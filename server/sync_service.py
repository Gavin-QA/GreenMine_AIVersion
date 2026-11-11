# -*- coding: utf-8 -*-
"""
server/sync_service.py —— 磁盘自动化产物与 SQLite 数据库多端极速热同步服务

核心职责：
1. 自动感知 reports/runs/ 目录下新增或变更的测试任务，极速增量入库至 TaskRun；
2. 核心防重与双引擎归一：智能关联平台自定义发起的任务与底层运行目录，杜绝影子重复记录；
3. 自动同步 artifacts/bugs/global_bugs_*.json 的最新复现频次、运行批次 run_id、责任人与 AI 诊断报告至 BugRecord；
4. 支持轻量化文件时间戳防抖热同步（Hot Sync），用户通宵夜跑后无需重启服务，刷新页面或点击同步即可秒级呈现最新结果。
"""

import os
import re
import json
import time
import logging
import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

from .models import TaskRun, BugRecord, StepRecord, PerformanceMetric
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


def cleanup_duplicate_task_runs(db: Session) -> int:
    """自动清理并合并指向同一物理目录的重复任务记录 (保全用户自定义业务名称与完整指标)"""
    from collections import defaultdict

    all_tasks = db.query(TaskRun).all()
    by_folder = defaultdict(list)

    for t in all_tasks:
        folder = None
        if t.run_dir:
            folder = Path(t.run_dir.replace("\\", "/").strip("/")).name
        elif t.report_url:
            for seg in t.report_url.replace("\\", "/").split("/"):
                if seg.startswith(("explore_", "smoke_", "yaml_")):
                    folder = seg
                    break
        if folder:
            by_folder[folder].append(t)

    cleaned_count = 0
    for folder, group in by_folder.items():
        if len(group) <= 1:
            continue

        # 优先保留平台派发的业务命名任务
        platform_tasks = [t for t in group if not t.id.startswith(("task_explore_", "task_smoke_", "task_yaml_"))]
        generic_tasks = [t for t in group if t.id.startswith(("task_explore_", "task_smoke_", "task_yaml_"))]

        if platform_tasks:
            primary = platform_tasks[0]
            shadows = [t for t in group if t.id != primary.id]
        else:
            primary = sorted(group, key=lambda x: (len(x.name), x.id), reverse=True)[0]
            shadows = [t for t in group if t.id != primary.id]

        for s in shadows:
            # 汇聚指标
            if (s.total_steps or 0) > (primary.total_steps or 0):
                primary.total_steps = s.total_steps
            if s.duration and (not primary.duration or primary.duration == "未知"):
                primary.duration = s.duration
            if s.report_url and not primary.report_url:
                primary.report_url = s.report_url
            if s.run_dir and not primary.run_dir:
                primary.run_dir = s.run_dir
            if (s.coverage_rate or 0) > (primary.coverage_rate or 0):
                primary.coverage_rate = s.coverage_rate
            if (s.bugs_count or 0) > (primary.bugs_count or 0):
                primary.bugs_count = s.bugs_count

            # 转移关联的缺陷与步骤记录
            bugs = db.query(BugRecord).filter(BugRecord.task_id == s.id).all()
            for b in bugs:
                b.task_id = primary.id
            steps = db.query(StepRecord).filter(StepRecord.task_id == s.id).all()
            for st in steps:
                st.task_id = primary.id
            metrics = db.query(PerformanceMetric).filter(PerformanceMetric.task_id == s.id).all()
            for m in metrics:
                m.task_id = primary.id

            db.delete(s)
            cleaned_count += 1

    if cleaned_count > 0:
        db.commit()
        logger.info(f"🛡️ [TaskClean] 已自动合并清理 {cleaned_count} 条物理运行重复任务记录")
    return cleaned_count


def sync_all_task_runs(db: Session) -> int:
    """全量/增量同步测试运行目录到 TaskRun 表 (多维索引与防重归一模式)"""
    from utils.report_generator import ReportGenerator

    # 1. 预先执行一次重复检测与清理
    cleanup_duplicate_task_runs(db)

    synced_count = 0
    run_folders = get_all_run_folders()
    all_tasks = db.query(TaskRun).all()

    # 建立多维索引：同时以 task_id、run_dir、run_id 索引已有任务
    existing_by_id: Dict[str, TaskRun] = {t.id: t for t in all_tasks}
    existing_by_run: Dict[str, TaskRun] = {}

    for t in all_tasks:
        if t.run_dir:
            clean_rd = t.run_dir.replace("\\", "/").strip("/")
            existing_by_run[clean_rd] = t
            existing_by_run[Path(clean_rd).name] = t
        if t.report_url:
            clean_ru = t.report_url.replace("\\", "/").strip("/")
            for seg in clean_ru.split("/"):
                if seg.startswith(("explore_", "smoke_", "yaml_")):
                    existing_by_run[seg] = t

    for f in run_folders:
        try:
            run_id = f.name
            task_id = f"task_{run_id}"

            try:
                rel_p = f.relative_to(RUNS_DIR).as_posix()
            except Exception:
                rel_p = f.name

            # 核心防重：优先命中平台派发的业务任务，严禁新建影子记录
            existing = existing_by_run.get(rel_p) or existing_by_run.get(run_id) or existing_by_id.get(task_id)

            # ⚡ 核心极速优化：如果历史任务已入库且已有执行步数，直接毫秒级跳过，绝不重复解析磁盘大报告！
            if existing and (existing.total_steps or 0) > 0 and existing.duration and existing.duration != "未知":
                if not existing.run_dir:
                    existing.run_dir = rel_p
                continue

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
                    report_url=f"/reports/runs/{rel_p}/report.html",
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
                existing_by_id[task_id] = t_rec
                existing_by_run[rel_p] = t_rec
                existing_by_run[run_id] = t_rec
                synced_count += 1
            else:
                # 仅增量刷新指标，严格保留用户原本设置的有业务意义的名称
                changed = False
                if not existing.run_dir:
                    existing.run_dir = rel_p
                    changed = True
                if not existing.report_url:
                    existing.report_url = f"/reports/runs/{rel_p}/report.html"
                    changed = True
                new_bugs = kpi.get("bugs_count", 0)
                new_steps = kpi.get("total_steps", 0)
                new_duration = data.get("duration")
                if new_bugs != existing.bugs_count or new_steps != existing.total_steps:
                    existing.bugs_count = new_bugs
                    existing.total_steps = new_steps
                    if new_duration:
                        existing.duration = new_duration
                    changed = True
                if existing.status != "completed":
                    existing.status = "completed"
                    changed = True
                if changed:
                    synced_count += 1

        except Exception as fe:
            logger.debug(f"同步运行目录 {f.name} 跳过: {fe}")

    db.commit()
    return synced_count


def sync_all_bugs(db: Session) -> int:
    """全量/增量同步 global_bugs_*.json 到 BugRecord 表 (智能归属映射)"""
    synced_count = 0
    if not GLOBAL_BUGS_DIR.exists():
        return 0

    all_tasks = db.query(TaskRun).all()
    # 建立 task_id 智能反查索引 (支持由 run_id 或 run_dir 命中平台真实发起的任务 ID)
    task_id_lookup: Dict[str, str] = {}
    for t in all_tasks:
        task_id_lookup[t.id] = t.id
        if t.run_dir:
            clean_rd = t.run_dir.replace("\\", "/").strip("/")
            task_id_lookup[clean_rd] = t.id
            task_id_lookup[Path(clean_rd).name] = t.id
        if t.report_url:
            for seg in t.report_url.replace("\\", "/").split("/"):
                if seg.startswith(("explore_", "smoke_", "yaml_")):
                    task_id_lookup[seg] = t.id

    existing_bugs = {b.id: b for b in db.query(BugRecord).all()}

    for bug_file in GLOBAL_BUGS_DIR.glob("global_bugs*.json"):
        # 从文件名提取归属矿山应用代号 (如 global_bugs_tianrui.json -> tianrui)
        m = re.search(r"global_bugs_([a-zA-Z0-9_\-]+)\.json", bug_file.name)
        file_app_name = m.group(1) if m else "zhaiwan"

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

            bug_app = rb.get("app_name") or rb.get("app") or file_app_name
            raw_run_id = rb.get("run_id") or ""
            # 智能映射缺陷归属的任务 ID
            assigned_task_id = None
            if raw_run_id:
                assigned_task_id = task_id_lookup.get(raw_run_id) or task_id_lookup.get(f"task_{raw_run_id}")
            if not assigned_task_id and rb.get("task_id"):
                assigned_task_id = task_id_lookup.get(rb.get("task_id"))

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
                last_seen_dt = datetime.datetime.now()

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
                    app_name=bug_app,
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
                if exist.app_name != bug_app:
                    exist.app_name = bug_app
                    changed = True

                if occurrences_val > (exist.occurrences or 0):
                    exist.occurrences = occurrences_val
                    exist.last_seen = last_seen_dt
                    changed = True

                if raw_run_id and exist.run_id != raw_run_id:
                    exist.run_id = raw_run_id
                    changed = True

                # 自动校准关联任务 ID
                if assigned_task_id and exist.task_id != assigned_task_id:
                    exist.task_id = assigned_task_id
                    changed = True

                if rb.get("title") and exist.title != rb.get("title"):
                    exist.title = rb.get("title")
                    changed = True

                if rb.get("target_element") and exist.target_element != rb.get("target_element"):
                    exist.target_element = rb.get("target_element")
                    changed = True

                if rb.get("status") and exist.status != rb.get("status"):
                    exist.status = rb.get("status")
                    changed = True

                if rb.get("assignee") and exist.assignee != rb.get("assignee"):
                    exist.assignee = rb.get("assignee")
                    changed = True

                if rb.get("analysis_notes") and exist.analysis_notes != rb.get("analysis_notes"):
                    exist.analysis_notes = rb.get("analysis_notes")
                    changed = True

                if rb.get("remark") and exist.remark != rb.get("remark"):
                    exist.remark = rb.get("remark")
                    changed = True

                if rb.get("zentao_id") and exist.zentao_id != str(rb.get("zentao_id")):
                    exist.zentao_id = str(rb.get("zentao_id"))
                    changed = True

                if changed:
                    synced_count += 1

    # 同步反向更新每个 TaskRun 的 bugs_count
    for t in all_tasks:
        b_count = db.query(BugRecord).filter(BugRecord.task_id == t.id).count()
        if b_count != t.bugs_count:
            t.bugs_count = b_count

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
