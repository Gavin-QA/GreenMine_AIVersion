# -*- coding: utf-8 -*-
"""
server/sync_service.py —— 磁盘自动化产物与 SQLite 数据库多端极速热同步服务

核心职责：
1. 自动感知 reports/runs/ 目录下新增或变更的测试任务，极速增量入库至 TaskRun（已入库历史批次直接毫秒级跳过，杜绝重复解析）；
2. 自动同步 artifacts/bugs/global_bugs_*.json 的最新复现频次、运行批次 run_id、责任人与 AI 诊断报告至 BugRecord；
3. 支持轻量化文件时间戳防抖热同步（Hot Sync），用户通宵夜跑后无需重启服务，刷新页面或点击同步即可秒级呈现最新结果。
"""

import os
import json
import time
import logging
import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from .models import TaskRun, BugRecord
from utils.paths import PROJECT_ROOT, GLOBAL_BUGS_DIR, RUNS_DIR, get_all_run_folders

logger = logging.getLogger("server.sync_service")

_sync_lock = Lock()
_last_sync_timestamp = 0.0
_cached_mtimes: Dict[str, float] = {}


def get_filesystem_fingerprint() -> Dict[str, float]:
    """获取关键数据目录与文件的最新修改时间指纹"""
    fingerprints = {}
    # 1. 全局缺陷库文件
    if GLOBAL_BUGS_DIR.exists():
        for bf in GLOBAL_BUGS_DIR.glob("global_bugs*.json"):
            try:
                fingerprints[str(bf.resolve())] = bf.stat().st_mtime
            except Exception:
                pass

    # 2. 运行报告根目录及最新运行目录
    if RUNS_DIR.exists():
        try:
            fingerprints[str(RUNS_DIR.resolve())] = RUNS_DIR.stat().st_mtime
            # 仅抽样探测最近 3 个 run 目录的 mtime
            sub_folders = sorted(get_all_run_folders(), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
            for sf in sub_folders:
                fingerprints[str(sf.resolve())] = sf.stat().st_mtime
        except Exception:
            pass

    return fingerprints


def sync_all_task_runs(db: Session) -> int:
    """全量/增量同步测试运行目录到 TaskRun 表 (极速索引跳过模式)"""
    from utils.report_generator import ReportGenerator

    synced_count = 0
    run_folders = get_all_run_folders()
    existing_tasks = {t.id: t for t in db.query(TaskRun).all()}

    for f in run_folders:
        try:
            run_id = f.name
            task_id = f"task_{run_id}"
            existing = existing_tasks.get(task_id)

            # ⚡ 核心极速优化：如果历史任务已入库且已有执行步数，直接毫秒级跳过，绝不重复解析磁盘大报告！
            if existing and (existing.total_steps or 0) > 0 and existing.duration and existing.duration != "未知":
                continue

            try:
                rel_p = f.relative_to(RUNS_DIR).as_posix()
            except Exception:
                rel_p = f.name

            generator = ReportGenerator(f)
            data = generator.parse_run_data()
            app_key = rel_p.split("/")[0] if "/" in rel_p else "zhaiwan"
            mode_val = "smoke" if run_id.startswith("smoke_") else ("case" if run_id.startswith("yaml_") else "explore")
            kpi = data.get("kpi", {})

            start_dt = None
            if data.get("start_time"):
                try:
                    start_dt = datetime.datetime.strptime(data["start_time"].strip(), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            if not start_dt:
                start_dt = datetime.datetime.fromtimestamp(f.stat().st_mtime)

            if not existing:
                t_rec = TaskRun(
                    id=task_id,
                    name=f"巡检执行报告 · {run_id}",
                    app_name=app_key,
                    mode=mode_val,
                    status="completed",
                    macro_objective=data.get("macro_objective") or "常规自动化巡检与探索",
                    run_dir=rel_p,
                    report_url=f"reports/runs/{rel_p}/report.html",
                    exit_code=0,
                    start_time=start_dt,
                    duration=data.get("duration") or "未知",
                    total_steps=kpi.get("total_steps", 0),
                    planner_phases=kpi.get("planner_phases", 0),
                    coverage_rate=float(kpi.get("page_coverage_rate") or 0.0),
                    bugs_count=kpi.get("bugs_count", 0),
                    apis_count=kpi.get("apis_count", 0),
                    yaml_steps_count=kpi.get("yaml_steps_count", 0)
                )
                db.add(t_rec)
                existing_tasks[task_id] = t_rec
                synced_count += 1
            else:
                # 若任务已有但关键统计数据发生变动（如夜跑完成产生了最终 kpi），进行增量刷新
                new_bugs = kpi.get("bugs_count", 0)
                new_steps = kpi.get("total_steps", 0)
                new_duration = data.get("duration")
                if new_bugs != existing.bugs_count or new_steps != existing.total_steps:
                    existing.bugs_count = new_bugs
                    existing.total_steps = new_steps
                    if new_duration:
                        existing.duration = new_duration
                    synced_count += 1

        except Exception as fe:
            logger.debug(f"同步运行目录 {f.name} 跳过: {fe}")

    db.commit()
    return synced_count


def sync_all_bugs(db: Session) -> int:
    """全量/增量同步 global_bugs_*.json 到 BugRecord 表 (内存批量匹配)"""
    synced_count = 0
    if not GLOBAL_BUGS_DIR.exists():
        return 0

    existing_tasks = {t.id for t in db.query(TaskRun.id).all()}
    existing_bugs = {b.id: b for b in db.query(BugRecord).all()}

    for bug_file in GLOBAL_BUGS_DIR.glob("global_bugs*.json"):
        try:
            with open(bug_file, "r", encoding="utf-8") as bf:
                raw_bugs = json.load(bf)
        except Exception as e:
            logger.debug(f"读取全局缺陷文件 {bug_file.name} 失败: {e}")
            continue

        for rb in raw_bugs:
            b_id = rb.get("id")
            if not b_id:
                continue

            raw_run_id = rb.get("run_id") or ""
            target_task_id = f"task_{raw_run_id}" if raw_run_id else None
            assigned_task_id = target_task_id if target_task_id in existing_tasks else None

            # 解析日期
            last_seen_dt = None
            raw_last_seen = rb.get("last_seen") or rb.get("date")
            if raw_last_seen:
                try:
                    last_seen_dt = datetime.datetime.strptime(str(raw_last_seen).strip()[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    try:
                        last_seen_dt = datetime.datetime.strptime(str(raw_last_seen).strip()[:10], "%Y-%m-%d")
                    except Exception:
                        pass
            if not last_seen_dt:
                last_seen_dt = datetime.datetime.utcnow()

            first_seen_dt = None
            raw_first_seen = rb.get("date") or rb.get("first_seen")
            if raw_first_seen:
                try:
                    first_seen_dt = datetime.datetime.strptime(str(raw_first_seen).strip()[:10], "%Y-%m-%d")
                except Exception:
                    pass
            if not first_seen_dt:
                first_seen_dt = last_seen_dt

            occurrences_val = int(rb.get("occurrences") or 1)
            actual_text = rb.get("details", {}).get("actual") if isinstance(rb.get("details"), dict) else rb.get("actual")
            screenshot_val = rb.get("crash_screenshot") or rb.get("screenshot")

            exist = existing_bugs.get(b_id)
            if not exist:
                b_rec = BugRecord(
                    id=b_id,
                    task_id=assigned_task_id,
                    run_id=raw_run_id,
                    title=rb.get("title", ""),
                    severity=rb.get("severity", "Medium"),
                    status=rb.get("status", "激活"),
                    assignee=rb.get("assignee", "陈贻雄"),
                    zentao_id=str(rb.get("zentao_id")) if rb.get("zentao_id") else None,
                    ui_path=rb.get("ui_path"),
                    target_element=rb.get("target_element"),
                    actual_error=actual_text,
                    analysis_notes=rb.get("analysis_notes"),
                    remark=rb.get("remark"),
                    screenshot_path=screenshot_val,
                    occurrences=occurrences_val,
                    first_seen=first_seen_dt,
                    last_seen=last_seen_dt
                )
                db.add(b_rec)
                existing_bugs[b_id] = b_rec
                synced_count += 1
            else:
                changed = False
                if occurrences_val > (exist.occurrences or 0):
                    exist.occurrences = occurrences_val
                    exist.last_seen = last_seen_dt
                    changed = True

                if raw_run_id and exist.run_id != raw_run_id:
                    exist.run_id = raw_run_id
                    if assigned_task_id:
                        exist.task_id = assigned_task_id
                    changed = True

                if rb.get("status") and exist.status != rb.get("status"):
                    exist.status = rb.get("status")
                    changed = True

                if rb.get("assignee") and exist.assignee != rb.get("assignee"):
                    exist.assignee = rb.get("assignee")
                    changed = True

                if rb.get("analysis_notes") and (not exist.analysis_notes or len(rb.get("analysis_notes")) > len(exist.analysis_notes or "")):
                    exist.analysis_notes = rb.get("analysis_notes")
                    changed = True

                if rb.get("remark") and not exist.remark:
                    exist.remark = rb.get("remark")
                    changed = True

                if rb.get("zentao_id") and not exist.zentao_id:
                    exist.zentao_id = str(rb.get("zentao_id"))
                    changed = True

                if changed:
                    synced_count += 1

    db.commit()
    return synced_count


def perform_hot_sync(db: Session, force: bool = False, min_interval_sec: float = 15.0) -> Dict[str, Any]:
    """
    轻量化热感知同步入口：
    仅在文件实际变动或 force=True 且满足最小防抖间隔时执行增量扫描，零无用开销。
    """
    global _last_sync_timestamp, _cached_mtimes

    now = time.time()
    if not force and (now - _last_sync_timestamp) < min_interval_sec:
        return {"synced": False, "reason": "throttled", "elapsed": round(now - _last_sync_timestamp, 2)}

    with _sync_lock:
        latest_fingerprints = get_filesystem_fingerprint()
        
        has_changes = False
        if force or not _cached_mtimes:
            has_changes = True
        else:
            for path_k, mtime_v in latest_fingerprints.items():
                if path_k not in _cached_mtimes or mtime_v > _cached_mtimes[path_k]:
                    has_changes = True
                    break

        if not has_changes:
            _last_sync_timestamp = now
            return {"synced": False, "reason": "up_to_date"}

        t0 = time.time()
        new_tasks = sync_all_task_runs(db)
        new_bugs = sync_all_bugs(db)

        _cached_mtimes = latest_fingerprints
        _last_sync_timestamp = now
        elapsed = round(time.time() - t0, 3)

        logger.info(f"✨ [Hot Sync] 增量同步完成 (耗时 {elapsed}s)！更新/新增任务: {new_tasks} 项，更新/新增缺陷: {new_bugs} 条。")
        return {
            "synced": True,
            "new_tasks": new_tasks,
            "new_bugs": new_bugs,
            "elapsed": elapsed,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
