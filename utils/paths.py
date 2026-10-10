"""
测试产物辅助工具，用于统一管理框架运行产物、截图、日志、缺陷归档与知识资产。

架构分层体系：
1. 💎 全局持久资产 (artifacts/) - 长期沉淀、永不因日常日志清理误删
   - artifacts/bugs/              全局缺陷大盘总库 (global_bugs.json, global_bugs.md, global_bugs.csv)
   - artifacts/topology/          全局 UI 拓扑基线 (global_page_tree.json, auto_page_map.md)
   - artifacts/topology/snapshots/ 历史架构拓扑版本快照 (防止模型幻觉改坏树结构)

2. 📦 运行产物收敛区 (reports/runs/<run_id>/) - 一次运行对应一个独立完整目录
   - reports/runs/<run_id>/run.log               运行完整日志
   - reports/runs/<run_id>/checkpoint/           运行检查点与记忆 (global_history.json, page_tree.json, failed_counts.json)
   - reports/runs/<run_id>/bugs/                 单次运行捕获的缺陷凭证 (现场大图与报错详情 JSON)
   - reports/runs/<run_id>/screenshots/          探索/测试过程截图 (可按需安全瘦身)
   - reports/runs/<run_id>/generated_cases/      探索自动生成的 YAML 用例 (隔离保存，避免污染 test_cases/)

3. 📝 规范与用例源码
   - docs/                        只读设计规范与业务菜单骨架 (explore_rules.md 等)
   - test_cases/                  人工维护或晋升(Promote)的高价值稳定回归用例
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 1. 全局资产目录 (Permanent Artifacts)
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
GLOBAL_BUGS_DIR = ARTIFACTS_DIR / "bugs"
TOPOLOGY_DIR = ARTIFACTS_DIR / "topology"
TOPOLOGY_SNAPSHOTS_DIR = TOPOLOGY_DIR / "snapshots"

# 2. 运行时收敛目录 (Run Outputs)
REPORTS_DIR = PROJECT_ROOT / "reports"
RUNS_DIR = REPORTS_DIR / "runs"

# 3. 源码与规范目录
DOCS_DIR = PROJECT_ROOT / "docs"
TEST_CASES_DIR = PROJECT_ROOT / "test_cases"

# 向后兼容别名 (防止旧模块 import 出错)
LOGS_DIR = RUNS_DIR
BUGS_DIR = GLOBAL_BUGS_DIR


def ensure_artifact_dirs() -> None:
    """初始化所有标准的资产与输出目录结构。"""
    for directory in (
        GLOBAL_BUGS_DIR,
        TOPOLOGY_DIR,
        TOPOLOGY_SNAPSHOTS_DIR,
        RUNS_DIR,
        DOCS_DIR,
        TEST_CASES_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def report_run_id() -> str:
    """返回当前测试进程的全局唯一且稳定的运行 ID。"""
    env_run_id = os.getenv("REPORT_RUN_ID")
    if env_run_id:
        return safe_filename(env_run_id, max_length=80)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.environ["REPORT_RUN_ID"] = run_id
    return run_id


def get_run_dir(run_id: Optional[str] = None) -> Path:
    """获取单次运行的专属工作目录: reports/runs/<run_id>/"""
    rid = run_id or report_run_id()
    p = RUNS_DIR / rid
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_run_screenshots_dir(run_id: Optional[str] = None) -> Path:
    """获取单次运行的过程截图目录: reports/runs/<run_id>/screenshots/"""
    p = get_run_dir(run_id) / "screenshots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_run_bugs_dir(run_id: Optional[str] = None) -> Path:
    """获取单次运行捕获的缺陷凭据专属目录: reports/runs/<run_id>/bugs/"""
    p = get_run_dir(run_id) / "bugs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_run_checkpoint_dir(run_id: Optional[str] = None) -> Path:
    """获取单次运行记忆与续跑检查点目录: reports/runs/<run_id>/checkpoint/"""
    p = get_run_dir(run_id) / "checkpoint"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_run_generated_cases_dir(run_id: Optional[str] = None) -> Path:
    """获取单次运行闭环生成的 YAML 用例目录: reports/runs/<run_id>/generated_cases/"""
    p = get_run_dir(run_id) / "generated_cases"
    p.mkdir(parents=True, exist_ok=True)
    return p


def current_run_log_path(case_name: str, run_id: Optional[str] = None) -> Path:
    """返回当前测试运行的专用日志文件路径。"""
    run_dir = get_run_dir(run_id)
    return run_dir / f"{safe_filename(case_name)}_{run_id or report_run_id()}.log"


def screenshot_path(name: str, run_id: Optional[str] = None) -> Path:
    """构建位于 reports/runs/<run_id>/screenshots 下的专属截图路径。"""
    return get_run_screenshots_dir(run_id) / f"{safe_filename(name)}.png"


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
