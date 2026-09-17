import base64
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Generator, Optional, Tuple

import yaml
from playwright.sync_api import BrowserContext, Page

# 确保能正常引用 utils 模块
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.electron_launcher import ElectronLauncher
from config.settings import settings

# 初始化日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("core.browser")


class ElectronDriver:
    """
    纯视觉驱动框架的底座层封装 (Playwright over CDP)
    
    职责：
    1. 管理 Electron 进程生命周期与 CDP 连接（基于 ElectronLauncher）
    2. 捕获页面截图（提供原始字节流与 Base64 给大模型）
    3. 接收视觉模型解析的 (x, y) 坐标，执行物理鼠标/键盘事件
    4. 提供视口尺寸信息，保障模型视觉识别坐标与实际渲染严格 1:1 对齐
    """

    def __init__(
        self,
        exe_path: Optional[str] = None,
        debug_port: Optional[int] = None,
        **kwargs
    ):
        # 参数优先级：显式传参 > 全局 settings
        self.exe_path = exe_path or settings.app_path
        self.debug_port = debug_port or settings.cdp_port
        
        self.default_width = settings.default_width
        self.default_height = settings.default_height

        self.launcher: Optional[ElectronLauncher] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # 接口数据捕获池 (Rolling buffer of recent JSON responses)
        self.api_records = []
        
        # 后台静默报错捕获池 (Console Errors, Network Errors)
        self.caught_bugs = []

    def start(self) -> Page:
        """启动/连接 Electron 应用，并获取主页面 Target"""
        logger.info("=" * 50)
        logger.info("正在初始化 Electron 驱动底座...")
        logger.info(f"Target App: {self.exe_path}")
        logger.info(f"CDP Port:   {self.debug_port}")
        logger.info("=" * 50)

        self.launcher = ElectronLauncher(
            exe_path=self.exe_path,
            port=self.debug_port,
        )

        # 启动并建立 CDP 连接
        self.context, self.page = self.launcher.launch()

        # 等待并锁定有效页面
        self.page = self.get_active_page()

        # 挂载网络接口监听器
        self._setup_network_listeners()

        # 强制防御性刷新 (Ctrl+R)：
        # 1. 规避新启动时的竞态条件 (防止在挂载监听器前首屏 API 已发完而漏抓)
        # 2. 针对 Attach 模式，无伤重载前端而不掉线 UE
        logger.info("⚡ 正在执行防御性刷新 (Ctrl+R) 以确保完美捕获首屏 API 数据...")
        try:
            self.page.keyboard.press("Control+r")
            time.sleep(1)
        except Exception as e:
            logger.warning(f"模拟 Ctrl+R 失败: {e}")

        # 在启动器底层进行编程式判断，确保前端核心 DOM 已经加载完成
        try:
            logger.info("⏳ 等待应用前端底层加载 (domcontentloaded)...")
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            logger.info("⏳ 等待应用前端网络空闲 (networkidle)...")
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            logger.warning(f"⚠️ 前端底层状态等待超时，可能存在持续的轮询请求，将强制继续... ({e})")

        # 注册控制台日志与页面错误监听
        self._setup_page_listeners()

        # 获取并记录当前页面视口信息
        info = self.get_viewport_info()
        title = ""
        url = ""
        try:
            title = self.page.title()
            url = self.page.url
        except Exception:
            pass
        logger.info(f"[OK] 底座就绪，当前主页面: '{title}' ({url})")
        logger.info(f"[OK] 渲染视口尺寸: {info.get('width')}x{info.get('height')}, 缩放比(DPI): {info.get('devicePixelRatio')}")
        return self.page

    def get_active_page(self, wait_seconds: float = 5.0) -> Page:
        """
        获取当前可用且活跃的主页面。
        防止 Electron 冷启动、页面跳转或弹窗导致原有 Page 对象关闭或失效。
        """
        if self.page and not self.page.is_closed():
            try:
                # 简单测试一下页面通信是否正常
                _ = self.page.url
                return self.page
            except Exception:
                pass

        start_time = time.time()
        while time.time() - start_time < wait_seconds:
            if self.context:
                active_pages = [p for p in self.context.pages if not p.is_closed()]
                # 优先寻找真实业务 URL（排除 about:blank 与 devtools）
                for p in active_pages:
                    try:
                        u = p.url
                        if u and u != "about:blank" and not u.startswith("devtools://"):
                            self.page = p
                            return p
                    except Exception:
                        continue

                if active_pages:
                    self.page = active_pages[0]
                    return self.page

            time.sleep(0.5)

        return self.page

    def _setup_page_listeners(self):
        """挂载控制台日志与异常捕获"""
        if not self.page or self.page.is_closed():
            return
            
        def on_console(msg):
            if msg.type == "error":
                logger.debug(f"[Electron Console Error] {msg.text}")
                self.caught_bugs.append({"type": "console_error", "msg": msg.text})
            else:
                logger.debug(f"[Electron Console][{msg.type}] {msg.text}")

        def on_pageerror(err):
            logger.warning(f"[Electron PageError] {err}")
            self.caught_bugs.append({"type": "page_error", "msg": str(err)})

        try:
            self.page.on("console", on_console)
            self.page.on("pageerror", on_pageerror)
        except Exception:
            pass

    def _setup_network_listeners(self):
        """挂载底层 HTTP API 拦截器"""
        if not self.page or self.page.is_closed():
            return
            
        def handle_response(response):
            if response.request.method == "OPTIONS":
                return
                
            if response.status >= 400:
                self.caught_bugs.append({"type": "network_error", "url": response.url, "status": response.status})
                return
                
            if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                try:
                    data = response.json()
                    # 避免拦截巨大的无用报文或非业务接口
                    if data:
                        url_path = response.url.split("?")[0].split("/")[-1]
                        if len(url_path) < 2:
                            url_path = response.url.split("?")[0]
                        self.api_records.append({
                            "url": url_path,
                            "data": data
                        })
                except Exception:
                    pass
        
        self.page.on("response", handle_response)
        
    def clear_api_records(self):
        """清空缓存的网络接口记录，开始新的生命周期抓取"""
        self.api_records = []
        
    def get_api_records_summary(self) -> str:
        """返回最近拦截到的核心 JSON 数据（为了节约 Token，转为紧凑字符串）"""
        if not self.api_records:
            return "[]"
        import json
        # 取最近的 15 个接口防止过大
        recent_records = self.api_records[-15:]
        return json.dumps(recent_records, ensure_ascii=False)

    def get_and_clear_bugs(self) -> list:
        """获取并清空后台捕获到的所有异常报错"""
        bugs = list(self.caught_bugs)
        self.caught_bugs = []
        return bugs

    def get_viewport_info(self) -> Dict[str, Any]:
        """获取当前页面的内部视口宽高与设备像素比"""
        self.get_active_page()
        if not self.page or self.page.is_closed():
            return {"width": self.default_width, "height": self.default_height, "devicePixelRatio": 1.0}

        try:
            return self.page.evaluate("""() => ({
                width: window.innerWidth,
                height: window.innerHeight,
                devicePixelRatio: window.devicePixelRatio || 1.0
            })""")
        except Exception as e:
            logger.warning(f"获取页面视口信息失败: {e}")
            return {"width": self.default_width, "height": self.default_height, "devicePixelRatio": 1.0}

    def extract_interactive_elements(self) -> List[Dict[str, Any]]:
        """
        [Hybrid Mode] 提取视口内所有可见可交互元素的文本与几何包围盒 (BoundingRect)。
        用于 Midscene 风格的精确 DOM 匹配。
        """
        self.get_active_page()
        if not self.page or self.page.is_closed():
            return []

        js_code = """
        () => {
            // 获取所有元素，通过通用规则和样式来过滤可交互元素
            const elements = document.querySelectorAll('*');
            const results = [];
            let index = 0;
            
            for (const el of elements) {
                // 1. 基础过滤：排除不可见或在屏幕外的元素
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0 || rect.bottom <= 0 || rect.right <= 0 || 
                    rect.top >= window.innerHeight || rect.left >= window.innerWidth) {
                    continue;
                }
                
                // 2. 交互性判断：
                // a. 原生可交互标签
                const tag = el.tagName.toLowerCase();
                const isNativeInteractive = ['button', 'a', 'input', 'select', 'textarea'].includes(tag);
                // b. 具有可点击角色或属性
                const hasClickRole = ['button', 'menuitem', 'tab', 'link'].includes(el.getAttribute('role'));
                const hasOnClick = el.hasAttribute('onclick');
                // c. Vue/React 单页面应用常用做法：普通的 div/span 加上 cursor: pointer
                const style = window.getComputedStyle(el);
                const isPointer = style.cursor === 'pointer';
                // d. 包含直接文本的节点（很多大屏开发者会把普通的 div/span 当做按钮，且忘了加 cursor: pointer）
                const hasDirectText = Array.from(el.childNodes).some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0);
                
                if (isNativeInteractive || hasClickRole || hasOnClick || isPointer || hasDirectText) {
                    // 获取可读文本或标签
                    let text = el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '';
                    text = String(text).trim().replace(/\\n/g, ' ').slice(0, 50);
                    
                    // 如果本身没有文字，且不是 input，可能是一个纯图标，尽量尝试获取 aria-label
                    if (!text && !['input', 'textarea'].includes(tag)) {
                        text = el.getAttribute('title') || 'icon_or_empty';
                    }
                    
                    results.push({
                        id: index++,
                        tag: tag,
                        text: text,
                        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                    });
                }
            }
            return results;
        }
        """
        try:
            return self.page.evaluate(js_code)
        except Exception as e:
            logger.warning(f"获取页面可交互元素失败，自动回退到纯视觉模式: {e}")
            return []


    # =========================================================================
    # 纯视觉交互核心接口 (Vision Actions)
    # =========================================================================

    def capture_screenshot(self, save_path: Optional[str] = None) -> bytes:
        """
        截取当前窗口页面全屏截图
        
        :param save_path: 可选，保存截图的文件路径（自动创建目录）
        :return: 截图的二进制 PNG 字节流
        """
        self.get_active_page()
        if not self.page or self.page.is_closed():
            raise RuntimeError("页面尚未初始化或已关闭，无法截图！")

        # Electron 桌面应用通常为固定大屏尺寸，抓取当前 viewport
        png_bytes = self.page.screenshot(type="png", full_page=False)

        if save_path:
            out_file = Path(save_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "wb") as f:
                f.write(png_bytes)
            logger.info(f"截图已保存至: {out_file.resolve()}")

        return png_bytes

    def capture_screenshot_base64(self, save_path: Optional[str] = None) -> str:
        """
        截取屏幕并直接返回 Base64 编码字符串，便于多模态大模型 (Qwen-VL / GPT-4o) 组装 API 请求
        """
        png_bytes = self.capture_screenshot(save_path=save_path)
        return base64.b64encode(png_bytes).decode("utf-8")

    def click(self, x: int, y: int, button: str = "left", delay_after: float = 0.5):
        """
        在屏幕绝对坐标 (x, y) 位置执行物理鼠标点击
        
        :param x: 水平绝对像素坐标
        :param y: 垂直绝对像素坐标
        :param button: 鼠标按键 ("left" | "right" | "middle")
        :param delay_after: 点击后物理等待时间(秒)，等待界面渲染与动画反应
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"👉 模拟物理点击: 坐标 ({x}, {y}) [button={button}]")
        
        # 1. 模拟真人平滑移动鼠标过去 (PixelStreaming 经常需要检测持续的 MouseMove 才能触发 UE 内部的 Hover 事件)
        self.page.mouse.move(x, y, steps=10)
        time.sleep(0.2)
        
        # 2. 尝试强制让目标获取焦点 (防止部分 WebRTC 播放器不在焦点时不接收输入)
        try:
            self.page.evaluate(f"document.elementFromPoint({x}, {y})?.focus()")
        except Exception:
            pass

        # 3. 拆解按下和抬起动作，按压时间调整为 100ms (防止 300ms 被误判为长按，导致 DOM 点击失效)
        self.page.mouse.down(button=button)
        time.sleep(0.1)
        self.page.mouse.up(button=button)
        
        # 4. 终极 DOM 防御：如果目标是一个纯前端 DOM 元素（非 UE 画布），强制触发它的原生 click 事件！
        try:
            self.page.evaluate(f"document.elementFromPoint({x}, {y})?.click()")
        except Exception:
            pass
            
        if delay_after > 0:
            time.sleep(delay_after)

    def double_click(self, x: int, y: int, delay_after: float = 0.5):
        """在屏幕绝对坐标 (x, y) 处执行双击"""
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"👉 模拟物理双击: 坐标 ({x}, {y})")
        self.page.mouse.dblclick(x, y)
        if delay_after > 0:
            time.sleep(delay_after)

    def hover(self, x: int, y: int, delay_after: float = 0.3):
        """移动鼠标光标悬停至指定 (x, y) 坐标"""
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"👉 鼠标移动悬停: 坐标 ({x}, {y})")
        self.page.mouse.move(x, y)
        if delay_after > 0:
            time.sleep(delay_after)

    def drag(self, from_x: int, from_y: int, to_x: int, to_y: int, steps: int = 15, delay_after: float = 0.5):
        """
        按住鼠标从 (from_x, from_y) 拖拽至 (to_x, to_y)
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"👉 模拟拖拽: ({from_x}, {from_y}) -> ({to_x}, {to_y})")
        self.page.mouse.move(from_x, from_y)
        self.page.mouse.down()
        self.page.mouse.move(to_x, to_y, steps=steps)
        self.page.mouse.up()
        if delay_after > 0:
            time.sleep(delay_after)

    def type_text(self, text: str, delay_ms: int = 50, delay_after: float = 0.5):
        """
        向当前聚焦元素输入文本
        
        :param text: 输入字符内容
        :param delay_ms: 每个按键敲击间隔(毫秒)
        :param delay_after: 输入完成后的缓冲时间
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"⌨️ 键盘键入文本: '{text}' (按键间隔: {delay_ms}ms)")
        self.page.keyboard.type(text, delay=delay_ms)
        if delay_after > 0:
            time.sleep(delay_after)

    def press_key(self, key: str, delay_after: float = 0.5):
        """
        敲击特定功能按键 (如 'Enter', 'Escape', 'Tab', 'Backspace')
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"⌨️ 键盘敲击按键: [{key}]")
        self.page.keyboard.press(key)
        if delay_after > 0:
            time.sleep(delay_after)

    def scroll(self, delta_x: int = 0, delta_y: int = 0, x: Optional[int] = None, y: Optional[int] = None):
        """
        模拟滚轮滚动 (delta_y > 0 向下滚动，delta_y < 0 向上滚动)
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        if x is not None and y is not None:
            self.page.mouse.move(x, y)

        logger.info(f"📜 滚轮滑动: delta_x={delta_x}, delta_y={delta_y}")
        self.page.mouse.wheel(delta_x, delta_y)
        time.sleep(0.3)

    def wait(self, seconds: float):
        """物理等待（等待大屏渲染或动画完成）"""
        logger.info(f"⏳ 等待 {seconds} 秒...")
        time.sleep(seconds)

    def close(self):
        """清理连接与释放进程资源"""
        logger.info("正在关闭 Electron 驱动底座并释放资源...")
        if self.launcher:
            try:
                self.launcher.close()
            except Exception as e:
                logger.warning(f"关闭 launcher 时出现异常: {e}")
        self.launcher = None
        self.context = None
        self.page = None
        logger.info("[OK] 驱动底座清理完毕。")

    # 上下文管理器支持 (支持 with ElectronDriver() as driver: 语法)
    def __enter__(self):
        try:
            self.start()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# =============================================================================
# Pytest Fixture 兼容支持（若需要使用 pytest 运行传统用例，可直接复用）
# =============================================================================
try:
    import pytest
    from _pytest.fixtures import SubRequest

    @pytest.fixture(scope="session")
    def electron_driver() -> Generator[ElectronDriver, None, None]:
        """会话级 ElectronDriver 实例"""
        driver = ElectronDriver()
        driver.start()
        yield driver
        driver.close()

    @pytest.fixture(scope="function")
    def page(electron_driver: ElectronDriver) -> Generator[Page, None, None]:
        """函数级 Page fixture"""
        yield electron_driver.page

except ImportError:
    pass


if __name__ == "__main__":
    # 本地快速连通性自测
    print("正在测试 ElectronDriver 连通性...")
    driver = ElectronDriver()
    try:
        page = driver.start()
        print(f"连接成功！当前页面标题: {page.title()}, URL: {page.url}")
        
        # 测试截取一张测试图片验证底座能力
        test_screenshot = PROJECT_ROOT / "reports" / "driver_test.png"
        driver.capture_screenshot(str(test_screenshot))
        print(f"自测截图成功，已保存至: {test_screenshot}")
    finally:
        driver.close()