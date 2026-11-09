import asyncio
import datetime
import json
import logging
import os
import re
import threading
import time

from pathlib import Path

from typing import List, Optional, Dict, Any


from fastapi import (
    BackgroundTasks,
    FastAPI,
    Depends,
    HTTPException,
    Query,
    Path as FastPath,
    Body,
    WebSocket,
    WebSocketDisconnect,
)

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse, RedirectResponse, Response

from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session


from .database import get_db, init_db

from .models import TaskRun, BugRecord, PerformanceMetric, PresetTaskRecord, TaskQueueItem

from .schemas import (
    TaskCreate,
    TaskResponse,
    BugResponse,
    BugUpdate,
    PerformanceMetricResponse,
    PerformanceSummaryResponse,
    LivePerformanceSnapshotResponse,
    ConfigOptionsResponse,
    PresetTaskResponse,
    PresetTaskCreate,
    QueueItemCreate,
    QueueItemResponse,
)

from .task_manager import task_manager

from .performance_monitor import performance_monitor


CURRENT_DIR = Path(__file__).resolve().parent

PROJECT_ROOT = CURRENT_DIR.parent


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)

logger = logging.getLogger("server.api")


# Swagger 规范元数据定义

tags_metadata = [
    {
        "name": "1. 平台基础与选项",
        "description": "健康心跳检查、前端免敲命令表单所需的应用、模式与预置提示词模板字典",
    },
    {
        "name": "2. 巡检任务生命周期调度",
        "description": "巡检任务创建、查询列表、一键拉起异步子进程、优雅停机终止、控制台实时日志与 WebSocket 流",
    },
    {
        "name": "3. 缺陷治理与禅道同步",
        "description": "全局缺陷资产检索、错误现场与 AI 智能初诊排查详情、一键自动提单至公司禅道项目系统",
    },
    {
        "name": "4. 多核全栈性能监控",
        "description": "UE5 引擎、Chromium 渲染进程树、CDP DOM/堆内存/WebRTC 帧率、独立显卡 GPU 显存的实时探针与时序指标",
    },
]


app = FastAPI(
    title="⚡ Electron AI Vision 智能巡检与多核性能中枢平台 API",
    description="""

## 平台定位与核心架构

本平台是专为基于 Chromium 的 **Electron 桌面端大屏** 以及 **UE5 伴生数字孪生视界** 打造的端到端自动化巡检与全景监控中枢。



### 🌟 核心能力支持：

* **免敲命令任务调度**：参数与模式完全选项化，支持 AI 自主探索、二级菜单全量冒烟、确定性 YAML 回放与全量回归。

* **双核全栈性能监控探针**：

  * **Chromium 渲染端**：无侵入直连 CDP（DOM 节点、JS 事件监听器、V8 JS 堆内存、WebRTC 像素流实时 FPS）。

  * **UE5 伴生进程**：实时采样物理常驻内存（RSS / Working Set）与 CPU 占用率。

  * **独立 GPU 显卡**：静默追踪 3D 渲染核心负载与专用显存使用。

* **缺陷资产闭环与去重**：自动捕获案发现场报错、截图，结合大模型查重，支持一键分流推单至公司禅道。

* **多通道实时通信**：提供 WebSocket 实时日志流推送与实时性能数据流。

    """,
    version="1.2.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
)


# 允许跨域请求 (为前后端分离与大屏仪表盘服务)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局活跃 WebSocket 连接池（用于 shutdown/reload 时主动断开，彻底杜绝 uvicorn 卡死）
active_websockets: set = set()


@app.on_event("startup")
def on_startup():
    """服务冷启动生命周期钩子：冷启动自动物理快照、初始化数据库结构并自动同步已有全局缺陷库"""

    from .database import backup_database

    backup_database(max_backups=5)

    logger.info("⚡ 正在初始化数据库引擎与表结构 (含自动平滑迁移)...")

    init_db()

    # 3. 自动全量扫描磁盘运行报告与缺陷库并同步入库 (冷启动强制同步)

    try:
        from .database import SessionLocal

        from .sync_service import perform_hot_sync

        db = SessionLocal()

        sync_res = perform_hot_sync(db, force=True)

        db.close()

        logger.info(f"✨ 已自动同步本地历史巡检报告与全局缺陷库入库！({sync_res})")

    except Exception as te:
        logger.debug(f"冷启动增量同步历史运行异常 (可忽略): {te}")

    # 4. 滚动清理超过 24 小时的环境实时心电图数据 (正式测试任务数据永久保全，绝不自动清理)

    try:
        deleted = performance_monitor.cleanup_expired_ambient_metrics(hours=24)

        if deleted > 0:
            logger.info(
                f"🧹 冷启动数据治理：自动清理了 {deleted} 条超过 24 小时的环境实时心电图打点"
            )

    except Exception as e:
        logger.debug(f"滚动清理环境时序异常 (可忽略): {e}")

    # 5. 启动后台常驻多项目环境监控守护引擎 (按天瑞/寨湾/里伍铜多项目独立采样，滚动维持24小时时序)

    try:
        performance_monitor.start_ambient_monitoring(interval_sec=4.0)

    except Exception as e:
        logger.warning(f"启动环境守护监控异常: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    """关机/热重载生命周期钩子：主动关闭所有活跃 WebSocket 长连接与后台守护，杜绝 uvicorn reload 死锁"""
    logger.info("🛑 [Shutdown] 正在释放所有活跃 WebSocket 连接与后台监控守护...")
    try:
        performance_monitor.stop_ambient_monitoring()
    except Exception as se:
        logger.debug(f"停止环境守护异常: {se}")
    # 1. 主动断开所有 WebSocket 长连接，通知前端优雅重连
    for ws in list(active_websockets):
        try:
            await ws.close(code=1001, reason="Server shutting down or reloading")
        except Exception:
            pass
    active_websockets.clear()
    platform_subscribers.clear()

    # 2. 安全停止所有性能时序采集守护线程
    try:
        from .performance_monitor import performance_monitor

        with performance_monitor._lock:
            for task_id, stop_event in list(performance_monitor._stop_events.items()):
                stop_event.set()
    except Exception:
        pass
    logger.info("✨ [Shutdown] 所有长连接与守护线程释放完毕，服务退出/重载就绪！")


# 静态文件挂载：平台前端 UI 静态资源与测试产物报告截图

STATIC_DIR = CURRENT_DIR / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


REPORTS_DIR = PROJECT_ROOT / "reports"

if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

if ARTIFACTS_DIR.exists():
    app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")


@app.get("/report-hub", include_in_schema=False)
@app.get("/reports-hub", include_in_schema=False)
def redirect_to_report_hub():
    """统一重定向至自动化巡检全量大盘门户首页"""

    index_file = REPORTS_DIR / "runs" / "index.html"

    if not index_file.exists():
        try:
            from utils.report_hub import ReportHub

            ReportHub().build_index_html()

        except Exception as e:
            logger.warning(f"自动构建大盘首页警告: {e}")

    return RedirectResponse(url="/reports/runs/index.html", status_code=302)


@app.get("/", include_in_schema=False)
def serve_index():
    """Web 控制台首页面入口"""

    index_file = STATIC_DIR / "index.html"

    if index_file.exists():
        return FileResponse(str(index_file))

    return {"message": "Vision Platform API Server Running"}


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon():
    """网站专属图标 (Favicon)"""
    icon_file = STATIC_DIR / "favicon.svg"
    if icon_file.exists():
        return FileResponse(str(icon_file), media_type="image/svg+xml")
    return Response(status_code=204)


# =============================================================================

# 0. 缺陷统一治理与同步 API (单点真理源：同步全局库、运行目录与持久化数据库)

# =============================================================================


@app.post(
    "/api/update_bug_status",
    tags=["3. 缺陷治理与禅道同步"],
    summary="大盘门户统一接口：更新缺陷生命周期状态",
    description="统一更新缺陷状态，同步更新全局缺陷库、运行目录与平台数据库。",
)
@app.post(
    "/api/update_bug_detail",
    tags=["3. 缺陷治理与禅道同步"],
    summary="大盘门户统一接口：更新缺陷详细字段与排查说明",
    description="统一更新责任人、严重度、排查批注或回填禅道单号，同步更新全局缺陷库、运行目录与平台数据库。",
)
async def update_bug_compatible_api(data: dict):

    from utils.bug_updater import update_bug_record

    result = update_bug_record(data)

    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "更新缺陷记录失败")
        )

    return result


# =============================================================================

# 1. 基础配置与选项 API (免敲命令，选项化核心)

# =============================================================================


@app.get(
    "/api/health",
    tags=["1. 平台基础与选项"],
    summary="平台健康心跳检查",
    description="检测后端平台服务核心服务、数据库会话与运行时间戳是否处于正常就绪状态。",
)
def health_check():

    return {
        "status": "healthy",
        "service": "Electron AI Vision Platform",
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }


@app.get(
    "/api/config/options",
    response_model=ConfigOptionsResponse,
    tags=["1. 平台基础与选项"],
    summary="获取前端表单可选项与提示词模板库",
    description="为前端工作台提供一键选择的矿山应用、测试模式列表、开箱即用的高阶探索 Prompt 模板库以及禅道鉴权配置状态。",
)
def get_config_options():

    apps = [
        {
            "key": "zhaiwan",
            "name": "寨湾矿山 (Zhaiwan)",
            "desc": "包含中央 UE5 像素流三维矿山与两侧 2D 业务看板",
        },
        {
            "key": "liwutong",
            "name": "里伍铜矿山 (Liwutong)",
            "desc": "数字孪生采矿与智能选矿平台",
        },
        {
            "key": "tianrui",
            "name": "四川天瑞矿山 (Tianrui)",
            "desc": "四川天瑞大屏数字孪生系统",
        },
    ]

    modes = [
        {
            "key": "explore",
            "name": "自主探索模式 (Explorer)",
            "desc": "多模态大模型动态驱动，自主规划链路与挖掘未知深层 Crash",
        },
        {
            "key": "case",
            "name": "确定性用例回放 (YAML Case)",
            "desc": "精确重现已通过静态合规检验的标准自然语言回归流程",
        },
    ]

    yaml_cases = [{"name": "运行全量用例 (批量回归)", "path": ""}]
    test_cases_dir = Path("test_cases")
    if test_cases_dir.exists():
        for p in sorted(test_cases_dir.glob("*.yaml")):
            if p.is_file() and p.stat().st_size > 0:
                yaml_cases.append({
                    "name": p.name,
                    "path": str(p).replace("\\", "/")
                })

    templates = [
        {
            "title": "全系统页面冒烟体检 (推荐)",
            "prompt": "执行全系统全量页面冒烟体检：请自适应悬停与点击顶部导航栏，系统性遍历当前应用全部一级菜单与所有下属二级业务页面。\n在到达每个子页面后，请重点执行三维健康度体检：\n1. 页面加载与渲染：检查页面主体框架与业务面板是否完整渲染就绪，是否存在白屏、大面积黑屏或核心组件未渲染；\n2. 网络接口通信：静默校验页面加载及初载触发的网络请求，排查是否存在 5xx 服务端异常、404 资源丢失或接口超时；\n3. 控制台运行健康：嗅探控制台是否存在未捕获的严重 JavaScript 运行时报错（如 TypeError、Vue 渲染期崩溃、WebGL 上下文丢失）。\n\n每个页面完成健康核验后即平滑推进至下一个菜单，无需在单一页面深陷无休止的复杂表单穷举，确保自适应覆盖当前系统的每一个业务模块！",
        },
        {
            "title": "三维数字孪生视界抗压攻坚",
            "prompt": "全面探测中央 3D 矿山数字孪生模型健康度：重点进入三维视口页面，执行轨道视角全向旋转 (rotate_3d) 与镜头深度推进拉远 (zoom)，并发起三维视口晃动抗压测试 (canvas_stress_drag)，深度排查 UE5 像素流是否有花屏、断流、模型破面或 WebGL 上下文丢失！",
        },
        {
            "title": "未测盲区定向突击",
            "prompt": "全面攻克未探索盲区：重点深入遍历【设备管理】与【安全管理】下的各个子模块，优先测试各页面中的 2D 指标看板、折线图日/月/年维度切换、列表明细与操作弹窗，深入挖掘未知Bug与接口异常，避开已探索完备的模块。",
        },
    ]

    # 检查禅道是否具备配置与动态基地址

    from config.settings import settings

    zentao_ok = bool(
        os.getenv("ZENTAO_PASSWORD") or getattr(settings, "zentao_password", None)
    )

    zentao_url = getattr(settings, "zentao_url", "http://192.140.163.129:8080")

    if zentao_url:
        zentao_url = zentao_url.rstrip("/")

    return ConfigOptionsResponse(
        apps=apps,
        modes=modes,
        yaml_cases=yaml_cases,
        prompt_templates=templates,
        zentao_configured=zentao_ok,
        zentao_base_url=zentao_url,
        report_hub_url="/report-hub",
    )


# =============================================================================

# 2. 预设巡检任务库 API (Preset Tasks)

# =============================================================================


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
        "mode": "explore",
        "tour": True,
        "badge": "冒烟",
        "max_steps": 1500,
        "max_times": 150,
        "reset_memory": True,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "全量页面极速冒烟体检：自适应快速遍历当前系统全部业务菜单，校验两级路由跳转、页面白屏及核心接口通信健康度。",
        "description": "轻量级高频冒烟，快速校验全部菜单路由跳转、页面框架是否白屏以及核心接口通信健康度。",
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


@app.get(
    "/api/tasks/presets",
    response_model=List[PresetTaskResponse],
    tags=["1. 平台基础与选项"],
    summary="获取预置的标准巡检任务库 (系统预设 + 用户自定义预设)",
    description="提供系统默认验证的常用巡检任务模板，以及用户在界面中自行保存/编辑的个性化预设方案。",
)
def get_preset_tasks(db: Session = Depends(get_db)):

    # 1. 确保系统预设已装载到数据库中并与代码保持实时同步

    for p in DEFAULT_PRESET_TASKS:
        exist = (
            db.query(PresetTaskRecord).filter(PresetTaskRecord.id == p["id"]).first()
        )

        if not exist:
            rec = PresetTaskRecord(
                id=p["id"],
                title=p["title"],
                app_name=p["app_name"],
                mode=p["mode"],
                badge=p["badge"],
                description=p.get("description"),
                macro_objective=p["macro_objective"],
                max_steps=p["max_steps"],
                max_times=p["max_times"],
                reset_memory=p.get("reset_memory", False),
                ignore_errors=p.get("ignore_errors", True),
                case_path=p.get("case_path"),
                tour=p.get("tour", False),
                is_system=True,
            )

            db.add(rec)

        elif exist.is_system:
            # 允许用户在源码 DEFAULT_PRESET_TASKS 中直接修改，并自动热同步至数据库

            exist.title = p["title"]

            exist.app_name = p["app_name"]

            exist.mode = p["mode"]

            exist.tour = p.get("tour", False)

            exist.badge = p["badge"]

            exist.description = p.get("description")

            exist.macro_objective = p["macro_objective"]

            exist.max_steps = p["max_steps"]

            exist.max_times = p["max_times"]

            exist.reset_memory = p.get("reset_memory", False)

            exist.ignore_errors = p.get("ignore_errors", True)

            exist.case_path = p.get("case_path")

    # 清洗历史遗留的带有固定矿山前缀的标题
    for r in db.query(PresetTaskRecord).all():
        if r.title and re.match(r"^【(?:寨湾|里伍铜|天瑞)】", r.title):
            r.title = re.sub(r"^【.*?】\s*", "", r.title)

    db.commit()

    # 2. 查询全部预设（系统预设优先，用户自定义按更新时间倒序）

    return (
        db.query(PresetTaskRecord)
        .order_by(PresetTaskRecord.is_system.desc(), PresetTaskRecord.updated_at.desc())
        .all()
    )


@app.post(
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


@app.delete(
    "/api/tasks/presets/{preset_id}",
    tags=["1. 平台基础与选项"],
    summary="删除自定义预设任务模板",
    description="删除用户创建的个性化预设模板 (系统内置预设禁止删除)。",
)
def delete_preset_task(
    preset_id: str = FastPath(..., description="预设模板 ID"),
    db: Session = Depends(get_db),
):

    existing = (
        db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    )

    if not existing:
        raise HTTPException(status_code=404, detail="预设未找到")

    if existing.is_system:
        raise HTTPException(
            status_code=403, detail="系统内置预设禁止删除，可载入后另存为新预设"
        )

    db.delete(existing)

    db.commit()

    return {"code": 200, "message": "预设删除成功", "preset_id": preset_id}


@app.post(
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


# =============================================================================

# 3. 任务调度管理 API (任务创建、启动、终止、日志与状态)

# =============================================================================


@app.post(
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
        start_time=now,
    )

    db.add(task)

    db.commit()

    db.refresh(task)

    return task


@app.get(
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
        from .sync_service import perform_hot_sync

        perform_hot_sync(db, force=False)

    q = db.query(TaskRun).order_by(TaskRun.start_time.desc())

    if status:
        q = q.filter(TaskRun.status == status)

    return q.offset(offset).limit(limit).all()


# =============================================================================
# 2.5 任务执行调度队列与定时预约 API (RPA 调度执行器，必须置于 /{task_id} 之前优先匹配)
# =============================================================================


@app.get(
    "/api/tasks/queue",
    response_model=List[QueueItemResponse],
    tags=["2. 巡检任务生命周期调度"],
    summary="查询当前任务串行执行队列看板",
    description="获取所有排队中、执行中或历史已完成的调度队列项，按优先级与排队顺序升序排列。",
)
def get_task_queue(
    status: Optional[str] = Query(default=None, description="状态筛选: pending/running/completed/failed/canceled"),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from .models import TaskQueueItem
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
    for item in items:
        resp_item = {
            "id": item.id,
            "task_id": item.task_id,
            "task_name": item.task.name if item.task else None,
            "app_name": item.task.app_name if item.task else None,
            "mode": item.task.mode if item.task else None,
            "max_steps": item.task.max_steps if item.task else None,
            "max_times": item.task.max_times if item.task else None,
            "priority": item.priority,
            "status": item.status,
            "scheduled_at": item.scheduled_at,
            "created_at": item.created_at,
            "started_at": item.started_at,
            "finished_at": item.finished_at,
            "error_message": item.error_message,
        }
        result.append(resp_item)
    return result


@app.post(
    "/api/tasks/queue",
    response_model=QueueItemResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="将巡检任务加入串行调度执行队列 (支持预约定时)",
    description="把已有任务加入串行队列，执行器将自动轮流单机独占拉起。若配置 scheduled_at 则在到达设定时间后触发。",
)
def enqueue_task(payload: QueueItemCreate, db: Session = Depends(get_db)):
    from .models import TaskQueueItem
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
    queue_id = f"queue_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    q_item = TaskQueueItem(
        id=queue_id,
        task_id=payload.task_id,
        priority=payload.priority,
        status="pending",
        scheduled_at=payload.scheduled_at,
        created_at=datetime.datetime.utcnow(),
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


@app.delete(
    "/api/tasks/queue/{queue_id}",
    tags=["2. 巡检任务生命周期调度"],
    summary="从调度队列中取消或移出任务",
)
def remove_from_queue(queue_id: str = FastPath(...), db: Session = Depends(get_db)):
    from .models import TaskQueueItem
    q_item = db.query(TaskQueueItem).filter(TaskQueueItem.id == queue_id).first()
    if not q_item:
        raise HTTPException(status_code=404, detail="未找到指定的队列记录")

    if q_item.status == "running":
        # 正在执行的任务联动终止
        task_manager.stop_task(q_item.task_id)
        q_item.status = "canceled"
        q_item.finished_at = datetime.datetime.utcnow()
        db.commit()
        return {"code": 200, "message": "正在执行的队列任务已终止并移出", "queue_id": queue_id}

    db.delete(q_item)
    db.commit()
    return {"code": 200, "message": "已从调度队列中成功移出", "queue_id": queue_id}


@app.get(
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


@app.post(
    "/api/tasks/{task_id}/start",
    tags=["2. 巡检任务生命周期调度"],
    summary="一键触发启动指定巡检任务",
    description="从数据库装载配置，组装参数拉起后台 Python 子进程，并自动挂载启动伴生性能采样守护线程与日志缓冲监听。",
)
def start_task_execution(
    task_id: str = FastPath(..., description="待启动的任务全局识别码"),
    db: Session = Depends(get_db),
):

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


@app.post(
    "/api/tasks/{task_id}/stop",
    tags=["2. 巡检任务生命周期调度"],
    summary="一键优雅终止正在运行的任务",
    description="向目标 Electron 应用广播原生 WM_CLOSE 退出信号，并递归优雅终止子进程树，同时停止性能采集线程并回填终态产物。",
)
def stop_task_execution(
    task_id: str = FastPath(..., description="待停止的任务全局识别码"),
):

    stopped = task_manager.stop_task(task_id)

    if not stopped:
        return {"code": 200, "message": "任务未在运行或已处于终态", "task_id": task_id}

    return {"code": 200, "message": "任务已安全终止并归档", "task_id": task_id}


@app.delete(
    "/api/tasks/{task_id}",
    tags=["2. 巡检任务生命周期调度"],
    summary="安全级联删除指定任务及物理产物",
    description="从数据库与物理磁盘彻底清理指定任务。若任务正在运行则禁止删除；若包含已提交禅道的有效缺陷，提供保护校验。",
)
def delete_task_run(
    task_id: str = FastPath(..., description="待删除的任务全局识别码"),
    force: bool = Query(default=False, description="是否强制删除（忽略缺陷保护警报）"),
    cleanup_disk: bool = Query(default=True, description="是否级联清理磁盘物理运行目录 (reports/runs/<app>/<run_id>)"),
    db: Session = Depends(get_db),
):
    import shutil
    from utils.paths import PROJECT_ROOT, find_run_dir

    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="未找到指定的任务记录")

    # 1. 运行态安全互斥拦截
    if task.status == "running" or task_manager.is_running(task_id):
        raise HTTPException(status_code=400, detail="该任务当前正在运行中，请先点击【终止】停止任务后再执行删除")

    # 2. 缺陷安全保护防呆
    associated_bugs = db.query(BugRecord).filter(BugRecord.task_id == task_id).all()
    zentao_bugs = [b for b in associated_bugs if b.zentao_id]
    if zentao_bugs and not force:
        raise HTTPException(
            status_code=409,
            detail=f"安全保护拦截：该任务关联了 {len(zentao_bugs)} 条已提交至禅道的有效缺陷工单 (如 #{zentao_bugs[0].zentao_id})！如确认放弃这些证据并强行清理，请传递 force=true 参数。"
        )

    deleted_disk_path = None
    # 3. 级联清理物理磁盘产物目录
    if cleanup_disk:
        target_dir = None
        if task.run_dir:
            p = Path(task.run_dir)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            if p.exists() and p.is_dir():
                target_dir = p
        if not target_dir:
            # 尝试通过 task_id / run_id 探查磁盘真实物理路径
            r_id = task.id.replace("task_", "explore_")
            cand = find_run_dir(r_id)
            if cand and cand.exists() and cand.is_dir():
                target_dir = cand

        if target_dir and target_dir.exists() and target_dir.is_dir():
            # 严格防呆围栏：必须在 reports/runs 目录下，绝对禁止误删根目录或其他重要目录
            from utils.paths import RUNS_DIR
            try:
                resolved_target = target_dir.resolve()
                resolved_runs = RUNS_DIR.resolve()
                if resolved_runs in resolved_target.parents:
                    shutil.rmtree(resolved_target, ignore_errors=True)
                    deleted_disk_path = str(resolved_target)
                    logger.info(f"🗑️ [TaskDelete] 已彻底物理抹除任务磁盘目录: {resolved_target}")
                else:
                    logger.warning(f"⚠️ [TaskDelete] 目标目录 {resolved_target} 不在 reports/runs/ 围栏内，跳过物理删除以防误伤！")
            except Exception as e:
                logger.error(f"物理删除磁盘目录失败: {e}")

    # 4. 级联解除或清理关联 Bug
    if associated_bugs:
        for b in associated_bugs:
            if b.zentao_id:
                # 已提禅道的 Bug 仅解除 task_id 关联，保留其作为历史独立缺陷归档
                b.task_id = None
            else:
                # 未提禅道的草稿/临时 Bug 彻底从数据库删除
                db.delete(b)

    # 5. 删除任务主记录 (其 steps 和 metrics 会通过 cascade='all, delete-orphan' 自动级联清理)
    db.delete(task)
    db.commit()

    # 6. 轻量重构大盘报告，确保大盘 HTML 列表同步剔除
    try:
        from utils.report_hub import ReportHub
        ReportHub().build_index_html()
    except Exception as he:
        logger.debug(f"重构大盘报告通知 (可忽略): {he}")

    return {
        "code": 200,
        "message": "任务记录及物理产物已彻底安全清除",
        "task_id": task_id,
        "deleted_disk_path": deleted_disk_path,
        "cleaned_bugs_count": len(associated_bugs),
    }


@app.get(
    "/api/tasks/{task_id}/logs",
    tags=["2. 巡检任务生命周期调度"],
    summary="拉取任务控制台日志切片",
    description="获取指定任务最近在控制台输出的日志文本切片（默认最近 150 行）。",
)
def get_task_logs(
    task_id: str = FastPath(..., description="任务识别码"),
    tail: int = Query(default=150, ge=10, le=3000, description="读取最近日志行数"),
):

    logs = task_manager.get_logs(task_id, tail=tail)

    return {"task_id": task_id, "count": len(logs), "logs": logs}


@app.websocket("/ws/tasks/{task_id}/logs")
async def websocket_task_logs(websocket: WebSocket, task_id: str):
    """

    WebSocket 实时终端控制台日志推流频道

    前端连接后先接收最近 50 行历史日志，随后以长连接极低时延实时推送每一行子进程标准输出。

    """

    await websocket.accept()
    active_websockets.add(websocket)

    queue = task_manager.subscribe_logs(task_id)

    try:
        recent = task_manager.get_logs(task_id, tail=50)

        for line in recent:
            await websocket.send_text(line)

        while True:
            line = await queue.get()

            await websocket.send_text(line)

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass

    except Exception as e:
        logger.debug(f"[WS-Logs] 任务 [{task_id}] 推流通道安全关闭: {e}")

    finally:
        active_websockets.discard(websocket)
        task_manager.unsubscribe_logs(task_id, queue)


# =============================================================================

# 3. 缺陷管理与一键推单 API (Bug Management & ZenTao)

# =============================================================================


@app.get(
    "/api/bugs",
    response_model=List[BugResponse],
    tags=["3. 缺陷治理与禅道同步"],
    summary="多条件检索全局缺陷资产库",
    description="支持按状态（激活/已提单）、严重度（High/Medium/Low）、责任人（陈贻雄/梅本霞）以及模糊关键词全文检索系统缺陷。",
)
def list_bugs(
    status: Optional[str] = Query(
        default=None, description="缺陷状态过滤 (激活/已提单/误报/已解决)"
    ),
    assignee: Optional[str] = Query(
        default=None, description="责任人过滤 (如 陈贻雄 / 梅本霞)"
    ),
    severity: Optional[str] = Query(
        default=None, description="严重度过滤 (High/Medium/Low)"
    ),
    occurrences_range: Optional[str] = Query(
        default=None, description="频次区间过滤 (1-2 / 3-9 / 10+)"
    ),
    search: Optional[str] = Query(
        default=None, description="编号、标题、报错文本或禅道单号的全局模糊检索"
    ),
    sync: bool = Query(
        default=False,
        description="是否在查询前从磁盘执行增量热同步(默认False保障毫秒级极速响应)",
    ),
    limit: int = Query(default=200, ge=1, le=500, description="最大返回条数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
):

    if sync:
        from .sync_service import perform_hot_sync

        perform_hot_sync(db, force=False)

    q = db.query(BugRecord).order_by(BugRecord.last_seen.desc())

    if status:
        q = q.filter(BugRecord.status == status)

    if assignee:
        q = q.filter(BugRecord.assignee.like(f"%{assignee}%"))

    if severity:
        q = q.filter(BugRecord.severity == severity)

    if occurrences_range == "1-2":
        q = q.filter(BugRecord.occurrences >= 1, BugRecord.occurrences <= 2)

    elif occurrences_range == "3-9":
        q = q.filter(BugRecord.occurrences >= 3, BugRecord.occurrences <= 9)

    elif occurrences_range == "10+":
        q = q.filter(BugRecord.occurrences >= 10)

    if search:
        search_kw = search.strip()

        if search_kw:
            q = q.filter(
                (BugRecord.id.like(f"%{search_kw}%"))
                | (BugRecord.title.like(f"%{search_kw}%"))
                | (BugRecord.zentao_id.like(f"%{search_kw}%"))
                | (BugRecord.target_element.like(f"%{search_kw}%"))
                | (BugRecord.actual_error.like(f"%{search_kw}%"))
            )

    return q.offset(offset).limit(limit).all()


@app.put(
    "/api/bugs/{bug_id}",
    response_model=BugResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="编辑更新缺陷属性 (多端一致性同步写回)",
    description="支持在线修改缺陷标题、责任人、严重度、状态、关联禅道单号以及 AI 初诊排查指引，并自动同步到全局 JSON、单次运行报告 JSON 及数据库。",
)
def update_bug(
    bug_id: str = FastPath(..., description="待修改的缺陷编号，如 BUG-20261101-002"),
    payload: BugUpdate = ...,
    db: Session = Depends(get_db),
):

    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()

    if not bug:
        raise HTTPException(
            status_code=404, detail=f"未找到编号为 '{bug_id}' 的缺陷记录"
        )

    from utils.bug_updater import update_bug_record

    update_dict = {"bug_id": bug_id}

    if payload.title is not None:
        bug.title = payload.title

        update_dict["title"] = payload.title

    if payload.severity is not None:
        bug.severity = payload.severity

        update_dict["severity"] = payload.severity

    if payload.status is not None:
        bug.status = payload.status

        update_dict["status"] = payload.status

    if payload.assignee is not None:
        bug.assignee = payload.assignee

        update_dict["assignee"] = payload.assignee

    if payload.zentao_id is not None:
        bug.zentao_id = payload.zentao_id.strip() if payload.zentao_id else None

        update_dict["zentao_id"] = bug.zentao_id

    if payload.analysis_notes is not None:
        bug.analysis_notes = payload.analysis_notes

        update_dict["analysis_notes"] = payload.analysis_notes

    if payload.remark is not None:
        bug.remark = payload.remark

        update_dict["remark"] = payload.remark

    if payload.ui_path is not None:
        bug.ui_path = payload.ui_path

        update_dict["ui_path"] = payload.ui_path

    # 调用统一底座写回 JSON 库

    update_bug_record(update_dict)

    db.commit()

    db.refresh(bug)

    return bug


@app.post(
    "/api/bugs/{bug_id}/sync_zentao",
    tags=["3. 缺陷治理与禅道同步"],
    summary="在 Web 控制台一键将缺陷提交至禅道",
    description="自动解析缺陷详情、生成富文本案发排查说明，调用禅道 REST API 自动提交 Bug，并自动分流责任人（前端陈贻雄/后端梅本霞），回填禅道单号。",
)
def sync_bug_to_zentao(
    bug_id: str = FastPath(
        ..., description="待提交的全局缺陷编号，如 BUG-20261030-001"
    ),
    assignee: Optional[str] = Query(
        default=None,
        description="可选手动覆盖指派责任人姓名 (不填则根据 AI 分流自动指派)",
    ),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):

    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()

    if not bug:
        raise HTTPException(status_code=404, detail="Bug not found")

    try:
        from utils.zentao_sync import (
            ZenTaoClient,
            format_bug_details_html,
            find_bug_in_databases,
            resolve_bug_assignee,
            resolve_bug_app_key,
            APP_NAME_MAP,
        )

        from config.settings import settings

        zentao = ZenTaoClient()

        # 1. 动态智能判定该 Bug 所属矿山应用 (多级防呆)
        bug_dict_for_app = {
            "app": bug.task.app_name if (bug.task and bug.task.app_name) else None,
            "run_id": bug.task.run_id if bug.task else None,
            "ui_path": bug.ui_path,
            "screenshot": bug.screenshot_path,
            "crash_screenshot": bug.screenshot_path,
            "target_element": bug.target_element,
            "title": bug.title,
            "actual": bug.actual_error,
        }
        app_key = resolve_bug_app_key(bug_dict_for_app)

        # 2. 读取对应矿山应用专属的禅道产品/项目/迭代归属三元组
        app_mapping = settings.get_zentao_app_mapping(app_key)
        product_id = app_mapping["product_id"]
        project_id = app_mapping["project_id"]
        execution_id = app_mapping["execution_id"]
        app_chinese = APP_NAME_MAP.get(app_key, "寨湾矿山")

        target_assignee = assignee or bug.assignee or "陈贻雄"

        assignee_name, assignee_account, _ = resolve_bug_assignee(
            {"assignee": target_assignee}, override=target_assignee
        )

        raw_bug_dict = {
            "id": bug.id,
            "title": bug.title,
            "ui_path": bug.ui_path,
            "target_element": bug.target_element,
            "actual": bug.actual_error,
            "analysis_notes": bug.analysis_notes,
            "crash_screenshot": bug.screenshot_path,
            "occurrences": bug.occurrences,
        }

        # 预上传案发快照至禅道 (彻底避免富文本图片丢失)
        shot_path = bug.screenshot_path
        uploaded_info = None
        if shot_path:
            shot_file = Path(shot_path)
            if shot_file.exists():
                uploaded_info = zentao.upload_file(shot_file)

        uploaded_url = uploaded_info.get("url") if uploaded_info else None
        uploaded_file_ids = (
            [uploaded_info["id"]] if (uploaded_info and "id" in uploaded_info) else []
        )

        steps_html, _ = format_bug_details_html(
            bug=raw_bug_dict,
            app_key=app_key,
            assignee_name=assignee_name,
            assignee_account=assignee_account,
            uploaded_image_url=uploaded_url,
        )

        res = zentao.submit_bug(
            product_id=product_id,
            title=f"【AI自动化·{app_chinese}】[{bug.id}] {bug.title}",
            steps_html=steps_html,
            severity=3 if bug.severity == "High" else 2,
            assigned_to=assignee_account,
            project_id=project_id,
            execution_id=execution_id,
            files=uploaded_file_ids if uploaded_file_ids else None,
        )

        z_id = str(res.get("id"))

        # 更新本地数据库

        bug.zentao_id = z_id

        bug.status = "已提单"

        bug.assignee = assignee_name

        db.commit()

        # 同步回填本地 JSON 库

        from utils.zentao_sync import update_bug_records, rebuild_run_reports

        _, g_file, r_files = find_bug_in_databases(bug_id)
        # 禁用耗时的同步渲染离线 HTML 报告 (sync_reports=False)，实现 1 秒级极速响应返回
        update_bug_records(
            bug_id, z_id, g_file, r_files, assignee=assignee_name, sync_reports=False
        )

        # 异步后台任务：默默渲染历史报告与大盘，绝不卡死前端 Web 界面
        if background_tasks and r_files:
            background_tasks.add_task(rebuild_run_reports, r_files)

        return {
            "code": 200,
            "message": "禅道提交成功",
            "bug_id": bug.id,
            "zentao_id": z_id,
            "zentao_url": f"{zentao.url}/index.php?m=bug&f=view&bugID={z_id}",
        }

    except Exception as e:
        logger.error(f"同步缺陷 {bug_id} 到禅道异常: {e}")

        raise HTTPException(status_code=500, detail=f"提单失败: {e}")


# =============================================================================

# 4. 性能监控数据 API (Performance Metrics & WebRTC / UE Probes)

# =============================================================================


@app.get(
    "/api/metrics/live/snapshot",
    response_model=LivePerformanceSnapshotResponse,
    tags=["4. 多核全栈性能监控"],
    summary="即时采集当前大屏物理环境性能快照",
    description="无需启动任何测试任务，即时对本机运行的 UE5 引擎、Chromium CDP 协议端口以及 NVIDIA GPU 进行只读探针采样并返回即时切片。",
)
def get_live_performance_snapshot(
    app_name: str = Query(
        default="zhaiwan", description="矿山应用系统代号 (zhaiwan / liwutong)"
    ),
):

    snapshot = performance_monitor.collect_full_snapshot(app_name=app_name)

    return LivePerformanceSnapshotResponse(**snapshot)


@app.get(
    "/api/metrics/live/history",
    tags=["4. 多核全栈性能监控"],
    summary="获取指定矿山应用最近 24 小时内的环境实时心电图历史时序",
    description="支持指定矿山应用（如 tianrui / zhaiwan），返回过去 15 分钟 ~ 24 小时的高保真连续时序数据。进入页面时瞬间灌满 ECharts 图表，彻底告别从零开始。",
)
def get_ambient_metrics_history(
    app_name: str = Query(
        default="tianrui", description="矿山应用代码 (tianrui / zhaiwan / liwutong)"
    ),
    hours: float = Query(
        default=24.0, ge=0.1, le=48.0, description="回溯时长 (小时，默认24小时)"
    ),
    limit: int = Query(default=1000, ge=50, le=5000, description="最大返回点数"),
    downsample: bool = Query(default=True, description="是否等间距降采样"),
):

    return performance_monitor.get_ambient_history(
        app_name=app_name, hours=hours, limit=limit, downsample=downsample
    )


@app.get(
    "/api/metrics/live/apps_status",
    tags=["4. 多核全栈性能监控"],
    summary="获取所有矿山应用的实时运行与内存状态列表",
    description="返回各应用当前伴生 UE 是否在线、专用提交量(Commit)及物理内存，供前端展示状态微标。",
)
def get_all_apps_live_status():

    return performance_monitor.get_all_apps_live_status()


@app.get(
    "/api/metrics/{task_id}",
    response_model=List[PerformanceMetricResponse],
    tags=["4. 多核全栈性能监控"],
    summary="获取任务的时序性能指标数据列表 (支持自适应等间距智能降采样与全周期保真)",
    description="返回指定任务运行期间采集的所有性能时序打点。当点数超过 limit 时自动启用均匀等间距降采样算法，确保起点与终点 100% 完整覆盖，完美支撑数小时乃至通宵压测的全量 ECharts 渲染与 DataZoom 缩放。",
)
def get_task_metrics(
    task_id: str = FastPath(..., description="巡检任务全局标识码"),
    limit: int = Query(default=1000, ge=10, le=5000, description="最大返回时序点数量"),
    downsample: bool = Query(
        default=True,
        description="超出 limit 时是否进行自适应等间距降采样保留全周期跨度",
    ),
    db: Session = Depends(get_db),
):

    query = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.task_id == task_id)
        .order_by(PerformanceMetric.timestamp.asc())
    )

    total_count = query.count()

    # 若尚未入库，尝试从历史 reports/runs/**/memory_timeline.json 中自动回填历史数据

    if total_count == 0:
        task = db.query(TaskRun).filter(TaskRun.id == task_id).first()

        if task and task.run_dir:
            tl_path = (
                PROJECT_ROOT
                / "reports"
                / "runs"
                / task.run_dir
                / "screenshots"
                / "memory_timeline.json"
            )

            if tl_path.exists():
                try:
                    with open(tl_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    timeline = data.get("timeline", [])

                    new_records = []

                    for item in timeline:
                        ts = datetime.datetime.fromtimestamp(item.get("timestamp", 0))

                        pm = PerformanceMetric(
                            task_id=task_id,
                            timestamp=ts,
                            step_number=None,
                            page_scope=item.get("page_scope"),
                            dom_count=item.get("dom_nodes", 0),
                            listeners_count=item.get("js_event_listeners", 0),
                            js_heap_mb=item.get("js_heap_used_mb", 0.0),
                            js_heap_total_mb=item.get("js_heap_total_mb", 0.0),
                            echarts_instances=item.get("echarts_instances", 0),
                            canvas_count=item.get("canvas_count", 0),
                            video_instances=item.get("video_count", 0),
                        )

                        db.add(pm)

                        new_records.append(pm)

                    db.commit()

                    query = (
                        db.query(PerformanceMetric)
                        .filter(PerformanceMetric.task_id == task_id)
                        .order_by(PerformanceMetric.timestamp.asc())
                    )

                    total_count = len(new_records)

                except Exception as e:
                    logger.debug(f"回填历史 memory_timeline.json 异常: {e}")

    if total_count == 0:
        return []

    # 智能等间距降采样：如果数据点数量超过 limit，保留起点、终点和中间均匀分布的点，确保跨度 100% 完整

    if downsample and total_count > limit:
        all_records = query.all()

        step = (total_count - 1) / (limit - 1)

        sampled_indices = {int(round(i * step)) for i in range(limit)}

        sampled_indices.add(0)

        sampled_indices.add(total_count - 1)

        return [all_records[i] for i in sorted(sampled_indices) if i < total_count]

    return query.limit(limit).all()


@app.get(
    "/api/metrics/{task_id}/summary",
    response_model=PerformanceSummaryResponse,
    tags=["4. 多核全栈性能监控"],
    summary="聚合计算任务全生命周期性能峰值与健康预警",
    description="自动聚合 DOM 峰值、平均值、JSHeap 峰值、UE5 内存峰值与 WebRTC 最低谷底掉帧点，并输出智能性能告警建议（如 DOM 泄漏爆炸预警）。",
)
def get_task_metrics_summary(
    task_id: str = FastPath(..., description="巡检任务识别码"),
    db: Session = Depends(get_db),
):

    records = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.task_id == task_id)
        .order_by(PerformanceMetric.timestamp.asc())
        .all()
    )

    if not records:
        return PerformanceSummaryResponse(task_id=task_id, sample_count=0)

    count = len(records)

    doms = [r.dom_count for r in records if r.dom_count]

    listeners = [r.listeners_count for r in records if r.listeners_count]

    heaps = [r.js_heap_mb for r in records if r.js_heap_mb]

    fps_list = [r.webrtc_fps for r in records if r.webrtc_fps is not None]

    ue_cpus = [r.ue_cpu_percent for r in records if r.ue_cpu_percent is not None]

    ue_mems = [r.ue_memory_mb for r in records if r.ue_memory_mb is not None]

    ue_commits = [r.ue_commit_mb for r in records if r.ue_commit_mb is not None]

    host_commits = [
        r.host_commit_load_percent
        for r in records
        if r.host_commit_load_percent is not None
    ]

    chrome_cpus = [
        r.chrome_cpu_percent for r in records if r.chrome_cpu_percent is not None
    ]

    chrome_mems = [
        r.chrome_memory_mb for r in records if r.chrome_memory_mb is not None
    ]

    gpus = [r.gpu_usage_percent for r in records if r.gpu_usage_percent is not None]

    gpu_mems = [r.gpu_memory_mb for r in records if r.gpu_memory_mb is not None]

    alerts: List[str] = []

    peak_dom = max(doms) if doms else 0

    latest_dom = doms[-1] if doms else 0

    peak_listeners = max(listeners) if listeners else 0

    latest_listeners = listeners[-1] if listeners else 0

    peak_heap = max(heaps) if heaps else 0.0

    latest_heap = heaps[-1] if heaps else 0.0

    peak_ue_commit = max(ue_commits) if ue_commits else None

    peak_host_commit = max(host_commits) if host_commits else None

    if peak_dom > 50000:
        alerts.append(
            f"⚠️ DOM 节点数发生严重泄漏膨胀！峰值达到 {peak_dom} 个节点（健康阈值: <30,000）"
        )

    if peak_listeners > 10000:
        alerts.append(
            f"⚠️ JS 事件监听器累积过多！峰值达到 {peak_listeners} 个，可能未注销事件销毁钩子"
        )

    if peak_heap > 800.0:
        alerts.append(f"⚠️ Chromium V8 堆内存超标！峰值达到 {peak_heap} MB")

    if fps_list and min(fps_list) < 15.0:
        alerts.append(f"⚠️ WebRTC 像素流出现明显掉帧！最低帧率仅 {min(fps_list)} FPS")

    if peak_ue_commit and peak_ue_commit > 12288.0:
        alerts.append(
            f"⚠️ UE5 引擎专用提交量 (Commit) 严重膨胀！峰值达到 {round(peak_ue_commit / 1024, 2)} GB (健康阈值: 小于 12 GB)"
        )

    if peak_host_commit and peak_host_commit > 85.0:
        alerts.append(
            f"⚠️ 宿主机专用虚拟提交负荷过高！峰值达到 {peak_host_commit}% (OOM 崩溃风险预警)"
        )

    return PerformanceSummaryResponse(
        task_id=task_id,
        sample_count=count,
        peak_dom_count=peak_dom,
        avg_dom_count=round(sum(doms) / len(doms), 1) if doms else 0.0,
        latest_dom_count=latest_dom,
        peak_listeners_count=peak_listeners,
        latest_listeners_count=latest_listeners,
        peak_js_heap_mb=peak_heap,
        avg_js_heap_mb=round(sum(heaps) / len(heaps), 2) if heaps else 0.0,
        latest_js_heap_mb=latest_heap,
        avg_webrtc_fps=round(sum(fps_list) / len(fps_list), 1) if fps_list else None,
        min_webrtc_fps=min(fps_list) if fps_list else None,
        peak_chrome_cpu_percent=max(chrome_cpus) if chrome_cpus else None,
        peak_chrome_memory_mb=max(chrome_mems) if chrome_mems else None,
        peak_ue_cpu_percent=max(ue_cpus) if ue_cpus else None,
        avg_ue_cpu_percent=round(sum(ue_cpus) / len(ue_cpus), 1) if ue_cpus else None,
        peak_ue_memory_mb=max(ue_mems) if ue_mems else None,
        peak_ue_commit_mb=peak_ue_commit,
        peak_host_commit_load_percent=peak_host_commit,
        peak_gpu_usage_percent=max(gpus) if gpus else None,
        peak_gpu_memory_mb=max(gpu_mems) if gpu_mems else None,
        health_alerts=alerts,
    )


@app.websocket("/ws/tasks/{task_id}/metrics")
async def websocket_task_metrics(websocket: WebSocket, task_id: str):
    """

    WebSocket 实时时序性能推流频道

    专供前端 ECharts 动态折线大屏实时渲染，任务后台探针每完成一次 5 秒采样便自动向当前频道广播一条最新的指标 JSON。

    """

    await websocket.accept()
    active_websockets.add(websocket)

    queue = performance_monitor.subscribe_metrics(task_id)

    try:
        while True:
            metric_dict = await queue.get()

            await websocket.send_json(metric_dict)

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass

    except Exception as e:
        logger.debug(f"[WS-Metrics] 任务 [{task_id}] 性能推流通道安全关闭: {e}")

    finally:
        active_websockets.discard(websocket)
        performance_monitor.unsubscribe_metrics(task_id, queue)


platform_subscribers: set = set()


@app.post(
    "/api/sync/hot",
    tags=["1. 平台全局总览与控制"],
    summary="强制从磁盘热同步最新运行批次与缺陷",
    description="主动扫描 reports/runs/ 运行目录和 artifacts/bugs/ 缺陷库，增量写入数据库并实时广播更新。",
)
async def trigger_hot_sync_endpoint(db: Session = Depends(get_db)):

    from .sync_service import perform_hot_sync

    res = perform_hot_sync(db, force=True)

    msg_str = json.dumps({"event": "data_refresh", "data": res}, ensure_ascii=False)
    dead = set()
    for ws in list(platform_subscribers):
        try:
            await ws.send_text(msg_str)
        except Exception:
            dead.add(ws)
    for ws in dead:
        platform_subscribers.discard(ws)

    return res


@app.websocket("/ws/platform")
async def websocket_platform(websocket: WebSocket):
    """全平台全局多端实时数据同步 WebSocket 通道"""

    await websocket.accept()
    active_websockets.add(websocket)

    platform_subscribers.add(websocket)

    try:
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                await websocket.send_text("pong")

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass

    finally:
        active_websockets.discard(websocket)
        platform_subscribers.discard(websocket)


@app.post(
    "/api/metrics/cleanup",
    tags=["4. 多核全栈性能监控"],
    summary="手动触发滚动清理历史过期性能打点数据",
    description="支持指定保留天数（默认 7 天），滚动清理超期性能打点，释放存储空间保障极速读写。",
)
def trigger_metrics_cleanup(
    retention_days: int = Query(
        default=7, ge=1, le=90, description="性能时序数据保留天数"
    ),
):

    deleted = performance_monitor.cleanup_expired_metrics(retention_days=retention_days)

    return {
        "code": 200,
        "message": f"成功清理 {deleted} 条超过 {retention_days} 天的历史性能时序数据",
        "deleted_count": deleted,
        "retention_days": retention_days,
    }


# =============================================================================

# 5. 产物与已测接口目录 API (Task Artifacts & API Registry)

# =============================================================================


@app.get(
    "/api/tasks/{task_id}/apis",
    tags=["2. 巡检任务生命周期调度"],
    summary="获取巡检任务捕获解析的业务 API 接口清单",
    description="自动解析底层网络监听池与单次报告中的 `api_registry.json`，将前端交互触发的全部后端接口分类呈现为 OpenAPI / Postman 风格契约清单。",
)
def get_task_apis(
    task_id: str = FastPath(..., description="巡检任务标识码"),
    db: Session = Depends(get_db),
):

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


@app.get(
    "/api/tasks/{task_id}/env_info",
    tags=["2. 巡检任务生命周期调度"],
    summary="获取指定任务的案发/运行时环境基线快照 (env_info.json)",
    description="解析并返回该次巡检启动时的 2D 前端包版本路径、UE5 孪生工程版本路径、N+1 业务接口与推流网关配置。",
)
def get_task_env_info(
    task_id: str = FastPath(..., description="巡检任务标识码"),
    db: Session = Depends(get_db),
):
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    run_dir = task.run_dir or ""
    if run_dir.startswith("reports/runs/") or run_dir.startswith("reports\\runs\\"):
        run_dir = run_dir.replace("reports/runs/", "").replace("reports\\runs\\", "")

    if not run_dir:
        return {
            "task_id": task_id,
            "exists": False,
            "env_info": None,
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
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取环境基线快照失败: {e}")


@app.get(
    "/api/cases",
    tags=["5. 用例资产管理"],
    summary="获取全量测试用例资产列表 (分手工编写与 AI 自动生成两类)",
    description="扫描并汇总 test_cases/ 下的手工编写自然语言用例，以及 reports/runs/**/generated_cases 下 AI 探索沉淀的回归用例。",
)
def get_test_cases():
    import yaml
    from datetime import datetime

    manual_cases = []
    test_cases_dir = PROJECT_ROOT / "test_cases"
    if test_cases_dir.exists():
        for p in sorted(test_cases_dir.glob("*.yaml")):
            if p.is_file() and p.stat().st_size > 0:
                steps_count = 0
                title = p.stem
                desc = ""
                try:
                    content = yaml.safe_load(p.read_text(encoding="utf-8"))
                    if isinstance(content, list):
                        steps_count = len(content)
                    elif isinstance(content, dict):
                        steps = content.get("steps", [])
                        steps_count = len(steps) if isinstance(steps, list) else 0
                        title = content.get("name") or content.get("title") or title
                        desc = content.get("description", "")
                except Exception:
                    pass

                stat = p.stat()
                mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                rel_path = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
                manual_cases.append({
                    "id": p.stem,
                    "name": title,
                    "filename": p.name,
                    "path": rel_path,
                    "steps_count": steps_count,
                    "size_kb": round(stat.st_size / 1024, 2),
                    "modified_at": mtime_str,
                    "description": desc,
                    "type": "manual"
                })

    auto_cases = []
    runs_dir = PROJECT_ROOT / "reports" / "runs"
    if runs_dir.exists():
        for p in sorted(runs_dir.glob("**/generated_cases/*.yaml"), reverse=True):
            if p.is_file() and p.stat().st_size > 0:
                steps_count = 0
                title = p.stem
                try:
                    content = yaml.safe_load(p.read_text(encoding="utf-8"))
                    if isinstance(content, list):
                        steps_count = len(content)
                    elif isinstance(content, dict):
                        steps = content.get("steps", [])
                        steps_count = len(steps) if isinstance(steps, list) else 0
                        title = content.get("name") or title
                except Exception:
                    pass

                stat = p.stat()
                ctime_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                rel_path = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")

                parts = p.parts
                app_name = "zhaiwan"
                run_id = ""
                try:
                    idx = parts.index("runs")
                    if len(parts) > idx + 2:
                        app_name = parts[idx + 1]
                        run_id = parts[idx + 2]
                except Exception:
                    pass

                auto_cases.append({
                    "id": p.stem,
                    "name": title,
                    "filename": p.name,
                    "path": rel_path,
                    "app_name": app_name,
                    "run_id": run_id,
                    "steps_count": steps_count,
                    "size_kb": round(stat.st_size / 1024, 2),
                    "created_at": ctime_str,
                    "type": "auto"
                })

    return {
        "manual_cases": manual_cases,
        "auto_cases": auto_cases,
        "total_manual": len(manual_cases),
        "total_auto": len(auto_cases)
    }


@app.get(
    "/api/cases/content",
    tags=["5. 用例资产管理"],
    summary="读取指定用例的 YAML 内容",
)
def get_case_content(path: str = Query(..., description="用例相对工程根目录的路径")):
    safe_path = (PROJECT_ROOT / path).resolve()
    if not str(safe_path).startswith(str(PROJECT_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="非法路径访问拒绝")

    if not safe_path.exists() or not safe_path.is_file():
        raise HTTPException(status_code=404, detail="用例文件不存在")

    if safe_path.suffix.lower() not in [".yaml", ".yml"]:
        raise HTTPException(status_code=400, detail="仅支持预览 YAML 用例文件")

    try:
        content = safe_path.read_text(encoding="utf-8")
        return {
            "path": path,
            "filename": safe_path.name,
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}")


@app.post(
    "/api/cases/promote",
    tags=["5. 用例资产管理"],
    summary="将 AI 自动生成的用例固化转存为手工常态化回归用例",
)
def promote_auto_case(data: Dict[str, Any] = Body(...)):
    path = data.get("path")
    target_name = data.get("target_name")
    if not path:
        raise HTTPException(status_code=400, detail="缺少源路径 path")

    src_path = (PROJECT_ROOT / path).resolve()
    if not str(src_path).startswith(str(PROJECT_ROOT.resolve())) or not src_path.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")

    target_filename = target_name or src_path.name
    if not target_filename.endswith(".yaml") and not target_filename.endswith(".yml"):
        target_filename += ".yaml"

    dest_dir = PROJECT_ROOT / "test_cases"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / target_filename

    import shutil
    try:
        shutil.copyfile(src_path, dest_path)
        return {
            "code": 200,
            "message": f"成功固化为常态用例: test_cases/{target_filename}",
            "dest_path": f"test_cases/{target_filename}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复制失败: {e}")
