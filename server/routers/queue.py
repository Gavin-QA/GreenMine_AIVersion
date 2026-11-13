"""
任务执行调度队列与预约计划 (常驻计划与串行调度器)
"""

import datetime
import json
import logging
import re
import uuid
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Path as FastPath
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TaskRun, TaskQueueItem, PresetTaskRecord, SchedulePlan
from ..task_manager import task_manager
from ..schedule_service import calculate_next_run_time, spawn_task_from_plan
from .presets import DEFAULT_PRESET_TASKS
from ..schemas import (
    QueueItemResponse,
    QueueItemCreate,
    SchedulePlanCreate,
    SchedulePlanUpdate,
    SchedulePlanResponse,
    QueueDeleteResponse,
)

logger = logging.getLogger("server.queue")
router = APIRouter()


@router.get(
    "/api/tasks/queue",
    tags=["2. 巡检任务生命周期调度"],
    summary="查询当前任务调度计划与串行执行看板",
    description="获取所有常驻调度计划规则及正在排队/执行中的调度队列项。",
)
def get_task_queue(
    status: Optional[str] = Query(default=None, description="状态筛选: active/paused/expired/running/completed"),
    limit: int = Query(default=50, ge=1, le=100, description="单页最大拉取记录条数"),
    db: Session = Depends(get_db),
):
    """
    获取调度执行看板：
    以常驻调度计划 (SchedulePlan) 为核心，结合底层 RPA 队列实时执行状态呈现。
    """
    limit_val = limit.default if hasattr(limit, "default") else (int(limit) if isinstance(limit, (int, str)) else 50)
    status_val = status.default if hasattr(status, "default") else status
    plans = db.query(SchedulePlan).order_by(SchedulePlan.priority.asc(), SchedulePlan.created_at.desc()).limit(limit_val).all()
    result = []

    for p in plans:
        # 获取关联预设信息
        preset = p.preset or db.query(PresetTaskRecord).filter(PresetTaskRecord.id == p.preset_id).first()
        preset_title = preset.title if preset else "自定义巡检模板"
        preset_mode = getattr(preset, "mode", "explore") if preset else "explore"
        max_steps = getattr(preset, "max_steps", 200) if preset else 200
        max_times = getattr(preset, "max_times", 60) if preset else 60

        # 判断当前计划是否正在实际执行中
        plan_status = p.status or "active"
        is_running_now = False
        if p.last_task_id:
            if task_manager.is_running(p.last_task_id):
                is_running_now = True
                plan_status = "running"

        if not is_running_now and p.is_active == 0:
            plan_status = "paused" if p.status != "expired" else "expired"

        if status_val and plan_status != status_val:
            continue

        scheduled_at_str = p.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if p.next_run_time else None

        item_dict = {
            "id": p.id,
            "task_id": p.last_task_id or p.id,
            "task_name": p.name,
            "name": p.name,
            "app_name": p.app_name,
            "preset_id": p.preset_id,
            "preset_title": preset_title,
            "mode": preset_mode,
            "max_steps": max_steps,
            "max_times": max_times,
            "priority": p.priority,
            "status": plan_status,
            "scheduled_at": scheduled_at_str,
            "next_run_time": scheduled_at_str,
            "start_date": p.start_date,
            "end_date": p.end_date,
            "start_time": p.start_time,
            "end_time": p.end_time,
            "cron_mode": p.cron_mode or "daily",
            "cron_spec": p.cron_spec or "1",
            "conflict_policy": p.conflict_policy or "wait",
            "auto_retry": p.auto_retry or 0,
            "ignore_env_check": p.ignore_env_check or 0,
            "is_active": p.is_active,
            "run_count": p.run_count or 0,
            "last_run_time": p.last_run_time.strftime("%Y-%m-%d %H:%M:%S") if p.last_run_time else None,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else None,
        }
        result.append(item_dict)

    # 兼容处理：若存在手动加入的临时 TaskQueueItem (非来自 SchedulePlan)，也一并呈现
    plan_last_task_ids = {p.last_task_id for p in plans if p.last_task_id}
    q_items = db.query(TaskQueueItem).filter(TaskQueueItem.status.in_(["pending", "running"])).all()
    for qi in q_items:
        if qi.task_id in plan_last_task_ids:
            continue # 已由对应常驻计划呈现
        task = qi.task or db.query(TaskRun).filter(TaskRun.id == qi.task_id).first()
        if not task:
            continue
        result.append({
            "id": qi.id,
            "task_id": qi.task_id,
            "task_name": task.name,
            "name": task.name,
            "app_name": task.app_name,
            "mode": task.mode,
            "max_steps": task.max_steps,
            "max_times": task.max_times,
            "priority": qi.priority,
            "status": qi.status,
            "scheduled_at": qi.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if qi.scheduled_at else None,
            "next_run_time": qi.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if qi.scheduled_at else None,
            "cron_mode": getattr(qi, "cron_mode", "once") or "once",
            "cron_spec": getattr(qi, "cron_spec", "") or "",
            "is_active": getattr(qi, "is_active", 1),
            "created_at": qi.created_at.strftime("%Y-%m-%d %H:%M:%S") if qi.created_at else None,
        })

    return result


@router.post(
    "/api/tasks/queue/schedule",
    tags=["2. 巡检任务生命周期调度"],
    summary="新建调度执行计划 (常驻规则，关联巡检任务模板)",
    description="在调度中心新建一条常驻排程计划。支持配置生效日期、触发时刻、巡检周期与冲突策略。",
)
def create_schedule_plan(payload: SchedulePlanCreate, db: Session = Depends(get_db)):
    """创建常驻调度执行计划"""
    # 1. 查找关联预设模板
    preset = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == payload.preset_id).first()
    if not preset:
        preset_dict = next((p for p in DEFAULT_PRESET_TASKS if p["id"] == payload.preset_id), None)
        if not preset_dict:
            raise HTTPException(status_code=404, detail="未找到指定的关联巡检任务预设")
        preset_title = preset_dict.get("title", "巡检任务")
    else:
        preset_title = preset.title

    now = datetime.datetime.now()
    raw_plan_name = (payload.name and payload.name.strip()) or f"【排程】{preset_title}"
    plan_name = re.sub(r"【.*?矿山\s*\(.*?\)\s*】", "", raw_plan_name).strip()

    # 2. 计算首次执行预约时间
    start_time_val = (payload.start_time or payload.time_of_day or "18:35:00").strip()
    next_dt = calculate_next_run_time(
        cron_mode=payload.cron_mode or "daily",
        cron_spec=payload.cron_spec or "1",
        start_time_str=start_time_val,
        start_date_str=payload.start_date,
        end_date_str=payload.end_date,
        after_time=now,
    )

    plan_id = f"plan_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    plan = SchedulePlan(
        id=plan_id,
        name=plan_name,
        app_name=payload.app_name,
        preset_id=payload.preset_id,
        priority=payload.priority,
        start_date=(payload.start_date or "").strip(),
        end_date=(payload.end_date or "").strip(),
        start_time=start_time_val,
        end_time=(payload.end_time or "23:59:59").strip(),
        cron_mode=payload.cron_mode or "daily",
        cron_spec=payload.cron_spec or "1",
        conflict_policy=payload.conflict_policy or "wait",
        auto_retry=payload.auto_retry or 0,
        ignore_env_check=payload.ignore_env_check or 0,
        is_active=payload.is_active if payload.is_active is not None else 1,
        status="active" if (payload.is_active if payload.is_active is not None else 1) else "paused",
        next_run_time=next_dt,
        run_count=0,
        created_at=now,
        updated_at=now,
    )

    db.add(plan)
    db.commit()
    db.refresh(plan)

    logger.info(f"📅 已成功创建调度计划 [{plan.name}] (ID: {plan.id})，首次触发预约于: {next_dt.strftime('%Y-%m-%d %H:%M:%S') if next_dt else '未预约'}")

    return {
        "id": plan.id,
        "name": plan.name,
        "app_name": plan.app_name,
        "preset_id": plan.preset_id,
        "priority": plan.priority,
        "cron_mode": plan.cron_mode,
        "cron_spec": plan.cron_spec,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "start_time": plan.start_time,
        "end_time": plan.end_time,
        "is_active": plan.is_active,
        "status": plan.status,
        "scheduled_at": plan.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if plan.next_run_time else None,
        "next_run_time": plan.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if plan.next_run_time else None,
    }


@router.put(
    "/api/tasks/queue/schedule/{plan_id}",
    tags=["2. 巡检任务生命周期调度"],
    summary="编辑已有的调度计划",
)
def update_schedule_plan(
    plan_id: str = FastPath(..., description="待修改的调度计划 ID"),
    payload: SchedulePlanUpdate = None,
    db: Session = Depends(get_db),
):
    """更新常驻调度计划并重新推演下次执行时间"""
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="未找到指定的调度计划")

    if payload.name is not None: plan.name = payload.name.strip()
    if payload.priority is not None: plan.priority = payload.priority
    if payload.start_date is not None: plan.start_date = payload.start_date.strip()
    if payload.end_date is not None: plan.end_date = payload.end_date.strip()
    if payload.start_time is not None: plan.start_time = payload.start_time.strip()
    if payload.end_time is not None: plan.end_time = payload.end_time.strip()
    if payload.cron_mode is not None: plan.cron_mode = payload.cron_mode.strip()
    if payload.cron_spec is not None: plan.cron_spec = payload.cron_spec.strip()
    if payload.conflict_policy is not None: plan.conflict_policy = payload.conflict_policy
    if payload.auto_retry is not None: plan.auto_retry = payload.auto_retry
    if payload.ignore_env_check is not None: plan.ignore_env_check = payload.ignore_env_check
    if payload.is_active is not None:
        plan.is_active = payload.is_active
        plan.status = "active" if payload.is_active else "paused"

    now = datetime.datetime.now()
    plan.updated_at = now

    # 重新推演下次执行时间
    if plan.is_active:
        plan.next_run_time = calculate_next_run_time(
            cron_mode=plan.cron_mode,
            cron_spec=plan.cron_spec,
            start_time_str=plan.start_time,
            start_date_str=plan.start_date,
            end_date_str=plan.end_date,
            after_time=now,
        )
    else:
        plan.next_run_time = None

    db.commit()
    db.refresh(plan)
    return {"code": 200, "message": "调度计划更新成功", "next_run_time": plan.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if plan.next_run_time else None}


@router.post(
    "/api/tasks/queue/schedule/{plan_id}/toggle",
    tags=["2. 巡检任务生命周期调度"],
    summary="启用或暂停指定调度计划",
)
def toggle_schedule_plan(
    plan_id: str = FastPath(..., description="调度计划 ID"),
    db: Session = Depends(get_db),
):
    """一键开关调度计划"""
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="未找到指定的调度计划")

    now = datetime.datetime.now()
    plan.is_active = 0 if plan.is_active else 1
    plan.updated_at = now

    if plan.is_active:
        plan.status = "active"
        plan.next_run_time = calculate_next_run_time(
            cron_mode=plan.cron_mode,
            cron_spec=plan.cron_spec,
            start_time_str=plan.start_time,
            start_date_str=plan.start_date,
            end_date_str=plan.end_date,
            after_time=now,
        )
        msg = f"计划已启用，下次触发时间: {plan.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if plan.next_run_time else '未排期'}"
    else:
        plan.status = "paused"
        plan.next_run_time = None
        msg = "计划已停用"

    db.commit()
    return {"code": 200, "message": msg, "is_active": plan.is_active, "status": plan.status, "next_run_time": plan.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if plan.next_run_time else None}


@router.post(
    "/api/tasks/queue/schedule/{plan_id}/run_now",
    tags=["2. 巡检任务生命周期调度"],
    summary="立即手动触发执行一次该调度计划",
)
def run_schedule_plan_now(
    plan_id: str = FastPath(..., description="调度计划 ID"),
    db: Session = Depends(get_db),
):
    """手动立即下发执行一次"""
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="未找到指定的调度计划")

    new_task = spawn_task_from_plan(plan, db)
    if not new_task:
        raise HTTPException(status_code=500, detail="下发任务执行失败")

    return {
        "code": 200,
        "message": f"计划【{plan.name}】已立即下发任务 [{new_task.id}] 并送入执行队列！",
        "task_id": new_task.id,
    }


@router.delete(
    "/api/tasks/queue/{item_id}",
    response_model=QueueDeleteResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="删除调度计划或从队列中移出任务",
)
def delete_queue_or_plan(
    item_id: str = FastPath(..., description="调度计划 ID (plan_xxx) 或 队列记录 ID (queue_xxx)"),
    db: Session = Depends(get_db),
):
    """
    通用删除接口：
    若传入 plan_ 开头，则删除对应的常驻调度计划；
    若传入 queue_ 开头，则从执行队列中移出该项并联动终止。
    """
    # 1. 优先尝试作为 SchedulePlan 删除
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == item_id).first()
    if plan:
        plan_name = plan.name
        db.delete(plan)
        db.commit()
        logger.info(f"🗑️ 已成功删除调度计划: {plan_name} ({item_id})")
        return {"code": 200, "message": f"调度计划【{plan_name}】已成功删除", "queue_id": item_id}

    # 2. 尝试作为 TaskQueueItem 删除
    q_item = db.query(TaskQueueItem).filter(TaskQueueItem.id == item_id).first()
    if q_item:
        if q_item.status == "running":
            task_manager.stop_task(q_item.task_id)

        task = db.query(TaskRun).filter(TaskRun.id == q_item.task_id).first()
        if task and not task.run_dir and not task_manager.is_running(task.id):
            db.delete(task)

        db.delete(q_item)
        db.commit()
        return {"code": 200, "message": "已从调度队列中成功移出", "queue_id": item_id}

    raise HTTPException(status_code=404, detail="未找到指定的调度计划或排队记录")
