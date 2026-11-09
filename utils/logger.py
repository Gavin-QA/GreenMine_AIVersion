"""
Electron AI Vision 视觉自动化巡检框架的日志模块。
提供集中的日志配置，支持控制台和文件双向输出。
支持彩色控制台输出、编码安全防护及按用例隔离的动态文件日志切换。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.paths import current_run_log_path
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
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe_msg = msg.encode(encoding, errors="replace").decode(encoding, errors="replace")
                stream.write(safe_msg + self.terminator)
            self.flush()
        except RecursionError:
            raise
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
    用于管理全局日志系统的单例管理器。

    提供集中的日志配置，支持：
    - 彩色控制台输出（如果 colorlog 可用）
    - Windows Unicode 编码安全容错
    - 针对测试用例的动态隔离文件日志输出 (switch_file_handler)
    - 可配置的全局日志级别
    """

    _instance: Optional["LoggerManager"] = None
    _logger: Optional[logging.Logger] = None
    _initialized: bool = False

    def __new__(cls) -> "LoggerManager":
        """确保单例实例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化日志管理器（确保仅配置一次）。"""
        if not LoggerManager._initialized:
            self._setup_logger()
            LoggerManager._initialized = True

    def _setup_logger(self) -> None:
        """使用 Handler 和 Formatter 配置根日志记录器。"""
        # 获取根日志记录器，拦截并管理所有子模块的日志
        self._logger = logging.getLogger()
        self._logger.setLevel(getattr(logging, getattr(settings, 'log_level', 'INFO').upper(), logging.INFO))

        # 清除外部库或 basicConfig 预注入的旧 Handler，确保接管为统一受控的 Handler
        for handler in self._logger.handlers[:]:
            self._logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        # 控制台 Handler (带 Unicode 编码安全与彩色格式化)
        if getattr(settings, 'log_to_console', True):
            console_handler = self._create_console_handler()
            self._logger.addHandler(console_handler)

        # 文件 Handler 会通过显式调用 switch_file_handler 进行挂载，不再默认创建

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

    def switch_file_handler(self, case_name: str) -> None:
        """动态切换日志文件，用于隔离不同用例的日志。"""
        # 移除现有的 FileHandler
        for handler in self._logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                self._logger.removeHandler(handler)
                handler.close()

        # 挂载新的 FileHandler
        if getattr(settings, 'log_to_file', True):
            file_handler = self._create_file_handler(case_name)
            self._logger.addHandler(file_handler)

    def _create_file_handler(self, case_name: str) -> logging.Handler:
        """创建带详细格式化器的文件 Handler。"""
        run_log_file = current_run_log_path(case_name)
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
        name: 日志记录器名称（通常为模块名或 __name__）。

    返回:
        logging.Logger: 指定名称的日志记录器实例。
    """
    # 确保全局日志配置已初始化
    if not LoggerManager._initialized:
        setup_logging()

    return logging.getLogger(name)


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

