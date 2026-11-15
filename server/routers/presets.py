"""
预设巡检任务库与快速拉起
"""

import datetime
import json
import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Path as FastPath
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TaskRun, PresetTaskRecord
from ..schemas import (
    PresetTaskResponse,
    PresetTaskCreate,
    PresetDeleteResponse,
    TaskResponse,
)
from ..task_manager import task_manager

logger = logging.getLogger("server.presets")
router = APIRouter()


DEFAULT_PRESET_TASKS = [
    {
        "id": "preset_zhaiwan_explore_full",
        "title": "全栈地毯式扫荡巡检",
        "app_name": "zhaiwan",
        "mode": "explore",
        "badge": "推荐",
        "max_steps": 2000,
        "max_times": 600,
        "reset_memory": True,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "执行全系统全量页面冒烟体检：请自适应悬停与点击顶部导航栏，系统性遍历当前应用全部一级菜单与所有下属二级业务页面。\n在到达每个子页面后，请重点执行三维健康度体检：\n1. 页面加载与渲染：检查页面主体框架与业务面板是否完整渲染就绪，是否存在白屏、大面积黑屏或核心组件未渲染；\n2. 网络接口通信：静默校验页面加载及初载触发的网络请求，排查是否存在 5xx 服务端异常、404 资源丢失或接口超时；\n3. 控制台运行健康：嗅探控制台是否存在未捕获的严重 JavaScript 运行时报错（如 TypeError、Vue 渲染期崩溃、WebGL 上下文丢失）。\n\n每个页面完成健康核验后即平滑推进至下一个菜单，无需在单一页面深陷无休止的复杂表单穷举，确保自适应覆盖当前系统的每一个业务模块！",
        "description": "系统性遍历全部业务页面，三维体检页面白屏加载、底层接口通信与控制台无声报错。",
    },
    {
        "id": "preset_zhaiwan_3d_stress",
        "title": "中央 3D 视界与像素流抗压专项",
        "app_name": "zhaiwan",
        "mode": "explore",
        "badge": "抗压",
        "max_steps": 1000,
        "max_times": 300,
        "reset_memory": True,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "全面探测中央 3D 矿山数字孪生模型健康度：重点进入三维视口页面，执行轨道视角全向旋转 (rotate_3d) 与镜头深度推进拉远 (zoom)，并发起三维视口晃动抗压测试 (canvas_stress_drag)，深度排查 UE5 像素流是否有花屏、断流、模型破面或 WebGL 上下文丢失！",
        "description": "重点进入中央三维视口执行轨道旋转、镜头推拉与高频甩动，深度压测 UE5 伴生进程与 WebRTC 掉帧风险。",
    },
    {
        "id": "preset_zhaiwan_smoke_tour",
        "title": "二级菜单极速全量冒烟体检",
        "app_name": "zhaiwan",
        "mode": "smoke",
        "tour": True,
        "badge": "冒烟",
        "max_steps": 0,
        "max_times": 150,
        "reset_memory": True,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "",
        "description": "轻量级高频冒烟，快速按序遍历全部二级业务菜单，执行无声报错、核心接口与页面视觉三阶门禁体检。",
    },
    {
        "id": "preset_zhaiwan_home_yaml",
        "title": "首页业务深度确定性回归 (YAML)",
        "app_name": "zhaiwan",
        "mode": "case",
        "badge": "回归",
        "max_steps": 500,
        "max_times": 200,
        "reset_memory": False,
        "ignore_errors": True,
        "case_path": "test_cases/test_home_mine_intro.yaml",
        "macro_objective": "精确重现已通过静态合规检验的 YAML 业务流程：首页矿山简介深度巡检",
        "description": "精确执行已固化的标准自动化回归脚本，100% 确定性复现关键业务链路并核对 API。",
    },
    {
        "id": "preset_liwutong_explore",
        "title": "数字孪生采矿与选矿自主探索",
        "app_name": "liwutong",
        "mode": "explore",
        "badge": "探索",
        "max_steps": 150,
        "max_times": 45,
        "reset_memory": False,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "全面扫荡矿山各业务模块：深入探测选矿看板、采场可视化与设备一张图，挖掘未覆盖盲区中的数据不一致与前端崩溃 Bug！",
        "description": "数字孪生采矿与选矿全业务板块探测，深入验证选矿流程、指标卡片与报警处置流程。",
    },
]


@router.get(
    "/api/tasks/presets",
    response_model=List[PresetTaskResponse],
    tags=["1. 平台基础与选项"],
    summary="获取预置的标准巡检任务库 (系统预设 + 用户自定义预设)",
    description="提供常用巡检任务模板，以及用户在界面中自行保存/编辑的个性化预设方案。优先系统预设置顶，用户自定义预设按最新更新时间倒序排列。",
)
def get_preset_tasks(db: Session = Depends(get_db)):
    # 按照 is_system 降序置顶，其次按 updated_at 倒序排列（最新修改/新建的在最前）
    return (
        db.query(PresetTaskRecord)
        .order_by(
            PresetTaskRecord.is_system.desc(),
            PresetTaskRecord.updated_at.desc().nullslast(),
            PresetTaskRecord.id.asc(),
        )
        .all()
    )


@router.post(
    "/api/tasks/presets",
    response_model=PresetTaskResponse,
    tags=["1. 平台基础与选项"],
    summary="保存或更新预设巡检任务模板",
    description="支持将前端表单微调后的配置持久化保存为预设，方便日后一键拉起或再次微调；若传入已有 id 则覆盖更新。",
)
def save_or_update_preset_task(
    payload: PresetTaskCreate, db: Session = Depends(get_db)
):

    now = datetime.datetime.now()

    preset_id = payload.id

    if not preset_id:
        preset_id = f"preset_user_{now.strftime('%Y%m%d_%H%M%S')}"

    existing = (
        db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    )

    if existing:
        existing.title = payload.title

        existing.app_name = payload.app_name

        existing.mode = payload.mode

        existing.badge = payload.badge or "自定义"

        existing.description = (
            payload.description
            or f"用户自定义任务: {payload.mode}模式 / {payload.max_steps}步"
        )

        existing.macro_objective = payload.macro_objective

        existing.max_steps = payload.max_steps

        existing.max_times = payload.max_times

        existing.reset_memory = payload.reset_memory

        existing.ignore_errors = payload.ignore_errors

        existing.case_path = payload.case_path
        existing.tour = payload.tour
        existing.resume_from = payload.resume_from
        existing.reexplore = payload.reexplore
        existing.start_delay = payload.start_delay
        existing.wait_ready = payload.wait_ready
        existing.wait_timeout = payload.wait_timeout
        existing.ignore_env_check = payload.ignore_env_check
        existing.updated_at = now

        db.commit()

        db.refresh(existing)

        return existing

    else:
        new_preset = PresetTaskRecord(
            id=preset_id,
            title=payload.title,
            app_name=payload.app_name,
            mode=payload.mode,
            badge=payload.badge or "自定义",
            description=payload.description
            or f"用户自定义任务: {payload.mode}模式 / {payload.max_steps}步",
            macro_objective=payload.macro_objective,
            max_steps=payload.max_steps,
            max_times=payload.max_times,
            reset_memory=payload.reset_memory,
            ignore_errors=payload.ignore_errors,
            case_path=payload.case_path,
            tour=payload.tour,
            resume_from=payload.resume_from,
            reexplore=payload.reexplore,
            start_delay=payload.start_delay,
            wait_ready=payload.wait_ready,
            wait_timeout=payload.wait_timeout,
            ignore_env_check=payload.ignore_env_check,
            is_system=False,
            created_at=now,
            updated_at=now,
        )

        db.add(new_preset)

        db.commit()

        db.refresh(new_preset)

        return new_preset


@router.delete(
    "/api/tasks/presets/{preset_id}",
    response_model=PresetDeleteResponse,
    tags=["1. 平台基础与选项"],
    summary="删除预设任务模板",
    description="从数据库中物理注销并删除指定的个性化预设模板。",
)
def delete_preset_task(
    preset_id: str = FastPath(..., description="待删除的预设模板 ID (如 preset_user_xxx)"),
    db: Session = Depends(get_db),
):
    """
    删除指定的个性化预设任务模板。

    Args:
        preset_id: 预设任务全局标识码
        db: 数据库会话

    Returns:
        PresetDeleteResponse: 包含状态码与删除预设 ID
    """
    existing = (
        db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    )

    if not existing:
        raise HTTPException(status_code=404, detail="预设未找到")

    db.delete(existing)

    db.commit()

    return {"code": 200, "message": "预设删除成功", "preset_id": preset_id}


@router.post(
    "/api/tasks/presets/{preset_id}/launch",
    response_model=TaskResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="按预设模板一键快速拉起巡检任务",
    description="根据预设模板 ID 直接创建巡检任务并在后台立即异步拉起，无需手动填写表单。",
)
def launch_preset_task(
    preset_id: str = FastPath(..., description="预设任务模板 ID"),
    db: Session = Depends(get_db),
):

    target_preset = (
        db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    )

    if not target_preset:
        target_preset = next(
            (p for p in DEFAULT_PRESET_TASKS if p["id"] == preset_id), None
        )

        if not target_preset:
            raise HTTPException(status_code=404, detail="Preset not found")

        # 兼容 dict 访问

        p_title = target_preset["title"]

        p_app = target_preset["app_name"]

        p_mode = target_preset["mode"]

        p_obj = target_preset["macro_objective"]

        p_steps = target_preset["max_steps"]

        p_times = target_preset["max_times"]

        p_reset = target_preset["reset_memory"]

        p_ignore = target_preset["ignore_errors"]

        p_case = target_preset["case_path"]
        p_tour = target_preset.get("tour", False)
        p_resume = target_preset.get("resume_from")
        p_reexplore = target_preset.get("reexplore")
        p_start_delay = target_preset.get("start_delay")
        p_wait_ready = target_preset.get("wait_ready")
        p_wait_timeout = target_preset.get("wait_timeout", 60.0)
        p_ignore_env = target_preset.get("ignore_env_check", False)

    else:
        p_title = target_preset.title
        p_app = target_preset.app_name
        p_mode = target_preset.mode
        p_obj = target_preset.macro_objective
        p_steps = target_preset.max_steps
        p_times = target_preset.max_times
        p_reset = target_preset.reset_memory
        p_ignore = target_preset.ignore_errors
        p_case = target_preset.case_path
        p_tour = getattr(target_preset, "tour", False)
        p_resume = getattr(target_preset, "resume_from", None)
        p_reexplore = getattr(target_preset, "reexplore", None)
        p_start_delay = getattr(target_preset, "start_delay", None)
        p_wait_ready = getattr(target_preset, "wait_ready", None)
        p_wait_timeout = getattr(target_preset, "wait_timeout", 60.0)
        p_ignore_env = getattr(target_preset, "ignore_env_check", False)

    now = datetime.datetime.now()
    task_id = f"task_{now.strftime('%Y%m%d_%H%M%S')}"

    app_short_names = {"zhaiwan": "寨湾", "liwutong": "里伍铜", "tianrui": "天瑞"}
    short_mine = app_short_names.get(p_app, p_app)
    clean_title = re.sub(r"^【.*?】\s*", "", p_title)

    task = TaskRun(
        id=task_id,
        name=f"【{short_mine}】{clean_title} ({now.strftime('%H:%M:%S')})",
        app_name=p_app,
        mode=p_mode,
        status="pending",
        macro_objective=p_obj,
        max_steps=p_steps,
        max_times=p_times,
        reset_memory=p_reset,
        ignore_errors=p_ignore,
        case_path=p_case,
        tour=p_tour,
        resume_from=p_resume,
        reexplore=p_reexplore,
        start_delay=p_start_delay,
        wait_ready=p_wait_ready,
        wait_timeout=p_wait_timeout,
        ignore_env_check=p_ignore_env,
        explore_context=f"docs/explore_rules_{p_app}.md",
        trigger_type="manual",
        start_time=now,
    )

    db.add(task)

    db.commit()

    db.refresh(task)

    # 立即触发启动

    success = task_manager.start_task(task_id)

    if not success:
        raise HTTPException(status_code=500, detail="拉起预设任务失败，请检查运行环境")

    db.refresh(task)

    return task


