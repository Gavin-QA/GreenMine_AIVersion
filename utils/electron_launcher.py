import os
import subprocess
import time
import requests
from playwright.sync_api import sync_playwright

class ElectronLauncher:
    def __init__(self, headless: bool = False, debug_port: int = 9222, launch_args: list = None, target_name: str = None, exe_path: str = None, port: int = None, **kwargs):
        self.exe_path = exe_path if exe_path else target_name  # 转换为目标应用路径
        self.port = port if port else debug_port
        self.cdp_url = f"http://localhost:{self.port}"
        self.process = None
        self.playwright = None
        self.browser = None
        self.launch_args = launch_args or []
        self.was_already_running = False

    def is_cdp_alive(self) -> bool:
        """检查 CDP 调试端口是否已经就绪响应"""
        try:
            response = requests.get(
                f"{self.cdp_url}/json/version",
                timeout=1,
                proxies={"http": None, "https": None}
            )
            return response.status_code == 200
        except Exception:
            return False

    def start_app(self):
        """启动 Electron 客户端并暴露 CDP 调试端口"""
        if self.is_cdp_alive():
            print(f"CDP 调试端口 {self.port} 已在运行中，跳过进程启动，直接重用已有客户端。")
            self.was_already_running = True
            return

        print(f"正在启动 Electron 客户端: {self.exe_path} on port {self.port}...")

        # 设置工作目录为 exe 所在的根路径，确保 Electron/UE 引擎能正确读取相对路径下的前端资源
        cwd = os.path.dirname(self.exe_path) if self.exe_path and os.path.exists(self.exe_path) else None

        # 彻底清空从 Python 继承的系统代理环境变量，防止 Electron 内置 Node/NATS/WebRTC 走代理
        env = os.environ.copy()
        for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
            env.pop(proxy_var, None)

        # 显式设置 NO_PROXY 环境变量，保障本地与后端通信直连
        no_proxy_val = "127.0.0.1,localhost,192.168.1.97,221.234.48.197,::1"
        env["NO_PROXY"] = no_proxy_val
        env["no_proxy"] = no_proxy_val

        # 传入全套代理绕过参数，确保 WebRTC 像素流 (9527端口) 和本地 CDP (9222端口) 100% 本地直连
        proxy_args = [
            "--no-proxy-server",
            "--proxy-bypass-list=*"
        ]
        cmd = [self.exe_path, f"--remote-debugging-port={self.port}"] + proxy_args + self.launch_args
        self.process = subprocess.Popen(cmd, cwd=cwd, env=env)

        self._wait_for_port()

    def launch(self):
        """兼容 conftest.py 中的调用，建立 CDP 连接"""
        if not self.browser:
            if self.is_cdp_alive():
                self.was_already_running = True
            else:
                self.start_app()
            page = self.connect_playwright()
            return self.browser.contexts[0], page
        
        context = self.browser.contexts[0]
        pages = [p for p in context.pages if not p.is_closed()]
        page = pages[0] if pages else context.new_page()
        return context, page

    def _wait_for_port(self, timeout: int = 30):
        """等待 CDP 端口准备就绪"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_cdp_alive():
                print("CDP 调试端口已就绪。")
                return
            time.sleep(1)

        raise TimeoutError(f"在 {timeout} 秒内无法连接到 CDP 端口 {self.port}")

    def connect_playwright(self):
        """使用 Playwright 连接到已启动的 Electron CDP 端口"""
        if not self.playwright:
            self.playwright = sync_playwright().start()

        print(f"Playwright 正在连接到 CDP: {self.cdp_url}...")
        self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_url)

        # 获取 Electron 的默认上下文和所有窗口
        context = self.browser.contexts[0]
        pages = context.pages
        print(f"CDP 已成功连接，当前监测到 {len(pages)} 个 Page/Window Target:")
        for idx, p in enumerate(pages):
            try:
                print(f"  Target [{idx}]: URL='{p.url}', Title='{p.title()}'")
            except Exception as e:
                print(f"  Target [{idx}]: 无法获取信息: {e}")

        # 智能筛选真实的主页面（优先排除 about:blank 的背景页）
        main_page = None
        for p in pages:
            if p.url and p.url != "about:blank" and not p.url.startswith("devtools://"):
                main_page = p
                break

        if not main_page:
            main_page = pages[0] if pages else context.new_page()

        print(f"已选定主页面 Target: URL='{main_page.url}', Title='{main_page.title()}'")
        return main_page

    def close(self):
        """清理资源，关闭浏览器连接和进程"""
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass

        if self.process and not self.was_already_running:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            print("Electron 进程已终止。")
            
            # 自动清理 UE 虚幻引擎孤儿渲染进程 (zhaiwan.exe)，彻底释放显存、内存与 9527 像素流端口
            try:
                subprocess.run(["taskkill", "/F", "/IM", "zhaiwan.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

            time.sleep(1.5)  # 物理等待 1.5s 确保 Windows 回收 9222 端口，防止连抽用例时端口死锁

