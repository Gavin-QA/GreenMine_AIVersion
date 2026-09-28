import os
import subprocess
import time
import requests
import logging
from typing import Optional, List, Dict, Any, Tuple
from playwright.sync_api import sync_playwright, Page, BrowserContext

logger = logging.getLogger("electron_launcher")

class ElectronLauncher:
    def __init__(self, exe_path: str, port: int, launch_args: Optional[List[str]] = None):
        self.exe_path = exe_path
        self.port = port
        self.cdp_url = f"http://127.0.0.1:{self.port}"
        self.process: Optional[subprocess.Popen] = None
        self.playwright = None
        self.browser = None
        self.launch_args = launch_args or []
        self.was_already_running = False
        self._session = requests.Session()
        self._session.trust_env = False  # 彻底禁止 requests 读取环境变量代理，保障 CDP 直连
        self._session.proxies = {"http": None, "https": None}

    def is_cdp_alive(self) -> bool:
        """检查 CDP 调试端口是否已经就绪响应"""
        try:
            response = self._session.get(
                f"{self.cdp_url}/json/version",
                timeout=1
            )
            return response.status_code in [200, 403]
        except Exception:
            return False

    def start_app(self):
        """启动 Electron 客户端并暴露 CDP 调试端口"""
        if self.is_cdp_alive():
            logger.info(f"CDP 调试端口 {self.port} 已在运行中，跳过进程启动，直接重用已有客户端。")
            self.was_already_running = True
            return

        if not self.exe_path or not os.path.exists(self.exe_path):
            raise FileNotFoundError(f"❌ 找不到 Electron 可执行文件: '{self.exe_path}'，请检查 config.yaml 配置！")

        logger.info(f"正在启动 Electron 客户端: {self.exe_path} on port {self.port}...")

        # 设置工作目录为 exe 所在的根路径，确保 Electron/UE 引擎能正确读取相对路径下的前端资源
        cwd = os.path.dirname(self.exe_path)

        # 彻底清空从 Python 继承的系统代理环境变量，防止 Electron 内置 Node/NATS/WebRTC 走代理
        env = os.environ.copy()
        for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
            env.pop(proxy_var, None)

        # 显式设置 NO_PROXY 环境变量，保障本地与后端通信直连（优先从配置读取）
        try:
            from config.settings import settings
            no_proxy_val = getattr(settings, "no_proxy", "127.0.0.1,localhost,192.168.1.97,221.234.48.197,::1")
        except Exception:
            no_proxy_val = "127.0.0.1,localhost,192.168.1.97,221.234.48.197,::1"

        env["NO_PROXY"] = no_proxy_val
        env["no_proxy"] = no_proxy_val

        # 传入全套代理绕过参数，确保 WebRTC 像素流 (9527端口) 和本地 CDP (9222端口) 100% 本地直连
        proxy_args = [
            "--no-proxy-server",
            "--proxy-bypass-list=*",
            "--remote-allow-origins=*"
        ]
        cmd = [self.exe_path, f"--remote-debugging-port={self.port}"] + proxy_args + self.launch_args
        self.process = subprocess.Popen(cmd, cwd=cwd, env=env)

        self._wait_for_port()

    def launch(self) -> Tuple[BrowserContext, Page]:
        """启动并建立 CDP 连接，返回上下文与页面对象"""
        if not self.browser:
            if self.is_cdp_alive():
                self.was_already_running = True
            else:
                self.start_app()
            page = self.connect_playwright()
            context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            return context, page
        
        context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        pages = [p for p in context.pages if not p.is_closed()]
        page = pages[0] if pages else context.new_page()
        return context, page

    def _wait_for_port(self, timeout: int = 120):
        """等待 CDP 端口准备就绪"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_cdp_alive():
                logger.info("CDP 调试端口已就绪。")
                return
            
            # 进程意外崩溃快速失败，避免无效等待
            if self.process and self.process.poll() is not None:
                exit_code = self.process.poll()
                raise RuntimeError(
                    f"❌ Electron 客户端在启动后异常退出 (Exit Code: {exit_code})，无法建立 CDP 调试连接！请检查应用依赖或启动参数。"
                )
            time.sleep(1)

        raise TimeoutError(f"在 {timeout} 秒内无法连接到 CDP 端口 {self.port}")

    def connect_playwright(self) -> Page:
        """使用 Playwright 连接到已启动的 Electron CDP 端口"""
        if not self.playwright:
            self.playwright = sync_playwright().start()

        logger.info(f"Playwright 正在连接到 CDP: {self.cdp_url}...")
        self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_url)

        # 获取 Electron 的默认上下文和所有窗口
        context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        pages = context.pages
        logger.info(f"CDP 已成功连接，当前监测到 {len(pages)} 个 Page/Window Target:")
        for idx, p in enumerate(pages):
            try:
                logger.info(f"  Target [{idx}]: URL='{p.url}', Title='{p.title()}'")
            except Exception as e:
                logger.error(f"  Target [{idx}]: 无法获取信息: {e}")

        # 智能筛选真实的主页面（优先排除 about:blank 的背景页）
        main_page = None
        for p in pages:
            if p.url and p.url != "about:blank" and not p.url.startswith("devtools://"):
                main_page = p
                break

        if not main_page:
            main_page = pages[0] if pages else context.new_page()

        try:
            target_title = main_page.title()
        except Exception:
            target_title = "<unknown>"
        logger.info(f"已选定主页面 Target: URL='{main_page.url}', Title='{target_title}'")
        return main_page

    @staticmethod
    def get_process_info(process_name: str) -> Optional[dict]:
        """使用 Windows 原生 tasklist 获取进程的运行信息 (若有多个匹配进程，返回主进程/物理内存最大的进程)"""
        import csv
        import io
        cmd = ["tasklist", "/fo", "csv", "/nh", "/fi", f"imagename eq {process_name}"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk", errors="ignore", timeout=5)
            reader = csv.reader(io.StringIO(r.stdout.strip()))
            candidates = []
            for row in reader:
                if len(row) >= 5 and row[0].lower() == process_name.lower():
                    mem_str = row[4].strip()
                    try:
                        mem_kb = float(mem_str.lower().replace("k", "").replace(",", "").strip())
                    except Exception:
                        mem_kb = 0.0
                    candidates.append({
                        "name": row[0],
                        "pid": int(row[1]),
                        "session": row[2],
                        "session_num": row[3],
                        "mem_str": mem_str,
                        "mem_kb": mem_kb,
                    })
            if candidates:
                candidates.sort(key=lambda x: x["mem_kb"], reverse=True)
                return candidates[0]
        except Exception as e:
            logger.debug(f"检查进程 {process_name} 异常: {e}")
        return None

    @staticmethod
    def is_process_hung(process_name: str) -> bool:
        """检查进程是否处于 Not Responding (未响应卡死) 状态"""
        import csv
        import io
        cmd = ["tasklist", "/fo", "csv", "/nh", "/fi", f"imagename eq {process_name}", "/fi", "status eq not responding"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="gbk", errors="ignore", timeout=5)
            reader = csv.reader(io.StringIO(r.stdout.strip()))
            for row in reader:
                if len(row) >= 5 and row[0].lower() == process_name.lower():
                    return True
        except Exception:
            pass
        return False

    def wait_for_ue_process(self, process_name: str = "zhaiwan.exe", timeout: float = 40.0, min_memory_mb: float = 100.0) -> dict:
        """
        等待伴生 UE 进程启动并进入正常运行状态。
        若超时未拉起或发生持续卡死，则抛出明确异常实现快速失败。
        """
        logger.info(f"⏳ [UE Process Probe] 正在监听伴生 UE 进程 ({process_name}) 运行状态 (超时: {timeout}s)...")
        start_t = time.time()
        consecutive_hung = 0
        while time.time() - start_t < timeout:
            proc = self.get_process_info(process_name)
            if proc:
                if self.is_process_hung(process_name):
                    consecutive_hung += 1
                    if consecutive_hung >= 3:
                        raise RuntimeError(f"❌ [UE Process Probe] 检测到 UE 进程 ({process_name}, PID: {proc['pid']}) 持续处于未响应卡死状态 (Not Responding)！")
                    logger.warning(f"⚠️ [UE Process Probe] 检测到 UE 进程瞬时未响应 (第 {consecutive_hung}/3 次)，等待重试...")
                else:
                    consecutive_hung = 0
                
                # 解析工作集内存 (例如 "922,688 K" -> 901 MB)
                mem_mb = proc.get("mem_kb", 0.0) / 1024.0
                if mem_mb == 0.0:
                    mem_str = proc.get("mem_str", "")
                    try:
                        clean_kb = float(mem_str.lower().replace("k", "").replace(",", "").strip())
                        mem_mb = clean_kb / 1024.0
                    except Exception:
                        pass

                # 若内存过小，说明进程刚拉起、尚未真正装载 3D 资产，继续缓冲一下
                if min_memory_mb > 0 and 0 < mem_mb < min_memory_mb:
                    logger.info(f"⏳ [UE Process Probe] UE 进程已拉起 (PID: {proc['pid']}, 当前内存: {mem_mb:.1f}MB)，等待 3D 资产加载 (目标 > {min_memory_mb}MB)...")
                    time.sleep(1.5)
                    continue

                logger.info(f"✅ [UE Process Probe] 成功检测到 UE 核心引擎 ({proc['name']}, PID: {proc['pid']}, 工作集内存: {proc['mem_str']}) 正在健康运行！")
                return proc
            time.sleep(1.5)

        raise TimeoutError(f"❌ [UE Process Probe] 启动超时！在 {timeout} 秒内未能检测到 UE 核心引擎 ({process_name}) 启动，请检查显卡驱动或工程配置！")

    def wait_for_page_transition(
        self,
        expected_url_keyword: str = "main.html",
        expected_title_keyword: str = "主界面",
        timeout: float = 40.0
    ) -> Page:
        """
        等待 Electron 窗口完成真实页面跃迁，成功锁定到大屏主页面 Target。
        防止卡在白屏、启动页或 Loading 动画。
        """
        logger.info(f"⏳ [Page Transition Probe] 正在等待页面跃迁至大屏主界面 (URL关键词: '{expected_url_keyword}', 标题关键词: '{expected_title_keyword}', 超时: {timeout}s)...")
        start_t = time.time()
        
        while time.time() - start_t < timeout:
            if not self.browser or not self.browser.contexts:
                time.sleep(1.0)
                continue

            context = self.browser.contexts[0]
            pages = [p for p in context.pages if not p.is_closed()]
            
            for p in pages:
                try:
                    curr_url = p.url or ""
                    curr_title = p.title() or ""
                    
                    if curr_url.startswith("devtools://") or curr_url == "about:blank":
                        continue
                    
                    url_ok = (expected_url_keyword in curr_url) if expected_url_keyword else True
                    title_ok = (expected_title_keyword in curr_title) if expected_title_keyword else True
                    
                    # 只有当指定的过滤条件全部满足时（两者均指定需同时满足，单项指定满足单项），才判定跃迁完成
                    if url_ok and title_ok:
                        logger.info(f"✅ [Page Transition Probe] 页面跃迁成功！已锁定大屏主界面: URL='{curr_url}', Title='{curr_title}'")
                        return p
                except Exception:
                    pass
            time.sleep(1.0)
            
        logger.warning(f"⚠️ [Page Transition Probe] 未能在 {timeout} 秒内精确命中目标页面，将回退选定当前第一个非空白页面。")
        context = self.browser.contexts[0]
        for p in context.pages:
            if p.url and p.url != "about:blank" and not p.url.startswith("devtools://"):
                return p
        return context.pages[0] if context.pages else context.new_page()

    def close(self):
        """清理资源，关闭浏览器连接和进程"""
        if hasattr(self, "_session") and self._session:
            try:
                self._session.close()
            except Exception:
                pass

        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

        if self.process and not self.was_already_running:
            logger.info("等待 Electron 进程自然退出 (已取消强杀以防蓝屏)...")
            try:
                # 等待应用在前台收到关闭指令后自行退出
                self.process.wait(timeout=5)
                logger.info("Electron 进程已自然退出。")
            except subprocess.TimeoutExpired:
                logger.warning("Electron 进程未能按时退出，已放弃强杀以保护系统稳定。")
            except Exception as e:
                logger.warning(f"等待进程退出时发生异常: {e}")
            
            # 启动器关闭时，UE 引擎 (zhaiwan.exe) 会随之正常退出，不需要再用 taskkill 暴力强杀，避免导致显卡驱动蓝屏 (BSOD)。

            time.sleep(1.5)  # 物理等待 1.5s 确保 Windows 回收 9222 端口，防止连抽用例时端口死锁

        self.process = None

