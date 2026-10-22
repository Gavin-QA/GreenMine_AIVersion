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


from .network_monitor import NetworkMonitorMixin
from .dom_extractor import DomExtractorMixin
from .screenshot import ScreenshotMixin
from .chart_probe import ChartProbeMixin

class ElectronDriver(NetworkMonitorMixin, DomExtractorMixin, ScreenshotMixin, ChartProbeMixin):
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
        
        # 全局唯一接口注册表 (永久驻留，URL -> 最新规范报文，彻底解决轮询冲刷覆盖问题)
        self.api_registry: Dict[str, dict] = {}
        
        # 页面专属作用域注册表 (严格隔离各二级页面的网络包，彻底杜绝历史旧接口串扰)
        self.current_page_scope: str = "_global_shared"
        self.page_scoped_registry: Dict[str, Dict[str, dict]] = {"_global_shared": {}}
        
        # 后台静默报错捕获池 (Console Errors, Network Errors)
        self.caught_bugs = []
        
        # 记录最后一次鼠标交互坐标，用于在截图中硬核绘制真实光标
        self.last_mouse_pos = None

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

        # ========================================================
        # [Startup Probe] 伴生 UE 进程健康探针
        # ========================================================
        if settings.ue_process_name:
            try:
                self.launcher.wait_for_ue_process(
                    process_name=settings.ue_process_name,
                    timeout=settings.startup_timeout
                )
            except Exception as e:
                logger.error(f"❌ 伴生 UE 核心引擎探测失败: {e}")
                raise

        # ========================================================
        # [Startup Probe] 页面真实跳转与大屏就绪探针
        # ========================================================
        if settings.expected_page_url or settings.expected_page_title:
            try:
                self.page = self.launcher.wait_for_page_transition(
                    expected_url_keyword=settings.expected_page_url,
                    expected_title_keyword=settings.expected_page_title,
                    timeout=settings.startup_timeout
                )
            except Exception as e:
                logger.warning(f"⚠️ 页面跳转探测异常: {e}")
                self.page = self.get_active_page()
        else:
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
            self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            logger.info("⏳ 快速检测前端网络初始缓冲 (networkidle)...")
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            logger.info("⚡ 前端底层已加载完毕，后台轮询接口交由监听池持续捕获。")

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


    # =========================================================================
    # 纯视觉交互核心接口 (Vision Actions)
    # =========================================================================



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

        self.last_mouse_pos = (x, y)
        logger.info(f"👉 模拟物理点击: 坐标 ({x}, {y}) [button={button}]")
        
        # 1. 模拟真人平滑移动鼠标过去 (PixelStreaming 经常需要检测持续的 MouseMove 才能触发 UE 内部的 Hover 事件)
        self.page.mouse.move(x, y, steps=10)
        time.sleep(0.2)
        
        # 2. 尝试强制让目标获取焦点 (防止部分 WebRTC 播放器不在焦点时不接收输入)
        try:
            self.page.evaluate(f"document.elementFromPoint({x}, {y})?.focus()")
        except Exception:
            pass

        # 3. 严格遵循用户要求：先使用 CDP 的事件点击 (最纯净，兼容绝大多数前端与 3D WebRTC 引擎)
        try:
            self.page.mouse.down(button=button)
            time.sleep(0.1)
            self.page.mouse.up(button=button)
            logger.info(f"✨ 触发纯净 CDP 鼠标点击: ({x}, {y}) [button={button}]")
        except Exception as cdp_err:
            logger.warning(f"⚠️ CDP 虚拟点击失败 ({cdp_err})，自动降级为 PyAutoGUI 硬件鼠标点击...")
            
            # 4. 如果 CDP 失败，换 PyAutoGUI 操作系统级硬件鼠标兜底
            try:
                import pyautogui
                import ctypes
                pyautogui.FAILSAFE = False
                
                # 声明 Python 进程 DPI 感知，防止高分屏下坐标偏移
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    pass
                
                # 获取浏览器窗口在显示器上的物理绝对坐标与 DPI 缩放比
                rect = self.page.evaluate("() => ({screenX: window.screenX, screenY: window.screenY, innerWidth: window.innerWidth, outerWidth: window.outerWidth, innerHeight: window.innerHeight, outerHeight: window.outerHeight, dpr: window.devicePixelRatio || 1})")
                dpr = rect['dpr']
                
                border_x = (rect['outerWidth'] - rect['innerWidth']) / 2 if rect['outerWidth'] > rect['innerWidth'] else 0
                border_y = (rect['outerHeight'] - rect['innerHeight']) - border_x if rect['outerHeight'] > rect['innerHeight'] else 0
                
                # 换算为显示器真实的物理像素
                abs_x = int((rect['screenX'] + border_x + x) * dpr)
                abs_y = int((rect['screenY'] + border_y + y) * dpr)
                
                # 将物理鼠标真实移过去
                pyautogui.moveTo(abs_x, abs_y, duration=0.1)
                pyautogui.mouseDown(button=button)
                time.sleep(0.05)
                pyautogui.mouseUp(button=button)
                
                logger.info(f"✨ 触发 PyAutoGUI 操作系统级原生点击: 逻辑坐标({x},{y}) -> 物理屏幕坐标 ({abs_x}, {abs_y})")
            except ImportError:
                logger.error("未安装 pyautogui，硬件鼠标兜底失败！")
            except Exception as py_err:
                logger.error(f"PyAutoGUI 原生点击也发生异常: {py_err}")
            
        if delay_after > 0:
            time.sleep(delay_after)

    def double_click(self, x: int, y: int, delay_after: float = 0.5):
        """在屏幕绝对坐标 (x, y) 处执行双击"""
        if not self.page:
            raise RuntimeError("页面未就绪！")

        self.last_mouse_pos = (x, y)
        logger.info(f"👉 模拟物理双击: 坐标 ({x}, {y})")
        self.page.mouse.dblclick(x, y)
        if delay_after > 0:
            time.sleep(delay_after)

    def hover(self, x: int, y: int, delay_after: float = 0.3):
        """移动鼠标光标悬停至指定 (x, y) 坐标"""
        if not self.page:
            raise RuntimeError("页面未就绪！")

        self.last_mouse_pos = (x, y)
        logger.info(f"👉 鼠标移动悬停: 坐标 ({x}, {y})")
        # ====================================================================
        # [CRITICAL WARNING / 核心警告] 绝对不要删除 steps=10 参数！
        # ====================================================================
        # 很多复杂的 Vue/React 组件或 UE5 等渲染引擎在判断 hover 交互时，强依赖于
        # 完整的鼠标移动轨迹（MouseMove 事件序列）。如果去掉 steps，Playwright 的鼠标
        # 会“瞬间转移(Teleport)”到目标，导致前端底层无法触发 mouseenter 或 hover 状态，
        # 从而让依靠悬停展示的二级菜单永远无法弹出！请勿随意修改！
        self.page.mouse.move(x + 1, y + 1, steps=10)
        self.page.mouse.move(x, y)
        

        
        if delay_after > 0:
            time.sleep(delay_after)

    def cascade_click_with_probe(self, l1_x: int, l1_y: int, l2_x: int, l2_y: int, timeout_sec: float = 0.8) -> bool:
        """
        带安全气囊的原子级级联点击：
        1. 物理悬停一级菜单
        2. 毫秒级 DOM 探针检测二级菜单浮层是否真正激活弹出
        3. 若浮层已展开，立即在 200ms 内点击二级菜单（绝不给浮层失焦缩回的机会）
        4. 若探针未检测到浮层弹出，立刻安全刹车放弃点击，坚决防止盲目点击击穿背景！
        :return: True 表示级联成功点击；False 表示未展开浮层安全放弃
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"⚡ [Cascade Click] 启动级联点击安全序列: 一级锚点({l1_x}, {l1_y}) -> 二级锚点({l2_x}, {l2_y})")
        # 1. 执行真人体感平滑悬停
        self.hover(l1_x, l1_y, delay_after=0.1)

        # 2. 毫秒级 DOM 探针检测是否有下拉菜单/弹层容器可见
        start_t = time.time()
        dropdown_active = False
        while time.time() - start_t < timeout_sec:
            try:
                dropdown_active = self.page.evaluate("""() => {
                    const selectors = [
                        '.el-dropdown-menu', '.ant-dropdown', '.dropdown-menu', 
                        '.sub-menu', '[class*="dropdown"]', '[class*="submenu"]',
                        '[class*="menu-item"]', '[class*="popover"]'
                    ];
                    for (const sel of selectors) {
                        const nodes = document.querySelectorAll(sel);
                        for (const n of nodes) {
                            if (n.offsetParent !== null && window.getComputedStyle(n).display !== 'none') {
                                return true;
                            }
                        }
                    }
                    return false;
                }""")
                if dropdown_active:
                    break
            except Exception:
                pass
            time.sleep(0.08)

        # 3. 闭环决策：验货成功才允许发射点击
        if dropdown_active:
            logger.info("🛡️ [Cascade Probe] 探针验证成功：二级菜单浮层已稳定展开，立即执行原子点击！")
            self.click(l2_x, l2_y, button="left", delay_after=0.5)
            return True
        else:
            logger.warning("🛑 [Cascade Probe] 安全气囊生效：未检测到下拉浮层展开！为防止击空或误触背景，安全放弃第二步点击！")
            return False

    def drag(self, from_x: int, from_y: int, to_x: int, to_y: int, button: str = "left", steps: int = 15, delay_after: float = 0.5):
        """
        按住鼠标指定按键从 (from_x, from_y) 平滑拖拽至 (to_x, to_y)
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        self.last_mouse_pos = (to_x, to_y)
        logger.info(f"👉 模拟拖拽 [{button}]: ({from_x}, {from_y}) -> ({to_x}, {to_y})")
        self.page.mouse.move(from_x, from_y)
        self.page.mouse.down(button=button)
        self.page.mouse.move(to_x, to_y, steps=steps)
        self.page.mouse.up(button=button)
        if delay_after > 0:
            time.sleep(delay_after)

    def mouse_wheel(self, x: int = None, y: int = None, delta_x: float = 0, delta_y: float = -300, delay_after: float = 1.0):
        """
        在指定坐标处触发鼠标滚轮滚动 (支持三维数字孪生视点缩放与长列表滚动)
        :param x: 目标水平坐标 (若为空则默认屏幕中心)
        :param y: 目标垂直坐标 (若为空则默认屏幕中心)
        :param delta_x: 水平滚动偏移量
        :param delta_y: 垂直滚动偏移量 (负值向上滚/放大，正值向下滚/缩小)
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        vp = self.get_viewport_info()
        target_x = x if x is not None else vp.get("width", self.default_width) // 2
        target_y = y if y is not None else vp.get("height", self.default_height) // 2

        self.last_mouse_pos = (target_x, target_y)
        logger.info(f"🎡 触发鼠标滚轮: 坐标 ({target_x}, {target_y}) [deltaX={delta_x}, deltaY={delta_y}]")
        self.page.mouse.move(target_x, target_y)
        self.page.mouse.wheel(delta_x, delta_y)
        if delay_after > 0:
            time.sleep(delay_after)

    def zoom_3d(self, x: int = None, y: int = None, direction: str = "in", steps: int = 3, delay_after: float = 1.0):
        """
        针对三维孪生视口执行镜头推进(Zoom In)或拉远(Zoom Out)
        :param direction: "in" (放大推进) 或 "out" (缩小拉远)
        :param steps: 滚轮滚动阶数
        """
        delta = -250 * steps if direction.lower() in ["in", "放大", "推进"] else 250 * steps
        action_name = "放大镜头推进 (Zoom In)" if delta < 0 else "缩小镜头拉远 (Zoom Out)"
        logger.info(f"🔭 执行 3D 数字孪生镜头缩放: {action_name} | 阶数: {steps}")
        self.mouse_wheel(x=x, y=y, delta_y=delta, delay_after=delay_after)

    def rotate_3d(self, center_x: int = None, center_y: int = None, direction: str = "left", distance: int = 250, button: str = "right", delay_after: float = 1.0):
        """
        针对三维数字孪生场景执行视点轨道旋转(Orbit / Pitch / Rotate)
        支持 UE5 PixelStreaming / WebGL / Three.js 视角平滑拖拽变换
        :param direction: 旋转方向 ("left" | "right" | "up" | "down")
        :param distance: 拖拽滑动像素跨度
        :param button: 触发旋转的鼠标按键 ("right" 默认右键 | "left")
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        vp = self.get_viewport_info()
        cx = center_x if center_x is not None else vp.get("width", self.default_width) // 2
        cy = center_y if center_y is not None else vp.get("height", self.default_height) // 2

        half = distance // 2
        dir_clean = direction.lower().strip()
        if dir_clean in ["left", "向左", "左"]:
            from_x, from_y = cx + half, cy
            to_x, to_y = cx - half, cy
            desc = f"向左轨道旋转 3D 视角 ({distance}px)"
        elif dir_clean in ["right", "向右", "右"]:
            from_x, from_y = cx - half, cy
            to_x, to_y = cx + half, cy
            desc = f"向右轨道旋转 3D 视角 ({distance}px)"
        elif dir_clean in ["up", "向上", "俯仰上", "上"]:
            from_x, from_y = cx, cy + half
            to_x, to_y = cx, cy - half
            desc = f"向上俯仰 3D 视角 ({distance}px)"
        else: # down
            from_x, from_y = cx, cy - half
            to_x, to_y = cx, cy + half
            desc = f"向下俯仰 3D 视角 ({distance}px)"

        logger.info(f"🔄 执行 3D 视点轨道旋转: {desc} | 核心原点 ({cx}, {cy})")
        self.drag(from_x, from_y, to_x, to_y, button=button, steps=20, delay_after=delay_after)

    def scroll_element(self, x: int = None, y: int = None, direction: str = "down", delta: int = 300, delay_after: float = 1.0):
        """
        在指定组件容器（长表格、滚动卡片、历史报警列表等）内执行物理滚轮翻页
        :param x: 目标区域中心水平像素坐标 (若为空则默认当前鼠标位置或屏幕中心)
        :param y: 目标区域中心垂直像素坐标
        :param direction: 滚动方向 ("down" | "up" | "right" | "left")
        :param delta: 滚动的像素幅度
        :param delay_after: 滚动后等待界面渲染时间
        """
        dir_clean = str(direction).lower().strip()
        delta_x = 0
        delta_y = 0
        if dir_clean in ["down", "向下", "下"]:
            delta_y = abs(delta)
        elif dir_clean in ["up", "向上", "上"]:
            delta_y = -abs(delta)
        elif dir_clean in ["right", "向右", "右"]:
            delta_x = abs(delta)
        elif dir_clean in ["left", "向左", "左"]:
            delta_x = -abs(delta)
        else:
            delta_y = abs(delta)

        logger.info(f"📜 容器物理滚轮: 方向={dir_clean}, 偏移量=({delta_x}, {delta_y})")
        self.mouse_wheel(x=x, y=y, delta_x=delta_x, delta_y=delta_y, delay_after=delay_after)

    def slide(self, start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 15, delay_after: float = 1.0):
        """
        针对时间轴(Timeline Slider)、区间拖动条等组件执行连续物理拖拽滑块
        :param start_x: 滑块起始水平像素坐标
        :param start_y: 滑块起始垂直像素坐标
        :param end_x: 滑动目标水平像素坐标
        :param end_y: 滑动目标垂直像素坐标
        :param steps: 轨迹平滑插值步数
        :param delay_after: 释放后界面响应等待时间
        """
        logger.info(f"🎚️ 执行滑块/时间轴连续平滑拖拽: ({start_x}, {start_y}) -> ({end_x}, {end_y})")
        self.drag(from_x=start_x, from_y=start_y, to_x=end_x, to_y=end_y, button="left", steps=steps, delay_after=delay_after)

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

    def clear_and_type(self, x: int, y: int, text: str, press_enter: bool = False, delay_after: float = 0.5):
        """
        点击目标输入框，全选清除已有内容，并键入新文本 (支持可选回车触发搜索/提交)
        :param x: 输入框绝对水平坐标
        :param y: 输入框绝对垂直坐标
        :param text: 准备输入的文本或边界值
        :param press_enter: 输入完成后是否敲击 Enter 键
        :param delay_after: 完成后等待时间
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info(f"✍️ 清空并键入输入框: 坐标 ({x}, {y}) | 内容: '{text}' | Enter={press_enter}")
        self.click(x, y, delay_after=0.2)
        try:
            self.page.keyboard.press("Control+A")
            time.sleep(0.1)
            self.page.keyboard.press("Backspace")
            time.sleep(0.1)
        except Exception as e_clear:
            logger.warning(f"全选清空按键异常: {e_clear}")

        if text:
            self.type_text(text, delay_ms=30, delay_after=0.2)

        if press_enter:
            self.press_key("Enter", delay_after=0.3)

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

    def navigate_back(self, delay_after: float = 1.5):
        """
        执行路由历史回退 (支持单页路由 history.back 或快捷键 Alt+Left)
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info("🔙 执行路由/页面历史回退 (Back)...")
        try:
            self.page.go_back(timeout=3000)
        except Exception:
            try:
                self.page.evaluate("() => { if (window.history.length > 1) window.history.back(); }")
            except Exception:
                try:
                    self.page.keyboard.press("Alt+ArrowLeft")
                except Exception as e_back:
                    logger.warning(f"历史回退快捷键执行异常: {e_back}")

        if delay_after > 0:
            time.sleep(delay_after)

    def reload_page(self, delay_after: float = 2.0):
        """
        执行当前视口刷新与状态重置 (用于清洗污染的表单过滤死锁或卡死界面)
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        logger.info("🔄 刷新视口与重置页面状态 (Reload)...")
        try:
            self.page.reload(timeout=10000)
        except Exception as e_reload:
            logger.warning(f"页面重载异常: {e_reload}")

        if delay_after > 0:
            time.sleep(delay_after)

    def close(self):
        """清理连接与释放进程资源"""
        logger.info("正在关闭 Electron 驱动底座并释放资源...")
        
        # --- 避免显卡驱动蓝屏的优雅关闭方案 ---
        # 很多大屏端(UE5)若被暴力结束进程，显卡驱动来不及清理内存就会报 BSOD
        # 故通过物理点击关闭按钮和系统快捷键通知其正常进入 shutdown 流程
        if self.page and not self.page.is_closed():
            try:
                logger.info("尝试模拟手动点击右上角并发送 Alt+F4，以优雅关闭应用...")
                # RPA 方案 2：在发点击与按键前，强行将 Electron 窗口置顶并夺回前台焦点，防微信/弹窗抢焦
                if self.launcher and hasattr(self.launcher, "bring_to_foreground"):
                    try:
                        self.launcher.bring_to_foreground()
                    except Exception as e:
                        logger.debug(f"尝试前台激活 Electron 窗口: {e}")

                viewport = self.get_viewport_info()
                width = viewport.get("width", self.default_width)
                
                # 1. 点击大部分应用默认的关闭按钮区域 (右上方)
                close_x = int(width - 20)
                close_y = 20
                self.click(close_x, close_y, delay_after=1.0)
                
                # 2. 兜底策略：触发 Windows 标准退出指令
                self.page.keyboard.press("Alt+F4")
                try:
                    import pyautogui
                    pyautogui.hotkey('alt', 'f4')
                    logger.info("已通过 PyAutoGUI 触发硬件级 Alt+F4 关闭信号。")
                except ImportError:
                    pass
                time.sleep(2.0)
            except Exception as e:
                logger.warning(f"尝试优雅关闭窗口失败: {e}")

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