"""
==============================================================================
utils/bug_updater.py —— 全局与单次运行缺陷多端统一同步核心引擎
==============================================================================

职责：
1. 统一维护缺陷生命周期状态、责任人、严重度、排查说明、禅道单号的写回逻辑；
2. 一处修改，多端同步：
   - 全局知识库：artifacts/bugs/global_bugs*.json
   - 单次测试运行目录：reports/runs/<app>/<run_id>/bugs/<bug_id>.json
   - SQLite / MySQL 平台持久化数据库：BugRecord
3. 杜绝在各个服务与脚本中重复复制代码，提供唯一的 Single Source of Truth。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.paths import GLOBAL_BUGS_DIR, get_all_run_folders
from utils.bug_enricher import normalize_severity

logger = logging.getLogger("bug_updater")


def update_bug_record(data: Dict[str, Any]) -> Dict[str, Any]:
    """统一更新缺陷属性，同步文件 JSON 与数据库记录

    :param data: 包含 bug_id, status, severity, assignee, ui_path, analysis_notes, zentao_id 的字典
    :return: 包含 success, bug_id, updated_targets 或 error 的结果字典
    """
    bug_id = data.get("bug_id")
    if not bug_id:
        return {"success": False, "error": "缺少必要的 bug_id 参数"}

    new_status = data.get("status")
    new_severity = normalize_severity(data.get("severity")) if "severity" in data else None
    new_assignee = data.get("assignee")
    new_ui_path = data.get("ui_path")
    new_analysis = data.get("analysis_notes")
    new_zentao_id = data.get("zentao_id")

    success = False
    updated_targets: List[str] = []

    def _apply_updates(target_dict: dict):
        if new_status:
            target_dict["status"] = new_status
        if new_severity is not None:
            target_dict["severity"] = new_severity
        if new_assignee is not None:
            target_dict["assignee"] = new_assignee
        if new_ui_path is not None:
            target_dict["ui_path"] = new_ui_path
        if new_analysis is not None:
            target_dict["analysis_notes"] = new_analysis
        if new_zentao_id is not None:
            z_val = str(new_zentao_id).strip()
            target_dict["zentao_id"] = z_val
            # 若填入了禅道单号且状态为空或激活，自动流转为'已提单'
            if z_val and not new_status and target_dict.get("status") in ("激活", "待处理", "", None, "Open"):
                target_dict["status"] = "已提单"

    # 1. 更新全局缺陷知识库 (artifacts/bugs/global_bugs*.json)
    if GLOBAL_BUGS_DIR.exists():
        for bug_file in GLOBAL_BUGS_DIR.glob("global_bugs*.json"):
            try:
                with open(bug_file, "r", encoding="utf-8") as f:
                    bugs = json.load(f)
                file_changed = False
                for b in bugs:
                    if b.get("id") == bug_id:
                        _apply_updates(b)
                        success = True
                        file_changed = True
                        updated_targets.append(bug_file.name)
                        break
                if file_changed:
                    with open(bug_file, "w", encoding="utf-8") as f:
                        json.dump(bugs, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"更新全局缺陷库 {bug_file.name} 异常: {e}")

    # 2. 更新对应单次测试运行目录 (reports/runs/<app>/<run_id>/bugs/<bug_id>.json)
    for run_dir in get_all_run_folders():
        run_bug_file = run_dir / "bugs" / f"{bug_id}.json"
        if run_bug_file.exists():
            try:
                with open(run_bug_file, "r", encoding="utf-8") as rf:
                    b_data = json.load(rf)
                _apply_updates(b_data)
                with open(run_bug_file, "w", encoding="utf-8") as rf:
                    json.dump(b_data, rf, ensure_ascii=False, indent=2)
                success = True
                updated_targets.append(f"{run_dir.name}/bugs/{bug_id}.json")
            except Exception as e:
                logger.warning(f"更新运行目录 Bug 文件异常 ({run_bug_file}): {e}")

    # 3. 同步持久化至 SQLite/MySQL 平台数据库
    try:
        from server.database import SessionLocal
        from server.models import BugRecord
        db = SessionLocal()
        b_rec = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
        if b_rec:
            if new_status:
                b_rec.status = new_status
            if new_severity is not None:
                b_rec.severity = str(new_severity)
            if new_assignee:
                b_rec.assignee = new_assignee
            if new_ui_path:
                b_rec.ui_path = new_ui_path
            if new_zentao_id is not None:
                b_rec.zentao_id = str(new_zentao_id).strip()
                if b_rec.zentao_id and not new_status and b_rec.status in ("激活", "待处理", "", None, "Open"):
                    b_rec.status = "已提单"
            if new_analysis:
                b_rec.analysis_notes = new_analysis
            db.commit()
            updated_targets.append("database.BugRecord")
        db.close()
    except Exception as de:
        # 当在无 DB 环境或离线独立执行时静默忽略
        logger.debug(f"同步更新数据库 Bug 记录异常 (非致命): {de}")

    if success or "database.BugRecord" in updated_targets:
        return {"success": True, "bug_id": bug_id, "updated": updated_targets}
    return {"success": False, "bug_id": bug_id, "error": f"未找到编号为 '{bug_id}' 的缺陷记录"}

