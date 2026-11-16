import base64
import logging
import os
import sys
import json
import math
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
        # 致命无声前端崩溃专属缓冲池 (Uncaught JS Error / Vue Render Crash / WebGL Lost，供 assert_no_console_errors 精准断言)
        self.fatal_js_crashes: List[Dict[str, Any]] = []
        self.non_fatal_console_errors: List[Dict[str, Any]] = []
        # 显存/内存与 DOM/监听器泄漏探针基线与时序轨迹池 (供 memory_leak_check 追踪)
        self.memory_baseline: Optional[Dict[str, Any]] = None
        self.memory_timeline: List[Dict[str, Any]] = []
        
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
        # 【UE 像素流安全红线】若伴生 UE 或 Attach 挂载模式，坚决禁止刷新 (包括 Ctrl+R)，避免打断 WebRTC 导致 UE 崩溃断流
        if settings.ue_process_name or settings.attach_existing:
            logger.info("🛡️ [UE Protection] 检测到伴生 UE 引擎或 Attach 挂载模式，跳过 Ctrl+R 防御性刷新以守护 WebRTC 像素流稳定。")
        else:
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

        # 挂载 CDP 静默下载拦截器 (彻底杜绝 Windows 原生阻塞式另存为弹窗)
        self._setup_download_interception(self.page)
        if self.context:
            try:
                self.context.on("page", lambda new_p: self._setup_download_interception(new_p))
            except Exception:
                pass

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






    def _setup_download_interception(self, target_page: Optional[Page] = None):
        """
        通过 CDP 协议激活静默下载拦截机制：
        1. 配置 Browser.setDownloadBehavior / Page.setDownloadBehavior 为 'allow' 并指定安全下载隔离区
        2. 注册 Playwright download 事件监听，自动静默取消或捕获，彻底杜绝调起 Windows 原生阻塞式 '另存为' 弹窗
        """
        page = target_page or self.page
        if not page or page.is_closed():
            return

        if getattr(page, "_download_interception_enabled", False):
            return

        download_dir = os.path.join(str(PROJECT_ROOT), "artifacts", "downloads")
        try:
            os.makedirs(download_dir, exist_ok=True)
        except Exception:
            pass

        cdp = None
        try:
            cdp = page.context.new_cdp_session(page)
            try:
                cdp.send("Browser.setDownloadBehavior", {
                    "behavior": "allow",
                    "downloadPath": download_dir,
                    "eventsEnabled": True
                })
            except Exception:
                cdp.send("Page.setDownloadBehavior", {
                    "behavior": "allow",
                    "downloadPath": download_dir
                })
            logger.info(f"🛡️ [Silent Download] CDP 静默下载接管已就绪 -> 隔离路径: {download_dir} (杜绝 Windows 原生阻塞式另存为弹窗)")
        except Exception as e:
            logger.debug(f"[Silent Download] 设置 CDP 静默下载失败: {e}")
        finally:
            if cdp is not None:
                try:
                    cdp.detach()
                except Exception:
                    pass

        try:
            def on_download(download):
                try:
                    fn = download.suggested_filename or "downloaded_file"
                    logger.info(f"📥 [Playwright Download] 捕获到底层文件下载: {fn} (URL: {download.url})")
                    download.cancel()
                    logger.info(f"🛡️ [Playwright Download] 已静默取消下载任务以释放带宽与磁盘: {fn}")
                except Exception as e:
                    logger.debug(f"[Playwright Download] 处理下载异常: {e}")

            page.on("download", on_download)
            page._download_interception_enabled = True
        except Exception as e:
            logger.debug(f"[Silent Download] 挂载 Playwright 下载监听异常: {e}")


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

    def _probe_3d_stream_health(self) -> Dict[str, Any]:
        """
        探测三维像素流 (UE5 WebRTC Video) 与 WebGL 画布在暴力交互后的存活健康度
        """
        if not self.page or self.page.is_closed():
            return {"healthy": False, "issues": ["Electron 页面句柄已关闭或断开"]}

        issues: List[str] = []
        # 1. 检测 WebGL 上下文是否丢失
        if hasattr(self, "probe_webgl_context_health"):
            for wi in self.probe_webgl_context_health():
                issues.append(str(wi.get("msg") or "WebGL 上下文丢失"))

        # 2. 检测 WebRTC 像素流大尺寸 <video> 状态与断流遮罩文案
        js_stream_check = """
        () => {
            const errs = [];
            const vw = window.innerWidth || 1920;
            const vh = window.innerHeight || 1080;
            // 检查主视口尺寸的像素流 video 标签
            const videos = document.querySelectorAll('video');
            videos.forEach((v, idx) => {
                const r = v.getBoundingClientRect();
                if (r.width >= vw * 0.45 && r.height >= vh * 0.45) {
                    if (v.error) {
                        errs.push(`UE5 像素流 Video[#${idx}] 媒体解码报错 (code=${v.error.code})`);
                    } else if (v.ended) {
                        errs.push(`UE5 像素流 Video[#${idx}] 推流已中断 (ended=true)`);
                    } else if (v.srcObject && (v.readyState === 0 || v.videoWidth === 0)) {
                        errs.push(`UE5 像素流 Video[#${idx}] 视频帧尺寸归零/断流 (readyState=${v.readyState}, videoWidth=${v.videoWidth})`);
                    }
                }
            });
            // 检查可见断流报错遮罩
            const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
            const fatalStreamTexts = ['WebRTC disconnected', 'Pixel Streaming disconnected', '像素流已断开', '推流连接断开', 'renderer process crashed'];
            for (const kw of fatalStreamTexts) {
                if (bodyText.toLowerCase().includes(kw.toLowerCase())) {
                    errs.push(`页面出现三维推流断连告警文案: "${kw}"`);
                }
            }
            return errs;
        }
        """
        try:
            dom_errs = self.page.evaluate(js_stream_check)
            if isinstance(dom_errs, list):
                issues.extend(str(x) for x in dom_errs if x)
        except Exception as e:
            issues.append(f"渲染进程无响应或 JS 执行超时: {e}")

        return {"healthy": len(issues) == 0, "issues": issues}

    def canvas_stress_drag(
        self,
        center_x: Optional[int] = None,
        center_y: Optional[int] = None,
        mode: str = "hybrid",
        rounds: int = 3,
        radius: int = 300,
        button: str = "right",
        delay_after: float = 1.5
    ) -> Dict[str, Any]:
        """
        3D 场景暴力晃动压力测试 (Canvas / UE5 WebRTC Stress Drag)
        在严格锁定的中央安全三维视口包围盒 [0.28W~0.72W, 0.20H~0.78H] 内，
        执行高频 8 字螺旋轨道甩动 + 正反向急停横扫 + 突发滚轮推拉风暴，
        专门诱发 UE5 像素流花屏断流、LOD 切换破面、WebGL Context Lost 与显存暴涨崩溃。
        绝对不触碰左右两翼 2D 业务面板、【一键隐藏】折叠条及右上角系统退出按钮！
        """
        if not self.page:
            raise RuntimeError("页面未就绪！")

        vp = self.get_viewport_info()
        w = int(vp.get("width", self.default_width))
        h = int(vp.get("height", self.default_height))

        # 物理级安全禁区围栏：严禁越出中央 3D 视口半步
        min_x, max_x = int(w * 0.28), int(w * 0.72)
        min_y, max_y = int(h * 0.20), int(h * 0.78)

        def clamp_x(val: float) -> int:
            return max(min_x, min(max_x, int(round(val))))

        def clamp_y(val: float) -> int:
            return max(min_y, min(max_y, int(round(val))))

        cx = clamp_x(center_x if center_x is not None else w // 2)
        cy = clamp_y(center_y if center_y is not None else h // 2)
        rounds = max(1, min(15, int(rounds)))
        rx = min(int(abs(radius)), (max_x - min_x) // 2 - 10)
        ry = min(int(abs(radius) * 0.65), (max_y - min_y) // 2 - 10)
        rx = max(40, rx)
        ry = max(30, ry)
        mode_clean = (mode or "hybrid").strip().lower()

        logger.info(
            f"🌪️ [3D Stress Drag] 启动三维视界暴力抗压晃动: mode={mode_clean}, rounds={rounds}, "
            f"radius=({rx},{ry}), button={button}, 安全围栏=[({min_x},{min_y})~({max_x},{max_y})]"
        )

        self.last_mouse_pos = (cx, cy)
        waypoints_executed = 0

        # 阶段 1：高频 8 字螺旋轨道旋转 + 正反向急停甩镜头
        if mode_clean in ("orbit", "whip", "hybrid", "all"):
            self.page.mouse.move(cx, cy)
            self.page.mouse.down(button=button)
            try:
                for r_idx in range(rounds):
                    # A. 8字利萨如曲线高速环绕 (12 采样点/圈)
                    segments = 12
                    for s in range(1, segments + 1):
                        theta = (2.0 * math.pi * s) / segments
                        phase = 1 if (r_idx % 2 == 0) else -1
                        tx = clamp_x(cx + phase * rx * math.sin(theta))
                        ty = clamp_y(cy + ry * math.sin(2.0 * theta))
                        self.page.mouse.move(tx, ty, steps=2)
                        waypoints_executed += 1
                    # B. 水平与俯仰正反向极限急甩 (诱发视锥体裁剪与动态贴图突发加载)
                    whip_pts = [
                        (clamp_x(cx - rx), cy),
                        (clamp_x(cx + rx), cy),
                        (cx, clamp_y(cy - ry)),
                        (cx, clamp_y(cy + ry)),
                        (cx, cy),
                    ]
                    for wx, wy in whip_pts:
                        self.page.mouse.move(wx, wy, steps=3)
                        waypoints_executed += 1
            finally:
                # 铁律：无论中间是否发生异常，必须释放鼠标按键防止右键粘连锁死！
                try:
                    self.page.mouse.up(button=button)
                except Exception:
                    pass

        # 阶段 2：突发 LOD 远近景高频滚轮风暴 (先急速推进再对等拉回原位)
        if mode_clean in ("zoom", "hybrid", "all"):
            self.page.mouse.move(cx, cy)
            burst_cnt = max(2, min(6, rounds + 1))
            for _ in range(burst_cnt):
                self.page.mouse.wheel(0, -360)
                waypoints_executed += 1
                time.sleep(0.05)
            time.sleep(0.15)
            for _ in range(burst_cnt):
                self.page.mouse.wheel(0, 360)
                waypoints_executed += 1
                time.sleep(0.05)

        if delay_after > 0:
            time.sleep(delay_after)

        health = self._probe_3d_stream_health()
        health["waypoints_executed"] = waypoints_executed
        health["center"] = (cx, cy)
        health["safe_bounds"] = [min_x, min_y, max_x, max_y]

        if health["healthy"]:
            logger.info(f"✅ [3D Stress Drag] 暴力晃动完成 ({waypoints_executed} 次高频位移/滚轮脉冲)，像素流与 WebGL 上下文健康存活！")
        else:
            logger.error(f"💥 [3D Stress Drag] 暴力晃动后检测到三维渲染/推流异常: {health['issues']}")

        return health

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
        【UE 像素流安全红线】坚决禁止使用 page.reload() 刷新网页！
        刷新网页会导致 WebRTC PeerConnection 句柄销毁、推流信令断开引起 UE5 崩溃。
        如需在极端死锁时彻底重置，请调用 restart_app() 安全重启启动器。
        """
        logger.warning("🚫 [UE Protection] 检测到页面刷新请求已拦截！在 WebRTC 像素流架构下，严禁刷新网页以防 UE 崩溃断流！")
        try:
            self.navigate_back(delay_after=1.0)
        except Exception:
            pass

        if delay_after > 0:
            time.sleep(delay_after)

    def close_active_modal(self, delay_after: float = 0.5) -> bool:
        """
        确定性直接关闭当前页面激活的模态弹窗、PDF/图纸预览或抽屉。
        优先命中前端专属 Teleport 挂载关闭叉号 (.class_teleportbox-close)，
        兜底命中通用 Element/AntD 弹窗关闭按钮，彻底避免纯视觉猜坐标或误触工具栏内部图标。
        """
        self.get_active_page()
        if not self.page or self.page.is_closed():
            return False

        try:
            closed = self.page.evaluate("""() => {
                // 1. 优先命中大屏专属 Teleport 挂载的关闭叉号
                const teleportClose = document.querySelector('.class_teleportbox-close, [class*="teleportbox-close"]');
                if (teleportClose) {
                    const style = window.getComputedStyle(teleportClose);
                    if (style.display !== 'none' && style.visibility !== 'hidden') {
                        teleportClose.click();
                        return true;
                    }
                }
                // 2. 通用 Element UI / Ant Design / Bootstrap 弹窗关闭按钮
                const modalClose = document.querySelector('.el-dialog__headerbtn, .ant-modal-close, .modal .close, [aria-label="Close"], .modal-close');
                if (modalClose) {
                    const style = window.getComputedStyle(modalClose);
                    if (style.display !== 'none' && style.visibility !== 'hidden') {
                        modalClose.click();
                        return true;
                    }
                }
                return false;
            }""")
            if closed:
                logger.info("🛡️ [Modal Close] 已通过底层原生 DOM 确定性触发弹窗关闭！")
                if delay_after > 0:
                    time.sleep(delay_after)
                return True
            return False
        except Exception as e:
            logger.warning(f"触发原生关闭弹窗异常: {e}")
            return False

    def restart_app(self, delay_after: float = 3.0) -> Page:
        """
        【安全冷重启】当大屏或界面彻底卡死时，优雅关闭当前 Electron/UE 启动器并冷重启重新挂载 CDP
        (坚决杜绝在浏览器内单方面 reload 导致 UE 像素流残损僵死)
        """
        logger.warning("🚨 [Launcher Restart] 检测到严重死锁/卡死无响应，正在安全关闭当前启动器并执行冷重启...")
        try:
            self.close()
        except Exception as e_close:
            logger.warning(f"关闭已有实例异常: {e_close}")

        time.sleep(3.0)  # 物理等待 3s 确保 Windows 回收 9222 端口与 GPU 显存，防止端口互斥

        logger.info("🚀 [Launcher Restart] 正在重新启动 Electron 客户端与推流底座...")
        page = self.start()
        if delay_after > 0:
            time.sleep(delay_after)
        logger.info("🎉 [Launcher Restart] 客户端重启完成，CDP 与推流已恢复健康就绪！")
        return page

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

    # =========================================================================
    # 显存/内存与句柄资源泄漏探针 (Memory / GPU / DOM / Listener Leak Probe)
    # =========================================================================
    def collect_garbage_cdp(self) -> bool:
        """通过底层 CDP 协议强制触发 V8 引擎 Full GC，剥离瞬态未回收垃圾，确保内存泄漏判定零误报"""
        if not self.page or self.page.is_closed():
            return False
        cdp = None
        try:
            cdp = self.page.context.new_cdp_session(self.page)
            cdp.send("HeapProfiler.collectGarbage")
            time.sleep(0.2)
            return True
        except Exception as e:
            logger.debug(f"[MemoryProbe] CDP 主动 GC 降级跳过: {e}")
            return False
        finally:
            if cdp is not None:
                try:
                    cdp.detach()
                except Exception:
                    pass

    def get_memory_metrics(self, label: str = "", trigger_gc: bool = False) -> Dict[str, Any]:
        """
        采集当前渲染进程的精确内存与渲染资源指标：
        - JSHeapUsedSize / JSHeapTotalSize (MB)
        - DOM Nodes 节点总数、JSEventListeners 事件监听器总数
        - ECharts 实例数、Canvas 画布数、Video 像素流/播放器实例数
        """
        if not self.page or self.page.is_closed():
            return {}

        if trigger_gc:
            self.collect_garbage_cdp()

        metrics_map: Dict[str, float] = {}
        cdp = None
        try:
            cdp = self.page.context.new_cdp_session(self.page)
            cdp.send("Performance.enable")
            raw_res = cdp.send("Performance.getMetrics")
            for item in raw_res.get("metrics", []):
                name = item.get("name")
                val = item.get("value")
                if name and isinstance(val, (int, float)):
                    metrics_map[name] = float(val)
        except Exception as e:
            logger.debug(f"[MemoryProbe] CDP Performance.getMetrics 降级 JS 采集: {e}")
        finally:
            if cdp is not None:
                try:
                    cdp.detach()
                except Exception:
                    pass

        dom_stats = {}
        js_stats = """
        () => {
            const mem = (window.performance && window.performance.memory) ? {
                usedJSHeapSize: window.performance.memory.usedJSHeapSize || 0,
                totalJSHeapSize: window.performance.memory.totalJSHeapSize || 0,
                jsHeapSizeLimit: window.performance.memory.jsHeapSizeLimit || 0
            } : {};
            return {
                perf_mem: mem,
                dom_nodes: document.getElementsByTagName('*').length,
                canvas_count: document.querySelectorAll('canvas').length,
                video_count: document.querySelectorAll('video').length,
                iframe_count: document.querySelectorAll('iframe').length,
                echarts_instances: document.querySelectorAll('[_echarts_instance_]').length
            };
        }
        """
        try:
            dom_stats = self.page.evaluate(js_stats) or {}
        except Exception:
            dom_stats = {}

        perf_mem = dom_stats.get("perf_mem") or {}
        heap_used_bytes = metrics_map.get("JSHeapUsedSize") or perf_mem.get("usedJSHeapSize") or 0.0
        heap_total_bytes = metrics_map.get("JSHeapTotalSize") or perf_mem.get("totalJSHeapSize") or 0.0
        dom_nodes = int(metrics_map.get("Nodes") or dom_stats.get("dom_nodes") or 0)
        js_listeners = int(metrics_map.get("JSEventListeners") or 0)

        # 通用宿主机与伴生引擎系统级物理内存采样 (完全动态解耦，零项目硬编码)
        try:
            from utils.system_guard import SystemMemoryGuard
            sys_mem = SystemMemoryGuard.sample_all_memory()
        except Exception:
            sys_mem = {}

        snapshot = {
            "label": label or "sample",
            "page_scope": getattr(self, "current_page_scope", "_global_shared"),
            "timestamp": round(time.time(), 3),
            "js_heap_used_mb": round(heap_used_bytes / (1024 * 1024), 2),
            "js_heap_total_mb": round(heap_total_bytes / (1024 * 1024), 2),
            "dom_nodes": dom_nodes,
            "js_event_listeners": js_listeners,
            "canvas_count": int(dom_stats.get("canvas_count") or 0),
            "video_count": int(dom_stats.get("video_count") or 0),
            "iframe_count": int(dom_stats.get("iframe_count") or 0),
            "echarts_instances": int(dom_stats.get("echarts_instances") or 0),
            "host_load_percent": sys_mem.get("host_load_percent", 0),
            "host_avail_mb": sys_mem.get("host_avail_mb", 0.0),
            "companion_name": sys_mem.get("companion_name"),
            "companion_mem_mb": sys_mem.get("companion_mem_mb", 0.0),
            "launcher_name": sys_mem.get("launcher_name"),
            "launcher_mem_mb": sys_mem.get("launcher_mem_mb", 0.0),
        }
        return snapshot

    def record_memory_snapshot(
        self,
        label: str = "snapshot",
        set_as_baseline: bool = False,
        trigger_gc: bool = False
    ) -> Dict[str, Any]:
        """记录单次内存与渲染资源水位快照，可选设为后续泄漏比对基线"""
        snap = self.get_memory_metrics(label=label, trigger_gc=trigger_gc)
        if not snap:
            return {}
        if not hasattr(self, "memory_timeline") or self.memory_timeline is None:
            self.memory_timeline = []
        self.memory_timeline.append(snap)
        if len(self.memory_timeline) > 500:
            self.memory_timeline = self.memory_timeline[-500:]
        if set_as_baseline or getattr(self, "memory_baseline", None) is None:
            self.memory_baseline = dict(snap)
            logger.info(
                f"📌 [MemoryProbe] 已锚定内存基线 [{label}]: "
                f"JSHeap={snap['js_heap_used_mb']}MB, DOM={snap['dom_nodes']}, Listeners={snap['js_event_listeners']}, "
                f"ECharts={snap['echarts_instances']}, Canvas={snap['canvas_count']}"
            )
        return snap

    def check_memory_leak(
        self,
        label: str = "memory_check",
        max_heap_mb: float = 1024.0,
        max_growth_mb: float = 300.0,
        max_growth_ratio: float = 2.5,
        max_dom_nodes: int = 50000,
        max_listener_growth: int = 5000,
        max_companion_mb: float = 6144.0,
        max_host_load_percent: float = 90.0,
        trigger_gc: bool = True
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        执行强制 GC 后的内存/显存句柄与 DOM/监听器泄漏综合判定。
        返回: (passed: bool, diagnostic_summary: str, current_snapshot: dict)
        """
        curr = self.record_memory_snapshot(label=label, set_as_baseline=False, trigger_gc=trigger_gc)
        if not curr:
            return True, "页面未就绪，跳过内存采集", {}

        base = getattr(self, "memory_baseline", None) or curr
        curr_heap = float(curr.get("js_heap_used_mb", 0.0))
        base_heap = float(base.get("js_heap_used_mb", 0.0))
        heap_growth_mb = round(curr_heap - base_heap, 2)
        heap_ratio = round(curr_heap / max(base_heap, 10.0), 2)

        curr_nodes = int(curr.get("dom_nodes", 0))
        base_nodes = int(base.get("dom_nodes", 0))
        node_growth = curr_nodes - base_nodes

        curr_listeners = int(curr.get("js_event_listeners", 0))
        base_listeners = int(base.get("js_event_listeners", 0))
        listener_growth = curr_listeners - base_listeners

        # 检测最近 4 次采样是否呈严格单调递增不回落趋势
        recent_heaps = [float(s.get("js_heap_used_mb", 0.0)) for s in (self.memory_timeline or [])[-4:]]
        is_monotonic_rising = (
            len(recent_heaps) == 4
            and recent_heaps[0] < recent_heaps[1] < recent_heaps[2] < recent_heaps[3]
            and (recent_heaps[-1] - recent_heaps[0]) >= 50.0
        )

        breaches: List[str] = []
        if curr_heap > max_heap_mb:
            breaches.append(f"JS 堆内存绝对值超限 ({curr_heap}MB > 阈值 {max_heap_mb}MB)")
        if heap_growth_mb > max_growth_mb:
            breaches.append(f"GC 后 JS 堆内存相对基线净暴涨 +{heap_growth_mb}MB (基线 {base_heap}MB -> 当前 {curr_heap}MB, 超阈值 +{max_growth_mb}MB)")
        if base_heap >= 30.0 and heap_growth_mb >= 80.0 and heap_ratio > max_growth_ratio:
            breaches.append(f"GC 后 JS 堆内存膨胀倍率异常 ({heap_ratio}x > 阈值 {max_growth_ratio}x, 基线 {base_heap}MB -> 当前 {curr_heap}MB)")
        if curr_nodes > max_dom_nodes:
            breaches.append(f"DOM 节点树未释放堆积超限 ({curr_nodes} 个 > 阈值 {max_dom_nodes} 个, 净增 +{node_growth})")
        if listener_growth > max_listener_growth:
            breaches.append(f"全局 JS 事件监听器严重泄漏未解绑 (净增 +{listener_growth} 个 > 阈值 +{max_listener_growth}, 当前 {curr_listeners})")

        # 检查外部伴生引擎 (UE 等 C++ 进程) 与宿主机内存
        curr_comp_mb = float(curr.get("companion_mem_mb", 0.0))
        comp_name = curr.get("companion_name") or "伴生引擎进程"
        host_load = int(curr.get("host_load_percent", 0))

        if curr_comp_mb > max_companion_mb:
            breaches.append(f"伴生引擎 [{comp_name}] 物理内存超限 ({curr_comp_mb:.1f}MB > 警戒线 {max_companion_mb:.1f}MB)")
        if host_load > max_host_load_percent:
            breaches.append(f"宿主机物理内存严重告急 ({host_load}% > 警戒线 {max_host_load_percent:.0f}%, 剩余 {curr.get('host_avail_mb', 0)}MB)")

        webgl_crashes = self.probe_webgl_context_health() if hasattr(self, "probe_webgl_context_health") else []
        for wc in webgl_crashes:
            breaches.append(str(wc.get("msg") or "WebGL 显存上下文丢失崩溃"))

        metrics_brief = (
            f"JSHeap: {base_heap}MB -> {curr_heap}MB (Δ={heap_growth_mb:+.2f}MB, {heap_ratio}x) | "
            f"DOM: {base_nodes} -> {curr_nodes} (Δ={node_growth:+d}) | "
            f"Listeners: {base_listeners} -> {curr_listeners} (Δ={listener_growth:+d}) | "
            f"ECharts={curr.get('echarts_instances', 0)}, Canvas={curr.get('canvas_count', 0)}, Video={curr.get('video_count', 0)}"
        )
        if comp_name and curr_comp_mb > 0:
            metrics_brief += f" | {comp_name}={curr_comp_mb:.1f}MB"
        if host_load > 0:
            metrics_brief += f" | HostRAM={host_load}%" 
        if is_monotonic_rising:
            metrics_brief += f" | ⚠️ 最近4次采样呈单调持续上涨趋势 {recent_heaps}"

        if breaches:
            summary = f"【前端内存/显存资源泄漏】{'; '.join(breaches)} | 探针详情: {metrics_brief}"
            logger.error(f"🚨 [MemoryProbe] 内存泄漏探针告警: {summary}")
            return False, summary, curr

        summary = f"内存与渲染句柄水位健康 | {metrics_brief}"
        logger.info(f"💚 [MemoryProbe] 探针核验通过 [{label}]: {summary}")
        return True, summary, curr

    def dump_memory_timeline(self, save_path: str) -> None:
        """导出完整内存时序轨迹至 JSON 文件，供报告追溯与离线分析"""
        try:
            out = Path(save_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "baseline": getattr(self, "memory_baseline", None),
                "sample_count": len(getattr(self, "memory_timeline", []) or []),
                "timeline": getattr(self, "memory_timeline", []) or []
            }
            with open(out, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f"📈 [MemoryProbe] 内存水位时序曲线已导出: {out}")
        except Exception as e:
            logger.warning(f"[MemoryProbe] 导出内存时序文件失败: {e}")

    def inspect_element_data_source(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        text_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        只读 Vue 组件数据血缘探针（零副作用，不刷新页面）：
        定位目标坐标 (x, y) 或文本提示对应的 DOM 元素，向上回溯 Vue2/Vue3 组件实例，
        判断展示数据是来自组件动态 state/props 还是前端模板静态硬编码。
        """
        if not self.page:
            return {"ok": False, "error": "page 未初始化"}

        js_code = """
        async ({ x, y, textHint }) => {
            try {
                let el = null;
                if (typeof x === 'number' && typeof y === 'number') {
                    el = document.elementFromPoint(x, y);
                }
                if ((!el || (textHint && !(el.innerText || '').includes(textHint))) && textHint) {
                    const all = Array.from(document.querySelectorAll('*'));
                    let best = null;
                    for (const node of all) {
                        if (node.children.length <= 3) {
                            const txt = (node.innerText || '').trim();
                            if (txt && txt.includes(textHint)) {
                                if (!best || txt.length < (best.innerText || '').trim().length) {
                                    best = node;
                                }
                            }
                        }
                    }
                    if (best) el = best;
                }
                if (!el) return { ok: false, error: '未命中目标 DOM 元素' };

                const domText = (el.innerText || el.textContent || '').trim().slice(0, 200);
                const probeToken = (textHint || domText.split(/\\s+/)[0] || '').trim();
                let cur = el;
                let vueVer = null;
                let compName = null;
                let compFile = null;
                let rawState = {};
                let renderStr = '';
                const wrapperClasses = [];

                while (cur) {
                    if (typeof cur.className === 'string' && cur.className) {
                        for (const c of cur.className.split(/\\s+/)) {
                            if (c.endsWith('Wrapper') && !wrapperClasses.includes(c)) {
                                wrapperClasses.push(c);
                            }
                        }
                    }
                    if (!vueVer && cur.__vue__) {
                        const vm = cur.__vue__;
                        vueVer = 2;
                        compName = (vm.$options && (vm.$options.name || vm.$options._componentTag)) || 'AnonymousVue2';
                        compFile = (vm.$options && vm.$options.__file) || null;
                        if (vm.$data) rawState.data = vm.$data;
                        if (vm.$props) rawState.props = vm.$props;
                        if (vm.$options && typeof vm.$options.render === 'function') {
                            try { renderStr = vm.$options.render.toString().slice(0, 6000); } catch (_) {}
                        }
                        break;
                    }
                    if (!vueVer && cur.__vueParentComponent) {
                        const inst = cur.__vueParentComponent;
                        vueVer = 3;
                        compName = (inst.type && (inst.type.name || inst.type.__name)) || 'AnonymousVue3';
                        compFile = (inst.type && inst.type.__file) || null;
                        if (inst.data) rawState.data = inst.data;
                        if (inst.props) rawState.props = inst.props;
                        if (inst.setupState) rawState.setupState = inst.setupState;
                        const rFn = inst.render || (inst.type && inst.type.render);
                        if (typeof rFn === 'function') {
                            try { renderStr = rFn.toString().slice(0, 6000); } catch (_) {}
                        }
                        break;
                    }
                    cur = cur.parentElement;
                }

                // 生产构建兜底：当 Vue3 剥离了 __vueParentComponent 时，通过 Wrapper 类名反查已加载的 JS Chunk 源码
                if (!vueVer) {
                    const genericWrappers = new Set(['bigScreenViewPageContentWrapper', 'bigScreenViewPageWrapper', 'bigScreenViewWrapper', 'outerFrame10Wrapper', 'layoutView9Wrapper', 'layoutView9WrapperRight']);
                    const targetWrappers = wrapperClasses.filter(c => !genericWrappers.has(c));
                    const candidateList = targetWrappers.length > 0 ? targetWrappers : wrapperClasses;

                    const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
                    const resources = performance.getEntriesByType('resource').filter(r => r.name.includes('.js')).map(r => r.name);
                    const allJs = Array.from(new Set([...scripts, ...resources]));

                    for (const cls of candidateList) {
                        for (const url of allJs) {
                            try {
                                const txt = await (await fetch(url)).text();
                                const idx = txt.indexOf(cls);
                                if (idx !== -1) {
                                    const chunkName = url.split('/').pop();
                                    const winStart = Math.max(0, idx - 1200);
                                    const winEnd = Math.min(txt.length, idx + 1200);
                                    const snippet = txt.slice(winStart, winEnd);
                                    const literalHit = probeToken && (
                                        snippet.includes(`"${probeToken}"`) ||
                                        snippet.includes(`'${probeToken}'`) ||
                                        snippet.includes(probeToken)
                                    );
                                    const verdict = literalHit ? 'HARDCODED_IN_BUNDLE' : 'DYNAMIC_IN_BUNDLE';
                                    const verdictDesc = literalHit
                                        ? `100% 实锤前端硬编码写死（"${probeToken}" 直接以字面量写死在组件 ${chunkName} [${cls}] 中）`
                                        : `组件 ${chunkName} [${cls}] 中未见 "${probeToken}" 硬编码字面量，疑似动态绑定或外部传入`;
                                    const summary = `🔬 [组件血缘探针] 生产包 Chunk: ${chunkName} (${cls}) | 判定: ${verdictDesc}`;
                                    return {
                                        ok: true,
                                        vue_found: true,
                                        mode: 'prod_bundle_chunk',
                                        component_name: cls,
                                        chunk_url: url,
                                        dom_text: domText,
                                        probe_token: probeToken,
                                        in_bundle_literal: Boolean(literalHit),
                                        verdict,
                                        verdict_desc: verdictDesc,
                                        summary
                                    };
                                }
                            } catch (_) {}
                        }
                    }

                    return {
                        ok: true,
                        vue_found: false,
                        dom_tag: el.tagName.toLowerCase(),
                        dom_text: domText,
                        verdict: 'NO_VUE_INSTANCE',
                        summary: `未找到 Vue 组件实例 (tag=${el.tagName.toLowerCase()}, text="${domText.slice(0, 60)}")`
                    };
                }

                const safeSerialize = (val, depth = 0) => {
                    if (val === null || val === undefined) return val;
                    if (typeof val === 'string') return val.length > 120 ? val.slice(0, 120) + '...' : val;
                    if (typeof val === 'number' || typeof val === 'boolean') return val;
                    if (typeof val === 'function') return '[Function]';
                    if (depth >= 3) return Array.isArray(val) ? `[Array(${val.length})]` : '[Object]';
                    if (Array.isArray(val)) {
                        return val.slice(0, 5).map(v => safeSerialize(v, depth + 1));
                    }
                    if (typeof val === 'object') {
                        const out = {};
                        const keys = Object.keys(val).filter(k => !k.startsWith('_') && !k.startsWith('$')).slice(0, 20);
                        for (const k of keys) {
                            try { out[k] = safeSerialize(val[k], depth + 1); } catch (_) { out[k] = '[Unreadable]'; }
                        }
                        return out;
                    }
                    return String(val);
                };

                const statePreview = safeSerialize(rawState, 0);
                const stateJson = JSON.stringify(statePreview) || '';
                const numMatches = (probeToken.match(/\\d+(?:\\.\\d+)?/g) || []);

                const inRender = probeToken ? renderStr.includes(probeToken) : false;
                let inState = probeToken ? stateJson.includes(probeToken) : false;
                if (!inState && numMatches.length > 0) {
                    inState = numMatches.some(n => stateJson.includes(n));
                }

                let verdict = 'UNKNOWN';
                let verdictDesc = '无法单凭组件快照确定来源';
                if (inRender && !inState) {
                    verdict = 'HARDCODED_IN_TEMPLATE';
                    verdictDesc = `疑似前端模板静态硬编码（"${probeToken}" 直接出现在 render() 字面量中，且组件 state/props 中无对应动态值）`;
                } else if (inState) {
                    verdict = 'DYNAMIC_FROM_STATE';
                    verdictDesc = `动态变量渲染（组件 state/props 中命中 "${probeToken}" 相关数据）`;
                } else if (!renderStr && Object.keys(statePreview).length === 0) {
                    verdict = 'STATIC_OR_EMPTY_STATE';
                    verdictDesc = '组件 state/props 为空，疑似纯静态展示组件';
                }

                const summary = `🔬 [组件血缘探针] Vue${vueVer} 组件: ${compName}${compFile ? ' (' + compFile + ')' : ''} | 判定: ${verdictDesc}`;
                return {
                    ok: true,
                    vue_found: true,
                    vue_version: vueVer,
                    component_name: compName,
                    component_file: compFile,
                    dom_text: domText,
                    probe_token: probeToken,
                    in_render_literal: inRender,
                    in_component_state: inState,
                    verdict,
                    verdict_desc: verdictDesc,
                    state_preview: statePreview,
                    summary
                };
            } catch (err) {
                return { ok: false, error: String(err) };
            }
        }
        """
        try:
            res = self.page.evaluate(js_code, {"x": x, "y": y, "textHint": text_hint})
            if isinstance(res, dict) and res.get("summary"):
                logger.info(res["summary"])
            return res if isinstance(res, dict) else {"ok": False, "error": "返回值异常"}
        except Exception as e:
            logger.warning(f"[DataSourceProbe] 组件血缘探针执行异常: {e}")
            return {"ok": False, "error": str(e)}

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