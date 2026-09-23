"""
settings.py — 读取环境变量及 .env 配置文件

统一集中管理寨湾大屏 UI 自动化测试框架的所有配置项，
包含 Electron 启动参数、CDP 调试端口、日志设置及报告生成元数据。
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import yaml

# 加载 .env 环境变量文件
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Settings:
    """自动化测试配置类（全局单一事实源）"""

    def __init__(self):
        # 1. 解析全局 config.yaml
        config_path = PROJECT_ROOT / "config.yaml"
        self._yaml_config = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self._yaml_config = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Warning: 读取 config.yaml 失败: {e}")

        app_cfg = self._yaml_config.get("app", {})
        llm_cfg = self._yaml_config.get("llm", {})

        # 2. 核心应用与调试配置（优先 .env，其次 yaml）
        self.app_path: str = os.getenv("APP_PATH") or app_cfg.get("exe_path", "")
        
        # 端口可以从 yaml 拿，环境变量优先级更高
        env_cdp_port = os.getenv("CDP_PORT")
        self.cdp_port: int = int(env_cdp_port) if env_cdp_port else int(app_cfg.get("debug_port", 9222))

        # 别名/兼容性映射
        self.client_path: str = self.app_path
        self.target_name: str = self.app_path
        self.debug_port: int = self.cdp_port
        
        # 视口配置
        viewport_cfg = app_cfg.get("viewport", {})
        self.default_width: int = viewport_cfg.get("width", 2560)
        self.default_height: int = viewport_cfg.get("height", 1440)
        self.device_pixel_ratio: float = viewport_cfg.get("device_pixel_ratio", 1.5)

        # 3. LLM 模型配置（优先 .env 保护敏感信息，其次 yaml）
        self.llm_provider: str = os.getenv("LLM_PROVIDER") or llm_cfg.get("provider", "openai")
        self.llm_api_key: str = os.getenv("LLM_API_KEY") or llm_cfg.get("api_key", "")
        self.llm_base_url: str = os.getenv("LLM_BASE_URL") or llm_cfg.get("base_url", "https://api.deepseek.com/v1")
        self.llm_model: str = os.getenv("LLM_MODEL") or llm_cfg.get("model", "deepseek-v4-flash-vision-exp")
        self.llm_timeout: float = float(os.getenv("LLM_TIMEOUT") or llm_cfg.get("timeout", 60.0))
        self.llm_temperature: float = float(os.getenv("LLM_TEMPERATURE") or llm_cfg.get("temperature", 0.1))

        # 4. 测试账号配置
        self.test_username: str = os.getenv("TEST_USERNAME", "")
        self.test_password: str = os.getenv("TEST_PASSWORD", "")
        self.test_account: str = self.test_username

        # 5. Electron 启动与运行参数
        self.headless: bool = os.getenv("HEADLESS", "false").lower() == "true"
        self.launch_args: list = []

        # 6. UE 伴生进程与页面跳转健康探测配置
        self.ue_process_name: str = os.getenv("UE_PROCESS_NAME") or app_cfg.get("ue_process_name", "zhaiwan.exe")
        self.expected_page_url: str = os.getenv("EXPECTED_PAGE_URL") or app_cfg.get("expected_page_url", "main.html")
        self.expected_page_title: str = os.getenv("EXPECTED_PAGE_TITLE") or app_cfg.get("expected_page_title", "主界面")
        self.startup_timeout: float = float(os.getenv("STARTUP_TIMEOUT") or app_cfg.get("startup_timeout", 40.0))
        self.start_delay: float = float(os.getenv("START_DELAY") or app_cfg.get("start_delay", 5.0))
        self.no_proxy: str = os.getenv("NO_PROXY") or app_cfg.get("no_proxy", "127.0.0.1,localhost,192.168.1.97,221.234.48.197,::1")

        # 7. 日志与报告配置
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.log_to_console: bool = os.getenv("LOG_TO_CONSOLE", "true").lower() == "true"
        self.log_to_file: bool = os.getenv("LOG_TO_FILE", "true").lower() == "true"
        self.log_file_path: str = os.getenv("LOG_FILE_PATH", "logs/pytest_execution.log")
        self.screenshot_on_failure: bool = os.getenv("SCREENSHOT_ON_FAILURE", "true").lower() == "true"


settings = Settings()

