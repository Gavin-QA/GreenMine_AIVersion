"""
巡检任务生命周期调度与管理 (创建、查询、启动、停止、删除、日志、网络接口、环境基线)
"""

import asyncio
import datetime
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Path as FastPath,
    BackgroundTasks,
)
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TaskRun, BugRecord, PerformanceMetric, TaskQueueItem
from ..schemas import (
    TaskCreate,
    TaskResponse,
    TaskActionResponse,
    TaskDeleteResponse,
    TaskLogsResponse,
    TaskApisResponse,
    TaskEnvInfoResponse,
)
from ..task_manager import task_manager
from ..performance_monitor import performance_monitor
from utils.paths import PROJECT_ROOT, RUNS_DIR, find_run_dir

logger = logging.getLogger("server.tasks")
router = APIRouter()

@router.post(
    "/api/tasks",
    response_model=TaskResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="新建巡检任务",
    description="接收前端选项表单，持久化生成新的巡检任务定义记录并分配唯一 `task_id`，初始状态为 `pending`。",
)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):

    now = datetime.datetime.now()

    task_id = f"task_{now.strftime('%Y%m%d_%H%M%S')}"

    task = TaskRun(
        id=task_id,
        name=payload.name or f"自动化巡检 - {payload.app_name}",
        app_name=payload.app_name,
        mode=payload.mode,
        status="pending",
        macro_objective=payload.macro_objective,
        max_steps=payload.max_steps,
        max_times=payload.max_times,
        reset_memory=payload.reset_memory,
        ignore_errors=payload.ignore_errors,
        explore_context=payload.explore_context,
        case_path=payload.case_path,
        tour=payload.tour,
        resume_from=payload.resume_from,
        reexplore=payload.reexplore,
        start_delay=payload.start_delay,
        wait_ready=payload.wait_ready,
        wait_timeout=payload.wait_timeout,
        ignore_env_check=payload.ignore_env_check,
        trigger_type="manual",
        start_time=now,
    )

    db.add(task)

    db.commit()

    db.refresh(task)

    return task


@router.get(
    "/api/tasks",
    response_model=List[TaskResponse],
    tags=["2. 巡检任务生命周期调度"],
    summary="分页查询巡检任务列表",
    description="支持按状态（`running`、`completed` 等）筛选，返回任务的覆盖率、执行步数与缺陷汇总等 KPI 指标。",
)
def list_tasks(
    status: Optional[str] = Query(
        default=None,
        description="任务状态过滤 (pending/running/completed/stopped/failed)",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="单页最大拉取记录条数"),
    offset: int = Query(default=0, ge=0, description="分页偏移量"),
    sync: bool = Query(
        default=False,
        description="是否在查询前从磁盘执行增量热同步(默认False保障极速响应)",
    ),
    db: Session = Depends(get_db),
):

    if sync:
        from ..sync_service import perform_hot_sync

        perform_hot_sync(db, force=False)

    q = db.query(TaskRun).order_by(TaskRun.start_time.desc())

    if status:
        q = q.filter(TaskRun.status == status)
    else:
        # 核心铁律：历史巡检任务列表仅展示真正已拉起执行或已归档的任务
        # 处于排队中的调度计划只在“执行调度队列看板”中呈现，严禁在未真正执行前占位显示
        q = q.filter(TaskRun.status != "pending")

    return q.offset(offset).limit(limit).all()



@router.get(
    "/api/tasks/{task_id}",
    response_model=TaskResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="获取指定任务详情",
    description="获取指定任务当前的运行进展、子进程 PID、结束时间、产物报告链接以及最终 KPI。",
)
def get_task(
    task_id: str = FastPath(..., description="任务唯一标识码，如 task_20261102_153022"),
    db: Session = Depends(get_db),
):

    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


@router.post(
    "/api/tasks/{task_id}/start",
    response_model=TaskActionResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="一键触发启动指定巡检任务",
    description="从数据库装载配置，组装参数拉起后台 Python 子进程，并自动挂载启动伴生性能采样守护线程与日志缓冲监听。",
)
def start_task_execution(
    task_id: str = FastPath(..., description="待启动的任务全局识别码"),
    db: Session = Depends(get_db),
):
    """
    异步启动指定的自动化巡检子进程。

    Args:
        task_id: 任务全局识别码
        db: 数据库会话

    Returns:
        TaskActionResponse: 包含状态码、提示信息、任务 ID 及拉起子进程 PID
    """
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "running":
        return {
            "code": 200,
            "message": "任务已经在运行中",
            "task_id": task_id,
            "pid": task.pid,
        }

    success = task_manager.start_task(task_id)

    if not success:
        raise HTTPException(
            status_code=500, detail="拉起任务进程失败，请检查运行环境或日志"
        )

    return {"code": 200, "message": "任务启动成功", "task_id": task_id}


@router.post(
    "/api/tasks/{task_id}/stop",
    response_model=TaskActionResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="一键优雅终止正在运行的任务",
    description="向目标 Electron 应用广播原生 WM_CLOSE 退出信号，并递归优雅终止子进程树，同时停止性能采集线程并回填终态产物。",
)
def stop_task_execution(
    task_id: str = FastPath(..., description="待停止的任务全局识别码"),
):
    """
    优雅终止正在运行的任务子进程及其渲染窗口。

    Args:
        task_id: 任务全局识别码

    Returns:
        TaskActionResponse: 终止操作执行结果
    """
    stopped = task_manager.stop_task(task_id)

    if not stopped:
        return {"code": 200, "message": "任务未在运行或已处于终态", "task_id": task_id}

    return {"code": 200, "message": "任务已安全终止并归档", "task_id": task_id}


def _async_cleanup_disk_and_hub(target_dir_str: Optional[str]):
    """后台异步抹除物理磁盘产物并增量重构大盘门户，彻底消除 HTTP 阻塞"""
    import shutil
    from utils.paths import RUNS_DIR
    if target_dir_str:
        try:
            p = Path(target_dir_str).resolve()
            if RUNS_DIR.resolve() in p.parents:
                shutil.rmtree(p, ignore_errors=True)
                logger.info(f"🗑️ [TaskDelete-Async] 物理磁盘产物已异步抹除完毕: {p}")
            else:
                logger.warning(f"⚠️ [TaskDelete-Async] 目录 {p} 不在 reports/runs/ 围栏内，跳过清理以防误伤！")
        except Exception as e:
            logger.error(f"后台异步删除物理磁盘产物失败: {e}")

    # 异步重构大盘报告，确保大盘 HTML 列表同步剔除
    try:
        from utils.report_hub import ReportHub
        ReportHub().build_index_html()
        logger.info("📊 [TaskDelete-Async] 大盘统一门户首页后台异步重构完成")
    except Exception as he:
        logger.debug(f"后台重构大盘报告通知 (可忽略): {he}")


@router.delete(
    "/api/tasks/{task_id}",
    response_model=TaskDeleteResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="安全级联删除指定任务及物理产物",
    description="从数据库与物理磁盘彻底清理指定任务。若任务正在运行则禁止删除；若包含已提交禅道的有效缺陷，提供保护校验。",
)
def delete_task_run(
    task_id: str = FastPath(..., description="待删除的任务全局识别码"),
    force: bool = Query(default=False, description="是否强制删除（忽略缺陷保护警报）"),
    cleanup_disk: bool = Query(default=True, description="是否级联清理磁盘物理运行目录 (reports/runs/<app>/<run_id>)"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    安全级联删除指定任务的主记录、指标、运行步骤及磁盘物理产物。

    Args:
        task_id: 任务全局识别码
        force: 是否强制删除 (忽略已提禅道缺陷工单保护拦截)
        cleanup_disk: 是否同时清理物理磁盘上的截图与报告目录
        background_tasks: FastAPI 后台任务上下文
        db: 数据库会话

    Returns:
        TaskDeleteResponse: 包含状态码、清理任务 ID、物理路径与缺陷清理计数
    """
    from utils.paths import PROJECT_ROOT, RUNS_DIR, find_run_dir

    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="未找到指定的任务记录")

    # 1. 运行态安全互斥拦截：仅当物理子进程真实存活时才拦截；若物理进程已死但数据库残留 running，允许清理
    if task_manager.is_running(task_id):
        raise HTTPException(status_code=400, detail="该任务当前正在物理运行中，请先点击【终止】停止任务后再执行删除")

    # 2. 缺陷安全保护防呆
    associated_bugs = db.query(BugRecord).filter(BugRecord.task_id == task_id).all()
    zentao_bugs = [b for b in associated_bugs if b.zentao_id]
    if zentao_bugs and not force:
        raise HTTPException(
            status_code=409,
            detail=f"安全保护拦截：该任务关联了 {len(zentao_bugs)} 条已提交至禅道的有效缺陷工单 (如 #{zentao_bugs[0].zentao_id})！如确认放弃这些证据并强行清理，请传递 force=true 参数。"
        )

    target_dir = None
    # 3. 探查物理磁盘产物目录路径 (严格兼容 RUNS_DIR 相对路径与 PROJECT_ROOT 相对路径)
    if cleanup_disk:
        if task.run_dir:
            p = Path(task.run_dir.replace("\\", "/").strip("/"))
            if not p.is_absolute():
                if (RUNS_DIR / p).exists() and (RUNS_DIR / p).is_dir():
                    target_dir = RUNS_DIR / p
                elif (PROJECT_ROOT / p).exists() and (PROJECT_ROOT / p).is_dir():
                    target_dir = PROJECT_ROOT / p
            elif p.exists() and p.is_dir():
                target_dir = p
        if not target_dir:
            # 尝试通过 task_id / run_id 探查磁盘真实物理路径 (支持 explore_、smoke_、yaml_)
            clean_id = task.id.replace("task_", "")
            for prefix in ["", "explore_", "smoke_", "yaml_"]:
                cand_id = f"{prefix}{clean_id}" if prefix else clean_id
                cand = find_run_dir(cand_id)
                if cand and cand.exists() and cand.is_dir():
                    target_dir = cand
                    break

    # 4. 级联解除或清理关联 Bug
    if associated_bugs:
        for b in associated_bugs:
            if b.zentao_id:
                # 已提禅道的 Bug 仅解除 task_id 关联，保留其作为历史独立缺陷归档
                b.task_id = None
            else:
                # 未提禅道的草稿/临时 Bug 彻底从数据库删除
                db.delete(b)

    # 5. 级联清理关联的调度队列流水记录 (TaskQueueItem)
    from ..models import TaskQueueItem
    db.query(TaskQueueItem).filter(TaskQueueItem.task_id == task_id).delete()

    # 6. 删除任务主记录 (其 steps, metrics 与 queue_items 会通过 cascade='all, delete-orphan' 自动级联清理)
    db.delete(task)
    db.commit()

    # 7. 将耗时的磁盘小文件树抹除与大盘全量扫描交由后台任务异步执行，使 HTTP 接口在 20ms 内即时返回
    target_dir_str = str(target_dir.resolve()) if (target_dir and target_dir.exists()) else None
    if background_tasks:
        background_tasks.add_task(_async_cleanup_disk_and_hub, target_dir_str)
    else:
        import threading
        threading.Thread(target=_async_cleanup_disk_and_hub, args=(target_dir_str,), daemon=True).start()

    return {
        "code": 200,
        "message": "任务记录已安全注销，磁盘产物与大盘已转入后台极速抹除",
        "task_id": task_id,
        "deleted_disk_path": target_dir_str,
        "cleaned_bugs_count": len(associated_bugs),
    }


@router.get(
    "/api/tasks/{task_id}/logs",
    response_model=TaskLogsResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="拉取任务控制台日志切片",
    description="获取指定任务最近在控制台输出的日志文本切片（默认最近 150 行）。",
)
def get_task_logs(
    task_id: str = FastPath(..., description="待拉取日志的任务全局识别码"),
    tail: int = Query(default=150, ge=10, le=3000, description="读取最近日志行数"),
):
    """
    获取指定任务最近输出的控制台运行日志行。

    Args:
        task_id: 任务全局识别码
        tail: 获取的日志行数尾部切片

    Returns:
        TaskLogsResponse: 包含任务 ID、本次行数与日志列表
    """
    logs = task_manager.get_logs(task_id, tail=tail)

    return {"task_id": task_id, "count": len(logs), "logs": logs}



@router.get(
    "/api/tasks/{task_id}/apis",
    response_model=TaskApisResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="获取巡检任务捕获解析的业务 API 接口清单",
    description="自动解析底层网络监听池与单次报告中的 `api_registry.json`，将前端交互触发的全部后端接口分类呈现为 OpenAPI / Postman 风格契约清单。",
)
def get_task_apis(
    task_id: str = FastPath(..., description="巡检任务标识码"),
    db: Session = Depends(get_db),
):
    """
    解析并返回指定任务捕获到的业务 HTTP/WebSocket 接口契约清单。

    Args:
        task_id: 任务全局识别码
        db: 数据库会话

    Returns:
        TaskApisResponse: 包含汇总统计、页面归属映射与平铺接口列表
    """
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    run_dir = task.run_dir

    if not run_dir:
        # 尝试查找最新的 run 目录
        from utils.paths import get_all_run_folders

        runs = get_all_run_folders(app_name=task.app_name)

        if runs:
            run_dir = f"{task.app_name}/{runs[0].name}"

    if not run_dir:
        return {
            "task_id": task_id,
            "run_dir": None,
            "summary": {},
            "page_scopes": {},
            "global_flat_apis": [],
        }

    api_path = (
        PROJECT_ROOT
        / "reports"
        / "runs"
        / run_dir
        / "screenshots"
        / "api_registry.json"
    )

    if not api_path.exists():
        api_path = PROJECT_ROOT / "reports" / "runs" / run_dir / "api_registry.json"

    if not api_path.exists():
        return {
            "task_id": task_id,
            "run_dir": run_dir,
            "summary": {},
            "page_scopes": {},
            "global_flat_apis": [],
        }

    try:
        with open(api_path, "r", encoding="utf-8") as f:
            api_data = json.load(f)

        return {
            "task_id": task_id,
            "run_dir": run_dir,
            "summary": api_data.get("summary", {}),
            "page_scopes": api_data.get("page_scopes", {}),
            "global_flat_apis": api_data.get(
                "global_flat_apis", api_data.get("summary", {}).get("endpoints", [])
            ),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析已测接口清单失败: {e}")


@router.get(
    "/api/tasks/{task_id}/env_info",
    response_model=TaskEnvInfoResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="获取指定任务的案发/运行时环境基线快照 (env_info.json)",
    description="解析并返回该次巡检启动时的 2D 前端包版本路径、UE5 孪生工程版本路径、N+1 业务接口与推流网关配置。",
)
def get_task_env_info(
    task_id: str = FastPath(..., description="巡检任务标识码"),
    db: Session = Depends(get_db),
):
    """
    读取并返回该次巡检启动时的软硬件与网络基线快照 (env_info.json)。

    Args:
        task_id: 任务全局识别码
        db: 数据库会话

    Returns:
        TaskEnvInfoResponse: 包含环境快照对象与美化 JSON 文本
    """
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    run_dir = task.run_dir or ""
    if run_dir.startswith("reports/runs/") or run_dir.startswith("reports\\runs\\"):
        run_dir = run_dir.replace("reports/runs/", "").replace("reports\\runs\\", "")

    if not run_dir:
        return {
            "task_id": task_id,
            "run_dir": None,
            "exists": False,
            "env_info": None,
            "raw_json": None,
            "message": "该任务尚未关联运行产物目录",
        }

    env_path = PROJECT_ROOT / "reports" / "runs" / run_dir / "env_info.json"
    if not env_path.exists():
        env_path = PROJECT_ROOT / "reports" / "runs" / Path(run_dir).name / "env_info.json"

    if not env_path.exists():
        return {
            "task_id": task_id,
            "run_dir": run_dir,
            "exists": False,
            "env_info": None,
            "raw_json": None,
            "message": "未采集到该批次的环境基线快照记录 (env_info.json 不存在)",
        }

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "task_id": task_id,
            "run_dir": run_dir,
            "exists": True,
            "env_info": data,
            "raw_json": json.dumps(data, indent=2, ensure_ascii=False),
            "message": "环境基线快照加载成功",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取环境基线快照失败: {e}")


