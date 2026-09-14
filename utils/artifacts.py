"""
Test artifact helpers for reports, screenshots, logs and Allure attachments.

This module centralises generated test output paths so pytest hooks and runner 
scripts produce a predictable report structure:

- reports/html/            pytest-html reports
- reports/allure-results/  raw Allure result files
- reports/allure-report/   generated Allure static report
- reports/allure-reports/  timestamped Allure static reports
- reports/screenshots/     screenshots captured by hooks/pages
- logs/                    framework and pytest logs
"""

from __future__ import annotations

import base64
import json
import os
import platform
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
REPORTS_DIR = PROJECT_ROOT / "reports"
HTML_REPORT_DIR = REPORTS_DIR / "html"
ALLURE_RESULTS_DIR = REPORTS_DIR / "allure-results"
ALLURE_REPORT_DIR = REPORTS_DIR / "allure-report"
ALLURE_REPORTS_DIR = REPORTS_DIR / "allure-reports"
SCREENSHOTS_DIR = REPORTS_DIR / "screenshots"
LOGS_DIR = PROJECT_ROOT / "logs"


def ensure_artifact_dirs() -> None:
    """Create all standard artifact directories if they do not exist."""
    for directory in (
        REPORTS_DIR,
        HTML_REPORT_DIR,
        ALLURE_RESULTS_DIR,
        ALLURE_REPORT_DIR,
        ALLURE_REPORTS_DIR,
        SCREENSHOTS_DIR,
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def report_run_id() -> str:
    """Return a stable run id for this process, suitable for report directories."""
    env_run_id = os.getenv("REPORT_RUN_ID")
    if env_run_id:
        return safe_filename(env_run_id, max_length=80)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.environ["REPORT_RUN_ID"] = run_id
    return run_id


def current_run_log_path(run_id: Optional[str] = None) -> Path:
    """Return the dedicated log file path for the current test run."""
    ensure_artifact_dirs()
    return LOGS_DIR / f"test_execution_{safe_filename(run_id or report_run_id(), max_length=80)}.log"


def allure_report_dir(run_id: Optional[str] = None) -> Path:
    """Build a timestamped Allure HTML report directory."""
    ensure_artifact_dirs()
    return ALLURE_REPORTS_DIR / safe_filename(run_id or report_run_id(), max_length=80)


def safe_filename(value: str, max_length: int = 180) -> str:
    """Convert a pytest node id or arbitrary text to a safe file name."""
    value = value.replace("::", "_").replace("/", "_").replace("\\", "_")
    value = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", value)
    value = value.strip("._") or "artifact"
    if len(value) > max_length:
        value = value[:max_length].rstrip("._")
    return value


def timestamp() -> str:
    """Return a compact timestamp for artifact names."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def screenshot_path(name: str) -> Path:
    """Build a screenshot path under reports/screenshots."""
    ensure_artifact_dirs()
    return SCREENSHOTS_DIR / f"{safe_filename(name)}.png"


def read_text_tail(path: Path, max_chars: int = 120_000, start_offset: int = 0) -> str:
    """Read a UTF-8 text file slice from an offset, capped to the tail length."""
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


def patch_allure_tree_data(report_dir: Path) -> None:
    """
    Ensure Allure report has data files required by Behaviors and Packages tabs.

    Some local Allure CLI/plugin combinations may render the Behaviors/Packages
    navigation entries but omit the generated JSON payloads, causing 404 in the
    report UI. Reusing suites.json keeps those tabs usable instead of broken.
    """
    data_dir = report_dir / "data"
    suites_file = data_dir / "suites.json"
    if not suites_file.exists():
        return
    fallback_map = {
        data_dir / "behaviors.json": "behaviors",
        data_dir / "packages.json": "packages",
    }
    for target, tree_name in fallback_map.items():
        if target.exists():
            continue
        payload = json.loads(suites_file.read_text(encoding="utf-8"))
        payload["name"] = tree_name
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        csv_target = target.with_suffix(".csv")
        suites_csv = data_dir / "suites.csv"
        if suites_csv.exists() and not csv_target.exists():
            shutil.copyfile(suites_csv, csv_target)


def html_img_from_png_bytes(png_bytes: bytes, title: str = "Screenshot") -> str:
    """Return an inline HTML image snippet for pytest-html extras."""
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return (
        f'<div><p>{title}</p>'
        f'<img src="data:image/png;base64,{encoded}" '
        'style="max-width:100%; border:1px solid #ddd;" />'
        "</div>"
    )


def write_allure_environment(extra: Optional[Dict[str, Any]] = None) -> None:
    """Write Allure environment info in both XML (UTF-8) and properties (Unicode-escaped) format for 100% clean rendering."""
    ensure_artifact_dirs()
    data: Dict[str, Any] = {
        "项目名称": "寨湾大屏 UI 自动化测试",
        "操作系统": f"{platform.system()} {platform.release()}",
        "Python版本": platform.python_version(),
        "工作目录": str(PROJECT_ROOT),
        "运行模式": "无头模式" if os.getenv("HEADLESS", "").lower() == "true" else "有界面模式",
        "调试端口": os.getenv("DEBUG_PORT", "9222"),
        "报告批次": report_run_id(),
    }
    if extra:
        data.update(extra)

    # 1. 写入 Allure 官方推荐的 environment.xml (支持原生 UTF-8 中文)
    env_xml_file = ALLURE_RESULTS_DIR / "environment.xml"
    with env_xml_file.open("w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<environment>\n')
        for key, value in data.items():
            f.write('    <parameter>\n')
            f.write(f'        <key>{key}</key>\n')
            f.write(f'        <value>{value}</value>\n')
            f.write('    </parameter>\n')
        f.write('</environment>\n')

    # 2. 写入 environment.properties (使用 Unicode 转义 \uXXXX 适配 Java Properties 规范)
    env_prop_file = ALLURE_RESULTS_DIR / "environment.properties"
    with env_prop_file.open("w", encoding="ascii") as f:
        for key, value in data.items():
            safe_key = str(key).replace(" ", "_").encode("unicode_escape").decode("ascii")
            safe_val = str(value).encode("unicode_escape").decode("ascii")
            f.write(f"{safe_key}={safe_val}\n")


def write_allure_categories() -> None:
    """Write common Allure defect categories for easier failure triage."""
    ensure_artifact_dirs()
    categories = [
        {
            "name": "断言失败",
            "matchedStatuses": ["failed"],
            "messageRegex": ".*AssertionError.*",
        },
        {
            "name": "页面/元素等待超时",
            "matchedStatuses": ["failed", "broken"],
            "messageRegex": ".*(Timeout|timed out|wait_for).*",
        },
        {
            "name": "客户端启动或 CDP 连接异常",
            "matchedStatuses": ["failed", "broken"],
            "messageRegex": ".*(Electron|CDP|WebSocket|launch|connect).*",
        },
        {
            "name": "页面资源或接口 404",
            "matchedStatuses": ["failed", "broken"],
            "messageRegex": ".*(404|Not Found|net::ERR_ABORTED).*",
        },
        {
            "name": "业务功能未就绪或测试数据不足",
            "matchedStatuses": ["skipped", "failed", "broken"],
            "messageRegex": ".*(No games available|not found|未找到|无可用|余额|时长).*",
        },
    ]
    categories_file = ALLURE_RESULTS_DIR / "categories.json"
    categories_file.write_text(json.dumps(categories, ensure_ascii=False, indent=2), encoding="utf-8")


def attach_to_allure(body: Any, name: str, attachment_type: Optional[Any] = None) -> bool:
    """
    Attach data to Allure if allure-pytest is installed and active.

    Returns True when the attachment call succeeds; otherwise False so callers
    can safely run without Allure installed.
    """
    try:
        import allure  # type: ignore

        if attachment_type is None:
            allure.attach(str(body), name=name)
        else:
            allure.attach(body, name=name, attachment_type=attachment_type)
        return True
    except Exception:
        return False


def attach_file_to_allure(path: Path, name: Optional[str] = None, attachment_type: Optional[Any] = None) -> bool:
    """Attach a file to Allure if possible."""
    try:
        import allure  # type: ignore

        allure.attach.file(str(path), name=name or path.name, attachment_type=attachment_type)
        return True
    except Exception:
        return False
