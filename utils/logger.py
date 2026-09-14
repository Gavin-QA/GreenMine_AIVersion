"""
寨湾 UI 自动化测试框架的日志模块。
提供集中的日志配置，支持控制台和文件双向输出。
支持彩色控制台输出及可配置的日志级别。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.artifacts import current_run_log_path
from config.settings import settings


class SafeUnicodeStreamHandler(logging.StreamHandler):
    """
    避免 Windows 代码页 UnicodeEncodeError 的控制台 Handler。

    Windows 下 subprocess/pytest 使用的某些终端会暴露 GBK/cp936 编码的 stdout。
    测试日志包含中文选择器或文本，因此标准的 StreamHandler 在格式化/打印时可能会失败。
    优先推荐将 stdout 重流向配置为 UTF-8；如果无法重配置，该 Handler 会替换无法编码的字符，
    而不是直接中断测试运行。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record)
                stream = self.stream
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe_msg = msg.encode(encoding, errors="replace").decode(encoding, errors="replace")
                stream.write(safe_msg + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)


# 尝试导入 colorlog 用于控制台彩色日志输出
try:
    import colorlog

    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False


class LoggerManager:
    """
    用于管理日志记录器实例的单例类。
    
    提供集中的日志配置，支持：
    - 彩色控制台输出（如果 colorlog 可用）
    - 带时间戳的文件日志输出
    - 多种日志级别
    """

    _instance: Optional["LoggerManager"] = None
    _logger: Optional[logging.Logger] = None

    def __new__(cls) -> "LoggerManager":
        """确保单例实例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化日志管理器。"""
        if self._logger is None:
            self._setup_logger()

    def _setup_logger(self) -> None:
        """使用 Handler 和 Formatter 配置日志记录器。"""
        # 获取此模块的根日志记录器
        self._logger = logging.getLogger("zhaiwan2UI")
        self._logger.setLevel(getattr(logging, getattr(settings, 'log_level', 'INFO').upper(), logging.INFO))

        # 避免重复添加 Handler
        if self._logger.handlers:
            return

        # 清除任何已存在的 Handler
        self._logger.handlers.clear()

        # 必要时创建日志目录
        log_file = Path(getattr(settings, 'log_file_path', 'logs/pytest_execution.log'))
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # 控制台 Handler
        if getattr(settings, 'log_to_console', True):
            console_handler = self._create_console_handler()
            self._logger.addHandler(console_handler)

        # 文件 Handler
        if getattr(settings, 'log_to_file', True):
            file_handler = self._create_file_handler()
            self._logger.addHandler(file_handler)

        self._logger.propagate = False

    def _create_console_handler(self) -> logging.Handler:
        """创建带合适格式化器的控制台 Handler。"""
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

        handler = SafeUnicodeStreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)

        if HAS_COLORLOG:
            # 使用 colorlog 的彩色格式化器
            formatter = colorlog.ColoredFormatter(
                fmt="%(log_color)s%(asctime)s [%(levelname)8s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "red,bg_white",
                },
                reset=True,
            )
        else:
            # 不带颜色的普通格式化器
            formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)8s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        handler.setFormatter(formatter)
        return handler

    def _create_file_handler(self) -> logging.Handler:
        """创建带详细格式化器的文件 Handler。"""
        run_log_file = current_run_log_path()
        settings.log_file_path = str(run_log_file)
        handler = logging.FileHandler(
            run_log_file,
            mode="w",
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)8s] %(filename)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        return handler

    @property
    def logger(self) -> logging.Logger:
        """获取配置好的日志记录器实例。"""
        return self._logger


def setup_logging() -> logging.Logger:
    """
    初始化并配置应用的日志记录系统。
    
    返回:
        logging.Logger: 配置好的日志记录器实例。
    """
    manager = LoggerManager()
    return manager.logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志记录器实例。
    
    参数:
        name: 日志记录器名称（通常为模块的 __name__）。
        
    返回:
        logging.Logger: 指定名称的日志记录器实例。
    """
    # 确保日志配置已初始化
    if LoggerManager()._logger is None:
        setup_logging()

    # 创建指定名称的子日志记录器
    return logging.getLogger(f"zhaiwan2UI.{name}")


# 模块导入时初始化日志系统
_logger = setup_logging()


def log_test_step(message: str, level: str = "INFO") -> None:
    """
    记录带时间戳的测试步骤。
    
    参数:
        message: 要记录的信息。
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)。
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_message = f"[STEP] {timestamp} - {message}"
    getattr(_logger, level.lower(), _logger.info)(log_message)


def log_action(action: str, details: Optional[str] = None) -> None:
    """
    记录测试操作及可选的详细信息。
    
    参数:
        action: 执行的操作说明。
        details: 可选的附加详细信息。
    """
    msg = f"[ACTION] {action}"
    if details:
        msg += f" | {details}"
    _logger.info(msg)


def log_assertion(description: str, passed: bool, expected: str = "", actual: str = "") -> None:
    """
    记录断言验证结果。
    
    参数:
        description: 断言检查项说明。
        passed: 断言是否通过。
        expected: 期望值（可选）。
        actual: 实际值（可选）。
    """
    status = "[PASSED]" if passed else "[FAILED]"
    msg = f"[ASSERT] {status} - {description}"

    if expected:
        msg += f" | Expected: {expected}"
    if actual:
        msg += f" | Actual: {actual}"

    if passed:
        _logger.info(msg)
    else:
        _logger.error(msg)

