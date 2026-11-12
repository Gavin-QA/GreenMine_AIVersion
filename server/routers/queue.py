"""
任务执行调度队列与预约计划 (串行调度器)
"""

import datetime
import json
import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Path as FastPath
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TaskRun, TaskQueueItem, PresetTaskRecord
from ..task_manager import task_manager
from .presets import DEFAULT_PRESET_TASKS
from ..schemas import (
    QueueItemResponse,
    QueueItemCreate,
    SchedulePlanCreate,
    QueueDeleteResponse,
)

logger = logging.getLogger("server.queue")
router = APIRouter()

@router.get(
    "/api/tasks/queue",
    response_model=List[QueueItemResponse],
    tags=["2. 巡检任务生命周期调度"],
    summary="查询当前任务串行执行队列看板",
    description="获取所有排队中、执行中或历史已完成的调度队列项，按优先级与排队顺序升序排列。",
)
def get_task_queue(
    status: Optional[str] = Query(default=None, description="状态筛选: pending/running/completed/failed/canceled"),
    limit: int = Query(default=50, ge=1, le=100, description="单页最大拉取队列记录条数"),
    db: Session = Depends(get_db),
):
    from ..models import TaskQueueItem
    q = db.query(TaskQueueItem)
    if status:
        q = q.filter(TaskQueueItem.status == status)
    # pending 优先放前面，再按 priority 与创建时间排序
    items = q.order_by(
        TaskQueueItem.status.desc(), # running/pending 会排在前面
        TaskQueueItem.priority.asc(),
        TaskQueueItem.created_at.asc()
    ).limit(limit).all()

    result = []
    orphaned_items = []
    for item in items:
        if not item.task:
            orphaned_items.append(item)
            continue
        resp_item = {
            "id": item.id,
            "task_id": item.task_id,
            "task_name": item.task.name,
            "app_name": item.task.app_name,
            "mode": item.task.mode,
            "max_steps": item.task.max_steps,
            "max_times": item.task.max_times,
            "priority": item.priority,
            "status": item.status,
            "scheduled_at": item.scheduled_at,
            "created_at": item.created_at,
            "started_at": item.started_at,
            "finished_at": item.finished_at,
            "error_message": item.error_message,
        }
        result.append(resp_item)

    # 自动抹除已失去主任务的孤儿历史排队流水
    if orphaned_items:
        for orphan in orphaned_items:
            db.delete(orphan)
        try:
            db.commit()
        except Exception:
            db.rollback()

    return result


@router.post(
    "/api/tasks/queue/schedule",
    response_model=QueueItemResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="新建调度执行计划 (关联指定应用与预设任务模板)",
    description="在调度执行队列中直接新建排程计划：选择目标应用与关联的预设巡检任务模板，支持定时预约与优先级排程。",
)
def create_schedule_plan(payload: SchedulePlanCreate, db: Session = Depends(get_db)):
    from ..models import TaskQueueItem, PresetTaskRecord, TaskRun
    import uuid

    # 1. 查找关联的预设模板
    preset = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == payload.preset_id).first()
    if preset:
        preset_dict = {
            "title": preset.title,
            "app_name": preset.app_name,
            "mode": preset.mode,
            "macro_objective": preset.macro_objective or "",
            "max_steps": preset.max_steps,
            "max_times": preset.max_times,
            "reset_memory": preset.reset_memory,
            "ignore_errors": preset.ignore_errors,
            "case_path": preset.case_path,
            "tour": getattr(preset, "tour", False),
            "resume_from": getattr(preset, "resume_from", None),
            "reexplore": getattr(preset, "reexplore", None),
            "start_delay": getattr(preset, "start_delay", None),
            "wait_ready": getattr(preset, "wait_ready", None),
            "wait_timeout": getattr(preset, "wait_timeout", 60.0),
            "ignore_env_check": getattr(preset, "ignore_env_check", False),
        }
    else:
        preset_dict = next((p for p in DEFAULT_PRESET_TASKS if p["id"] == payload.preset_id), None)
        if not preset_dict:
            raise HTTPException(status_code=404, detail="未找到指定的关联巡检任务预设")

    # 2. 生成待执行 TaskRun
    now = datetime.datetime.now()
    task_id = f"task_{now.strftime('%Y%m%d_%H%M%S')}"
    plan_name = (payload.name and payload.name.strip()) or f"【排程】{preset_dict.get('title', '巡检任务')}"

    target_app = payload.app_name or preset_dict.get("app_name", "zhaiwan")
    is_smoke = preset_dict.get("mode") == "smoke" or preset_dict.get("tour", False)

    new_task = TaskRun(
        id=task_id,
        name=plan_name,
        app_name=target_app,
        mode=preset_dict.get("mode", "explore"),
        status="pending",
        macro_objective="" if is_smoke else preset_dict.get("macro_objective", ""),
        max_steps=None if is_smoke else preset_dict.get("max_steps", 200),
        max_times=preset_dict.get("max_times", 60),
        reset_memory=preset_dict.get("reset_memory", False),
        ignore_errors=preset_dict.get("ignore_errors", True),
        explore_context=f"docs/explore_rules_{target_app}.md",
        case_path=preset_dict.get("case_path"),
        tour=is_smoke,
        resume_from=preset_dict.get("resume_from"),
        reexplore=preset_dict.get("reexplore"),
        start_delay=preset_dict.get("start_delay"),
        wait_ready=preset_dict.get("wait_ready"),
        wait_timeout=preset_dict.get("wait_timeout", 60.0),
        ignore_env_check=preset_dict.get("ignore_env_check", False),
    )
    db.add(new_task)
    db.flush()

    # 3. 创建 TaskQueueItem 排队记录
    queue_id = f"queue_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    q_item = TaskQueueItem(
        id=queue_id,
        task_id=new_task.id,
        priority=payload.priority,
        status="pending",
        scheduled_at=payload.scheduled_at,
        created_at=now,
    )
    db.add(q_item)
    db.commit()
    db.refresh(q_item)

    return {
        "id": q_item.id,
        "task_id": q_item.task_id,
        "task_name": new_task.name,
        "app_name": new_task.app_name,
        "mode": new_task.mode,
        "max_steps": new_task.max_steps,
        "max_times": new_task.max_times,
        "priority": q_item.priority,
        "status": q_item.status,
        "scheduled_at": q_item.scheduled_at,
        "created_at": q_item.created_at,
        "started_at": q_item.started_at,
        "finished_at": q_item.finished_at,
        "error_message": q_item.error_message,
    }


@router.post(
    "/api/tasks/queue",
    response_model=QueueItemResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="将巡检任务加入串行调度执行队列 (支持预约定时)",
    description="把已有任务加入串行队列，执行器将自动轮流单机独占拉起。若配置 scheduled_at 则在到达设定时间后触发。",
)
def enqueue_task(payload: QueueItemCreate, db: Session = Depends(get_db)):
    from ..models import TaskQueueItem
    task = db.query(TaskRun).filter(TaskRun.id == payload.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="未找到指定的关联任务")

    # 检查是否已经在排队或执行中
    existing = db.query(TaskQueueItem).filter(
        TaskQueueItem.task_id == payload.task_id,
        TaskQueueItem.status.in_(["pending", "running"])
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该任务已在调度队列中，请勿重复加入")

    import uuid
    queue_id = f"queue_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    q_item = TaskQueueItem(
        id=queue_id,
        task_id=payload.task_id,
        priority=payload.priority,
        status="pending",
        scheduled_at=payload.scheduled_at,
        created_at=datetime.datetime.now(),
    )
    db.add(q_item)
    db.commit()
    db.refresh(q_item)

    return {
        "id": q_item.id,
        "task_id": q_item.task_id,
        "task_name": task.name,
        "app_name": task.app_name,
        "mode": task.mode,
        "max_steps": task.max_steps,
        "max_times": task.max_times,
        "priority": q_item.priority,
        "status": q_item.status,
        "scheduled_at": q_item.scheduled_at,
        "created_at": q_item.created_at,
        "started_at": q_item.started_at,
        "finished_at": q_item.finished_at,
        "error_message": q_item.error_message,
    }


@router.delete(
    "/api/tasks/queue/{queue_id}",
    response_model=QueueDeleteResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="从调度队列中取消或移出任务",
    description="从串行调度执行队列中移除指定的任务项；若该任务正在执行中，则联动触发优雅停机。",
)
def remove_from_queue(
    queue_id: str = FastPath(..., description="待取消或移出的调度队列记录唯一标识"),
    db: Session = Depends(get_db)
):
    """
    从串行调度执行队列中取消或移除任务。

    Args:
        queue_id: 队列记录 ID
        db: 数据库会话

    Returns:
        QueueDeleteResponse: 包含状态码与队列操作结果
    """
    from ..models import TaskQueueItem
    q_item = db.query(TaskQueueItem).filter(TaskQueueItem.id == queue_id).first()
    if not q_item:
        raise HTTPException(status_code=404, detail="未找到指定的队列记录")

    if q_item.status == "running":
        # 正在执行的任务联动终止
        task_manager.stop_task(q_item.task_id)
        q_item.status = "canceled"
        q_item.finished_at = datetime.datetime.now()
        db.commit()
        return {"code": 200, "message": "正在执行的队列任务已终止并移出", "queue_id": queue_id}

    # 若该任务尚未物理执行且无磁盘产物，连带清理任务记录，杜绝残留孤儿脏数据
    task = db.query(TaskRun).filter(TaskRun.id == q_item.task_id).first()
    if task and task.status == "pending" and not task.run_dir and not task_manager.is_running(task.id):
        db.delete(task)

    db.delete(q_item)
    db.commit()
    return {"code": 200, "message": "已从调度队列中成功移出", "queue_id": queue_id}


