"""
测试产物辅助工具，用于管理截图和日志。

该模块集中管理生成的测试输出路径，确保执行脚本生成一致的目录结构：
- logs/<run_id>/                 框架运行日志与历史数据
- logs/<run_id>/screenshots/     测试或探索过程中捕获的截图
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
LOGS_DIR = PROJECT_ROOT / "logs"


def ensure_artifact_dirs() -> None:
    """如果标准的产物目录不存在，则自动创建它们。"""
    for directory in (
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def report_run_id() -> str:
    """返回当前进程的稳定运行 ID，适用于产物文件命名。"""
    env_run_id = os.getenv("REPORT_RUN_ID")
    if env_run_id:
        return safe_filename(env_run_id, max_length=80)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.environ["REPORT_RUN_ID"] = run_id
    return run_id


def current_run_log_path(case_name: str, run_id: Optional[str] = None) -> Path:
    """返回当前测试运行的专用日志文件路径。"""
    run_id = run_id or report_run_id()
    run_log_dir = LOGS_DIR / run_id
    run_log_dir.mkdir(parents=True, exist_ok=True)
    return run_log_dir / f"{safe_filename(case_name)}_{run_id}.log"


def safe_filename(value: str, max_length: int = 180) -> str:
    """将任意文本转换为操作系统的安全文件名。"""
    value = value.replace("::", "_").replace("/", "_").replace("\\", "_")
    value = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", value)
    value = value.strip("._") or "artifact"
    if len(value) > max_length:
        value = value[:max_length].rstrip("._")
    return value


def timestamp() -> str:
    """返回用于产物命名的紧凑时间戳。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def screenshot_path(name: str) -> Path:
    """构建位于 logs/<run_id>/screenshots 下的专属截图路径。"""
    run_id = report_run_id()
    run_screenshot_dir = LOGS_DIR / run_id / "screenshots"
    run_screenshot_dir.mkdir(parents=True, exist_ok=True)
    return run_screenshot_dir / f"{safe_filename(name)}.png"


def read_text_tail(path: Path, max_chars: int = 120_000, start_offset: int = 0) -> str:
    """从指定偏移量读取 UTF-8 文本文件片段，并限制最大读取长度。"""
    if not path.exists():
        return ""
    with path.open("rb") as f:
        if start_offset > 0:
            f.seek(start_offset)
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        return "...（前序日志已截断，仅保留当前片段末尾）...\n" + text[-max_chars:]
    return text
