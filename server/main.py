import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Query,
    Path as FastPath,
    WebSocket,
    WebSocketDisconnect
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .models import TaskRun, BugRecord, PerformanceMetric, PresetTaskRecord
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
    AppControlResponse
)
from .task_manager import task_manager
from .performance_monitor import performance_monitor

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
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
    redoc_url="/redoc"
)

# 允许跨域请求 (为前后端分离与大屏仪表盘服务)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """服务冷启动生命周期钩子：冷启动自动物理快照、初始化数据库结构并自动同步已有全局缺陷库"""
    from .database import backup_database
    backup_database(max_backups=5)

    logger.info("⚡ 正在初始化数据库引擎与表结构 (含自动平滑迁移)...")
    init_db()
    
    # 同步已有缺陷库到数据库 (冷启动初始化)
    try:
        from .database import SessionLocal
        db = SessionLocal()
        global_bugs_file = PROJECT_ROOT / "artifacts" / "bugs" / "global_bugs_zhaiwan.json"
        if global_bugs_file.exists():
            with open(global_bugs_file, "r", encoding="utf-8") as f:
                raw_bugs = json.load(f)
            for rb in raw_bugs:
                b_id = rb.get("id")
                if not b_id:
                    continue
                exist = db.query(BugRecord).filter(BugRecord.id == b_id).first()
                if not exist:
                    b_rec = BugRecord(
                        id=b_id,
                        title=rb.get("title", ""),
                        severity=rb.get("severity", "Medium"),
                        status=rb.get("status", "激活"),
                        assignee=rb.get("assignee", "陈贻雄"),
                        zentao_id=str(rb.get("zentao_id")) if rb.get("zentao_id") else None,
                        ui_path=rb.get("ui_path"),
                        target_element=rb.get("target_element"),
                        actual_error=rb.get("details", {}).get("actual") if isinstance(rb.get("details"), dict) else rb.get("actual"),
                        analysis_notes=rb.get("analysis_notes"),
                        remark=rb.get("remark"),
                        screenshot_path=rb.get("crash_screenshot") or rb.get("screenshot"),
                        occurrences=rb.get("occurrences", 1)
                    )
                    db.add(b_rec)
                elif rb.get("remark") and not exist.remark:
                    exist.remark = rb.get("remark")
            db.commit()
            logger.info("✨ 已将本地已有全局缺陷库同步入库！")
        db.close()
    except Exception as e:
        logger.debug(f"冷启动同步历史缺陷异常 (可忽略): {e}")

    # 4. 自动滚动清理过期历史性能数据 (默认保留 7 天，防止 SQLite 数据库膨胀)
    try:
        deleted = performance_monitor.cleanup_expired_metrics(retention_days=7)
        if deleted > 0:
            logger.info(f"🧹 冷启动数据治理：自动清理了 {deleted} 条超过 7 天的历史性能打点")
    except Exception as e:
        logger.debug(f"滚动清理性能时序异常 (可忽略): {e}")

    # 5. 自动增量同步本地历史测试运行目录到任务产物库
    try:
        from utils.paths import get_all_run_folders, RUNS_DIR
        from utils.report_generator import ReportGenerator

        db = SessionLocal()
        existing_run_dirs = {t.run_dir for t in db.query(TaskRun).all() if t.run_dir}
        for f in get_all_run_folders():
            try:
                rel_p = f.relative_to(RUNS_DIR).as_posix()
            except Exception:
                rel_p = f.name
            if rel_p in existing_run_dirs:
                continue

            try:
                generator = ReportGenerator(f)
                data = generator.parse_run_data()
                run_id = data.get("run_id") or f.name
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

                task_id = f"task_{run_id}"
                if not db.query(TaskRun).filter(TaskRun.id == task_id).first():
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
                    existing_run_dirs.add(rel_p)
            except Exception as fe:
                logger.debug(f"解析运行目录 {f.name} 跳过: {fe}")
        db.commit()
        db.close()
        logger.info("📁 已自动同步本地历史巡检运行目录入库！")
    except Exception as te:
        logger.debug(f"冷启动增量同步历史运行异常 (可忽略): {te}")


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


# =============================================================================
# 0. 缺陷统一治理与同步 API (单点真理源：同步全局库、运行目录与持久化数据库)
# =============================================================================

@app.post(
    "/api/update_bug_status",
    tags=["3. 缺陷治理与禅道同步"],
    summary="大盘门户统一接口：更新缺陷生命周期状态",
    description="统一更新缺陷状态，同步更新全局缺陷库、运行目录与平台数据库。"
)
@app.post(
    "/api/update_bug_detail",
    tags=["3. 缺陷治理与禅道同步"],
    summary="大盘门户统一接口：更新缺陷详细字段与排查说明",
    description="统一更新责任人、严重度、排查批注或回填禅道单号，同步更新全局缺陷库、运行目录与平台数据库。"
)
async def update_bug_compatible_api(data: dict):
    from utils.bug_updater import update_bug_record
    result = update_bug_record(data)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "更新缺陷记录失败"))
    return result


# =============================================================================
# 1. 基础配置与选项 API (免敲命令，选项化核心)
# =============================================================================

@app.get(
    "/api/health",
    tags=["1. 平台基础与选项"],
    summary="平台健康心跳检查",
    description="检测后端平台服务核心服务、数据库会话与运行时间戳是否处于正常就绪状态。"
)
def health_check():
    return {
        "status": "healthy",
        "service": "Electron AI Vision Platform",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }


@app.get(
    "/api/config/options",
    response_model=ConfigOptionsResponse,
    tags=["1. 平台基础与选项"],
    summary="获取前端表单可选项与提示词模板库",
    description="为前端工作台提供一键选择的矿山应用、测试模式列表、开箱即用的高阶探索 Prompt 模板库以及禅道鉴权配置状态。"
)
def get_config_options():
    apps = [
        {"key": "zhaiwan", "name": "寨湾矿山 (Zhaiwan)", "desc": "包含中央 UE5 像素流三维矿山与两侧 2D 业务看板"},
        {"key": "liwutong", "name": "里伍铜矿山 (Liwutong)", "desc": "数字孪生采矿与智能选矿平台"},
        {"key": "tianrui", "name": "四川天瑞矿山 (Tianrui)", "desc": "四川天瑞大屏数字孪生系统"}
    ]
    modes = [
        {"key": "explore", "name": "自主探索模式 (Explorer)", "desc": "Planner-Worker 双核黑客模式，自主规划链路挖掘深层 Crash"},
        {"key": "smoke", "name": "二级菜单全量冒烟 (Smoke Tour)", "desc": "极速单次遍历全部 33 个业务二级菜单，验证两级跳转"},
        {"key": "case", "name": "YAML 确定性用例回放", "desc": "精确重现已通过静态合规检验的 YAML 业务流程"},
        {"key": "all", "name": "批量回归全套用例", "desc": "遍历运行 test_cases/ 目录下全部 YAML 用例"}
    ]
    templates = [
        {
            "title": "全栈地毯式扫荡 (推荐)",
            "prompt": "开启全栈地毯式扫荡：不局限于任何单一模块，请依次悬停并点击顶部导航栏，深度遍历所有的顶级菜单与二级业务菜单。在每个页面内，务必全量探测核心业务组件（包含所有的数据指标卡片、Echarts图表时间维度切换、表格翻页与明细操作、以及各类深层弹窗和抽屉）。遇到折叠面板必须全部展开，遇到Tab必须逐一切换。请像QA黑客一样发散思维，重点寻找白屏、数据不一致、或者深层状态丢失的隐蔽 Bug。不要在单一页面陷入死循环死磕，确保整个应用 100% 页面全覆盖度！"
        },
        {
            "title": "三维数字孪生视界抗压攻坚",
            "prompt": "全面探测中央 3D 矿山数字孪生模型健康度：重点进入三维视口页面，执行轨道视角全向旋转 (rotate_3d) 与镜头深度推进拉远 (zoom)，并发起三维视口晃动抗压测试 (canvas_stress_drag)，深度排查 UE5 像素流是否有花屏、断流、模型破面或 WebGL 上下文丢失！"
        },
        {
            "title": "未测盲区定向突击",
            "prompt": "全面攻克未探索盲区：重点深入遍历【设备管理】与【安全管理】下的各个子模块，优先测试各页面中的 2D 指标看板、折线图日/月/年维度切换、列表明细与操作弹窗，深入挖掘未知Bug与接口异常，避开已探索完备的模块。"
        }
    ]
    
    # 检查禅道是否具备配置与动态基地址
    from config.settings import settings
    zentao_ok = bool(os.getenv("ZENTAO_PASSWORD") or getattr(settings, "zentao_password", None))
    zentao_url = getattr(settings, "zentao_url", "http://192.140.163.129:8080")
    if zentao_url:
        zentao_url = zentao_url.rstrip("/")

    return ConfigOptionsResponse(
        apps=apps,
        modes=modes,
        prompt_templates=templates,
        zentao_configured=zentao_ok,
        zentao_base_url=zentao_url,
        report_hub_url="/report-hub"
    )


# =============================================================================
# 2. 预设巡检任务库 API (Preset Tasks)
# =============================================================================

DEFAULT_PRESET_TASKS = [
    {
        "id": "preset_zhaiwan_explore_full",
        "title": "【寨湾】全栈地毯式扫荡巡检",
        "app_name": "zhaiwan",
        "mode": "explore",
        "badge": "推荐",
        "max_steps": 2000,
        "max_times": 600,
        "reset_memory": True,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "开启全栈地毯式扫荡：不局限于任何单一模块，请依次悬停并点击顶部导航栏，深度遍历所有的顶级菜单与二级业务菜单。在每个页面内，务必全量探测核心业务组件（包含所有的数据指标卡片、Echarts图表时间维度切换、表格翻页与明细操作、以及各类深层弹窗和抽屉）。遇到折叠面板必须全部展开，遇到Tab必须逐一切换。请像QA黑客一样发散思维，重点寻找白屏、数据不一致、或者深层状态丢失的隐蔽 Bug。不要在单一页面陷入死循环死磕，确保整个应用 100% 页面全覆盖度！",
        "description": "全量覆盖 33 个业务二级菜单，深度遍历 2D 业务面板组件、Tab、弹窗抽屉与图表维度切换。"
    },
    {
        "id": "preset_zhaiwan_3d_stress",
        "title": "【寨湾】中央 3D 视界与像素流抗压专项",
        "app_name": "zhaiwan",
        "mode": "explore",
        "badge": "抗压",
        "max_steps": 1000,
        "max_times": 300,
        "reset_memory": True,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "全面探测中央 3D 矿山数字孪生模型健康度：重点进入三维视口页面，执行轨道视角全向旋转 (rotate_3d) 与镜头深度推进拉远 (zoom)，并发起三维视口晃动抗压测试 (canvas_stress_drag)，深度排查 UE5 像素流是否有花屏、断流、模型破面或 WebGL 上下文丢失！",
        "description": "重点进入中央三维视口执行轨道旋转、镜头推拉与高频甩动，深度压测 UE5 伴生进程与 WebRTC 掉帧风险。"
    },
    {
        "id": "preset_zhaiwan_smoke_tour",
        "title": "【寨湾】二级菜单极速全量冒烟体检",
        "app_name": "zhaiwan",
        "mode": "smoke",
        "badge": "冒烟",
        "max_steps": 1500,
        "max_times": 150,
        "reset_memory": True,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "二级菜单全量冒烟体检：极速单次遍历全部 33 个业务二级菜单，验证两级跳转与基础展示健康度",
        "description": "轻量级高频冒烟，单次快速校验全部 33 个菜单路由跳转、页面框架是否白屏以及核心接口健康度。"
    },
    {
        "id": "preset_zhaiwan_home_yaml",
        "title": "【寨湾】首页业务深度确定性回归 (YAML)",
        "app_name": "zhaiwan",
        "mode": "case",
        "badge": "回归",
        "max_steps": 500,
        "max_times": 200,
        "reset_memory": False,
        "ignore_errors": True,
        "case_path": "test_cases/test_home_mine_intro.yaml",
        "macro_objective": "精确重现已通过静态合规检验的 YAML 业务流程：首页矿山简介深度巡检",
        "description": "精确执行已固化的标准自动化回归脚本，100% 确定性复现关键业务链路并核对 API。"
    },
    {
        "id": "preset_liwutong_explore",
        "title": "【里伍铜】数字孪生采矿与选矿自主探索",
        "app_name": "liwutong",
        "mode": "explore",
        "badge": "探索",
        "max_steps": 150,
        "max_times": 45,
        "reset_memory": False,
        "ignore_errors": True,
        "case_path": None,
        "macro_objective": "全面扫荡李屋塘矿山各业务模块：深入探测选矿看板、采场可视化与设备一张图，挖掘未覆盖盲区中的数据不一致与前端崩溃 Bug！",
        "description": "李屋塘矿山全业务板块探测，深入验证选矿流程、指标卡片与报警处置流程。"
    }
]


@app.get(
    "/api/tasks/presets",
    response_model=List[PresetTaskResponse],
    tags=["1. 平台基础与选项"],
    summary="获取预置的标准巡检任务库 (系统预设 + 用户自定义预设)",
    description="提供系统默认验证的常用巡检任务模板，以及用户在界面中自行保存/编辑的个性化预设方案。"
)
def get_preset_tasks(db: Session = Depends(get_db)):
    # 1. 确保系统预设已装载到数据库中并与代码保持实时同步
    for p in DEFAULT_PRESET_TASKS:
        exist = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == p["id"]).first()
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
                is_system=True
            )
            db.add(rec)
        elif exist.is_system:
            # 允许用户在源码 DEFAULT_PRESET_TASKS 中直接修改，并自动热同步至数据库
            exist.title = p["title"]
            exist.app_name = p["app_name"]
            exist.mode = p["mode"]
            exist.badge = p["badge"]
            exist.description = p.get("description")
            exist.macro_objective = p["macro_objective"]
            exist.max_steps = p["max_steps"]
            exist.max_times = p["max_times"]
            exist.reset_memory = p.get("reset_memory", False)
            exist.ignore_errors = p.get("ignore_errors", True)
            exist.case_path = p.get("case_path")
    db.commit()

    # 2. 查询全部预设（系统预设优先，用户自定义按更新时间倒序）
    return db.query(PresetTaskRecord).order_by(
        PresetTaskRecord.is_system.desc(),
        PresetTaskRecord.updated_at.desc()
    ).all()


@app.post(
    "/api/tasks/presets",
    response_model=PresetTaskResponse,
    tags=["1. 平台基础与选项"],
    summary="保存或更新预设巡检任务模板",
    description="支持将前端表单微调后的配置持久化保存为预设，方便日后一键拉起或再次微调；若传入已有 id 则覆盖更新。"
)
def save_or_update_preset_task(
    payload: PresetTaskCreate,
    db: Session = Depends(get_db)
):
    now = datetime.datetime.utcnow()
    preset_id = payload.id
    if not preset_id:
        preset_id = f"preset_user_{now.strftime('%Y%m%d_%H%M%S')}"

    existing = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    if existing:
        existing.title = payload.title
        existing.app_name = payload.app_name
        existing.mode = payload.mode
        existing.badge = payload.badge or "自定义"
        existing.description = payload.description or f"用户自定义任务: {payload.mode}模式 / {payload.max_steps}步"
        existing.macro_objective = payload.macro_objective
        existing.max_steps = payload.max_steps
        existing.max_times = payload.max_times
        existing.reset_memory = payload.reset_memory
        existing.ignore_errors = payload.ignore_errors
        existing.case_path = payload.case_path
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
            description=payload.description or f"用户自定义任务: {payload.mode}模式 / {payload.max_steps}步",
            macro_objective=payload.macro_objective,
            max_steps=payload.max_steps,
            max_times=payload.max_times,
            reset_memory=payload.reset_memory,
            ignore_errors=payload.ignore_errors,
            case_path=payload.case_path,
            is_system=False,
            created_at=now,
            updated_at=now
        )
        db.add(new_preset)
        db.commit()
        db.refresh(new_preset)
        return new_preset


@app.delete(
    "/api/tasks/presets/{preset_id}",
    tags=["1. 平台基础与选项"],
    summary="删除自定义预设任务模板",
    description="删除用户创建的个性化预设模板 (系统内置预设禁止删除)。"
)
def delete_preset_task(
    preset_id: str = FastPath(..., description="预设模板 ID"),
    db: Session = Depends(get_db)
):
    existing = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="预设未找到")
    if existing.is_system:
        raise HTTPException(status_code=403, detail="系统内置预设禁止删除，可载入后另存为新预设")

    db.delete(existing)
    db.commit()
    return {"code": 200, "message": "预设删除成功", "preset_id": preset_id}


@app.post(
    "/api/tasks/presets/{preset_id}/launch",
    response_model=TaskResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="按预设模板一键快速拉起巡检任务",
    description="根据预设模板 ID 直接创建巡检任务并在后台立即异步拉起，无需手动填写表单。"
)
def launch_preset_task(
    preset_id: str = FastPath(..., description="预设任务模板 ID"),
    db: Session = Depends(get_db)
):
    target_preset = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    if not target_preset:
        target_preset = next((p for p in DEFAULT_PRESET_TASKS if p["id"] == preset_id), None)
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

    now = datetime.datetime.utcnow()
    task_id = f"task_{now.strftime('%Y%m%d_%H%M%S')}"

    task = TaskRun(
        id=task_id,
        name=f"{p_title} ({now.strftime('%H:%M:%S')})",
        app_name=p_app,
        mode=p_mode,
        status="pending",
        macro_objective=p_obj,
        max_steps=p_steps,
        max_times=p_times,
        reset_memory=p_reset,
        ignore_errors=p_ignore,
        case_path=p_case,
        explore_context=f"docs/explore_rules_{p_app}.md",
        start_time=now
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
    description="接收前端选项表单，持久化生成新的巡检任务定义记录并分配唯一 `task_id`，初始状态为 `pending`。"
)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
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
        start_time=now
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
    description="支持按状态（`running`、`completed` 等）筛选，返回任务的覆盖率、执行步数与缺陷汇总等 KPI 指标。"
)
def list_tasks(
    status: Optional[str] = Query(default=None, description="任务状态过滤 (pending/running/completed/stopped/failed)"),
    limit: int = Query(default=50, ge=1, le=200, description="单页最大拉取记录条数"),
    offset: int = Query(default=0, ge=0, description="分页偏移量"),
    db: Session = Depends(get_db)
):
    q = db.query(TaskRun).order_by(TaskRun.start_time.desc())
    if status:
        q = q.filter(TaskRun.status == status)
    return q.offset(offset).limit(limit).all()


@app.get(
    "/api/tasks/{task_id}",
    response_model=TaskResponse,
    tags=["2. 巡检任务生命周期调度"],
    summary="获取指定任务详情",
    description="获取指定任务当前的运行进展、子进程 PID、结束时间、产物报告链接以及最终 KPI。"
)
def get_task(
    task_id: str = FastPath(..., description="任务唯一标识码，如 task_20261102_153022"),
    db: Session = Depends(get_db)
):
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post(
    "/api/tasks/{task_id}/start",
    tags=["2. 巡检任务生命周期调度"],
    summary="一键触发启动指定巡检任务",
    description="从数据库装载配置，组装参数拉起后台 Python 子进程，并自动挂载启动伴生性能采样守护线程与日志缓冲监听。"
)
def start_task_execution(
    task_id: str = FastPath(..., description="待启动的任务全局识别码"),
    db: Session = Depends(get_db)
):
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "running":
        return {"code": 200, "message": "任务已经在运行中", "task_id": task_id, "pid": task.pid}

    success = task_manager.start_task(task_id)
    if not success:
        raise HTTPException(status_code=500, detail="拉起任务进程失败，请检查运行环境或日志")
    return {"code": 200, "message": "任务启动成功", "task_id": task_id}


@app.post(
    "/api/tasks/{task_id}/stop",
    tags=["2. 巡检任务生命周期调度"],
    summary="一键优雅终止正在运行的任务",
    description="向目标 Electron 应用广播原生 WM_CLOSE 退出信号，并递归优雅终止子进程树，同时停止性能采集线程并回填终态产物。"
)
def stop_task_execution(
    task_id: str = FastPath(..., description="待停止的任务全局识别码")
):
    stopped = task_manager.stop_task(task_id)
    if not stopped:
        return {"code": 200, "message": "任务未在运行或已处于终态", "task_id": task_id}
    return {"code": 200, "message": "任务已安全终止并归档", "task_id": task_id}


@app.get(
    "/api/tasks/{task_id}/logs",
    tags=["2. 巡检任务生命周期调度"],
    summary="拉取任务控制台日志切片",
    description="获取指定任务最近在控制台输出的日志文本切片（默认最近 150 行）。"
)
def get_task_logs(
    task_id: str = FastPath(..., description="任务识别码"),
    tail: int = Query(default=150, ge=10, le=3000, description="读取最近日志行数")
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
        task_manager.unsubscribe_logs(task_id, queue)


# =============================================================================
# 3. 缺陷管理与一键推单 API (Bug Management & ZenTao)
# =============================================================================

@app.get(
    "/api/bugs",
    response_model=List[BugResponse],
    tags=["3. 缺陷治理与禅道同步"],
    summary="多条件检索全局缺陷资产库",
    description="支持按状态（激活/已提单）、严重度（High/Medium/Low）、责任人（陈贻雄/梅本霞）以及模糊关键词全文检索系统缺陷。"
)
def list_bugs(
    status: Optional[str] = Query(default=None, description="缺陷状态过滤 (激活/已提单/误报/已关闭)"),
    assignee: Optional[str] = Query(default=None, description="责任人过滤 (如 陈贻雄 / 梅本霞)"),
    severity: Optional[str] = Query(default=None, description="严重度过滤 (High/Medium/Low)"),
    search: Optional[str] = Query(default=None, description="标题、报错文本或编号的全局模糊检索"),
    limit: int = Query(default=100, ge=1, le=500, description="最大返回条数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db)
):
    q = db.query(BugRecord).order_by(BugRecord.last_seen.desc())
    if status:
        q = q.filter(BugRecord.status == status)
    if assignee:
        q = q.filter(BugRecord.assignee.like(f"%{assignee}%"))
    if severity:
        q = q.filter(BugRecord.severity == severity)
    if search:
        q = q.filter(
            (BugRecord.title.like(f"%{search}%")) |
            (BugRecord.actual_error.like(f"%{search}%")) |
            (BugRecord.id.like(f"%{search}%"))
        )
    return q.offset(offset).limit(limit).all()


@app.put(
    "/api/bugs/{bug_id}",
    response_model=BugResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="编辑更新缺陷属性 (多端一致性同步写回)",
    description="支持在线修改缺陷标题、责任人、严重度、状态、关联禅道单号以及 AI 初诊排查指引，并自动同步到全局 JSON、单次运行报告 JSON 及数据库。"
)
def update_bug(
    bug_id: str = FastPath(..., description="待修改的缺陷编号，如 BUG-20261101-002"),
    payload: BugUpdate = ...,
    db: Session = Depends(get_db)
):
    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if not bug:
        raise HTTPException(status_code=404, detail=f"未找到编号为 '{bug_id}' 的缺陷记录")

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
    description="自动解析缺陷详情、生成富文本案发排查说明，调用禅道 REST API 自动提交 Bug，并自动分流责任人（前端陈贻雄/后端梅本霞），回填禅道单号。"
)
def sync_bug_to_zentao(
    bug_id: str = FastPath(..., description="待提交的全局缺陷编号，如 BUG-20261030-001"),
    assignee: Optional[str] = Query(default=None, description="可选手动覆盖指派责任人姓名 (不填则根据 AI 分流自动指派)"),
    db: Session = Depends(get_db)
):
    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if not bug:
        raise HTTPException(status_code=404, detail="Bug not found")

    try:
        from utils.zentao_sync import ZenTaoClient, format_bug_details_html, find_bug_in_databases, resolve_bug_assignee
        from config.settings import settings

        zentao = ZenTaoClient()

        # 1. 动态智能判定该 Bug 所属矿山应用
        app_key = "zhaiwan"
        if bug.task and bug.task.app_name:
            app_key = bug.task.app_name
        elif bug.screenshot_path and "liwutong" in bug.screenshot_path.lower():
            app_key = "liwutong"
        elif bug.ui_path and ("里伍" in bug.ui_path or "liwutong" in bug.ui_path.lower()):
            app_key = "liwutong"

        # 2. 读取对应矿山应用专属的禅道产品/项目/迭代归属三元组
        app_mapping = settings.get_zentao_app_mapping(app_key)
        product_id = app_mapping["product_id"]
        project_id = app_mapping["project_id"]
        execution_id = app_mapping["execution_id"]
        app_chinese = "里伍铜矿" if app_key == "liwutong" else "寨湾矿山"

        target_assignee = assignee or bug.assignee or "陈贻雄"
        assignee_name, assignee_account, _ = resolve_bug_assignee({"assignee": target_assignee}, override=target_assignee)

        raw_bug_dict = {
            "id": bug.id,
            "title": bug.title,
            "ui_path": bug.ui_path,
            "target_element": bug.target_element,
            "actual": bug.actual_error,
            "analysis_notes": bug.analysis_notes,
            "crash_screenshot": bug.screenshot_path,
            "occurrences": bug.occurrences
        }

        steps_html, _ = format_bug_details_html(
            bug=raw_bug_dict,
            app_key=app_key,
            assignee_name=assignee_name,
            assignee_account=assignee_account
        )

        res = zentao.submit_bug(
            product_id=product_id,
            title=f"【AI自动化·{app_chinese}】[{bug.id}] {bug.title}",
            steps_html=steps_html,
            severity=3 if bug.severity == "High" else 2,
            assigned_to=assignee_account,
            project_id=project_id,
            execution_id=execution_id
        )
        z_id = str(res.get("id"))

        # 更新本地数据库
        bug.zentao_id = z_id
        bug.status = "已提单"
        bug.assignee = assignee_name
        db.commit()

        # 同步回填本地 JSON 库
        from utils.zentao_sync import update_bug_records
        _, g_file, r_files = find_bug_in_databases(bug_id)
        update_bug_records(bug_id, z_id, g_file, r_files, assignee=assignee_name)

        return {
            "code": 200,
            "message": "禅道提交成功",
            "bug_id": bug.id,
            "zentao_id": z_id,
            "zentao_url": f"{zentao.url}/index.php?m=bug&f=view&bugID={z_id}"
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
    description="无需启动任何测试任务，即时对本机运行的 UE5 引擎、Chromium CDP 协议端口以及 NVIDIA GPU 进行只读探针采样并返回即时切片。"
)
def get_live_performance_snapshot(
    app_name: str = Query(default="zhaiwan", description="矿山应用系统代号 (zhaiwan / liwutong)")
):
    snapshot = performance_monitor.collect_full_snapshot(app_name=app_name)
    return LivePerformanceSnapshotResponse(**snapshot)


@app.get(
    "/api/metrics/{task_id}",
    response_model=List[PerformanceMetricResponse],
    tags=["4. 多核全栈性能监控"],
    summary="获取任务的时序性能指标数据列表 (支持自适应等间距智能降采样与全周期保真)",
    description="返回指定任务运行期间采集的所有性能时序打点。当点数超过 limit 时自动启用均匀等间距降采样算法，确保起点与终点 100% 完整覆盖，完美支撑数小时乃至通宵压测的全量 ECharts 渲染与 DataZoom 缩放。"
)
def get_task_metrics(
    task_id: str = FastPath(..., description="巡检任务全局标识码"),
    limit: int = Query(default=1000, ge=10, le=5000, description="最大返回时序点数量"),
    downsample: bool = Query(default=True, description="超出 limit 时是否进行自适应等间距降采样保留全周期跨度"),
    db: Session = Depends(get_db)
):
    query = db.query(PerformanceMetric).filter(
        PerformanceMetric.task_id == task_id
    ).order_by(PerformanceMetric.timestamp.asc())

    total_count = query.count()

    # 若尚未入库，尝试从历史 reports/runs/**/memory_timeline.json 中自动回填历史数据
    if total_count == 0:
        task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
        if task and task.run_dir:
            tl_path = PROJECT_ROOT / "reports" / "runs" / task.run_dir / "screenshots" / "memory_timeline.json"
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
                            video_instances=item.get("video_count", 0)
                        )
                        db.add(pm)
                        new_records.append(pm)
                    db.commit()
                    query = db.query(PerformanceMetric).filter(
                        PerformanceMetric.task_id == task_id
                    ).order_by(PerformanceMetric.timestamp.asc())
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
    description="自动聚合 DOM 峰值、平均值、JSHeap 峰值、UE5 内存峰值与 WebRTC 最低谷底掉帧点，并输出智能性能告警建议（如 DOM 泄漏爆炸预警）。"
)
def get_task_metrics_summary(
    task_id: str = FastPath(..., description="巡检任务识别码"),
    db: Session = Depends(get_db)
):
    records = db.query(PerformanceMetric).filter(
        PerformanceMetric.task_id == task_id
    ).order_by(PerformanceMetric.timestamp.asc()).all()

    if not records:
        return PerformanceSummaryResponse(task_id=task_id, sample_count=0)

    count = len(records)
    doms = [r.dom_count for r in records if r.dom_count]
    listeners = [r.listeners_count for r in records if r.listeners_count]
    heaps = [r.js_heap_mb for r in records if r.js_heap_mb]
    fps_list = [r.webrtc_fps for r in records if r.webrtc_fps is not None]
    ue_cpus = [r.ue_cpu_percent for r in records if r.ue_cpu_percent is not None]
    ue_mems = [r.ue_memory_mb for r in records if r.ue_memory_mb is not None]
    chrome_cpus = [r.chrome_cpu_percent for r in records if r.chrome_cpu_percent is not None]
    chrome_mems = [r.chrome_memory_mb for r in records if r.chrome_memory_mb is not None]
    gpus = [r.gpu_usage_percent for r in records if r.gpu_usage_percent is not None]
    gpu_mems = [r.gpu_memory_mb for r in records if r.gpu_memory_mb is not None]

    alerts: List[str] = []
    peak_dom = max(doms) if doms else 0
    latest_dom = doms[-1] if doms else 0
    peak_listeners = max(listeners) if listeners else 0
    latest_listeners = listeners[-1] if listeners else 0
    peak_heap = max(heaps) if heaps else 0.0
    latest_heap = heaps[-1] if heaps else 0.0

    if peak_dom > 50000:
        alerts.append(f"⚠️ DOM 节点数发生严重泄漏膨胀！峰值达到 {peak_dom} 个节点（健康阈值: <30,000）")
    if peak_listeners > 10000:
        alerts.append(f"⚠️ JS 事件监听器累积过多！峰值达到 {peak_listeners} 个，可能未注销事件销毁钩子")
    if peak_heap > 800.0:
        alerts.append(f"⚠️ Chromium V8 堆内存超标！峰值达到 {peak_heap} MB")
    if fps_list and min(fps_list) < 15.0:
        alerts.append(f"⚠️ WebRTC 像素流出现明显掉帧！最低帧率仅 {min(fps_list)} FPS")

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
        peak_gpu_usage_percent=max(gpus) if gpus else None,
        peak_gpu_memory_mb=max(gpu_mems) if gpu_mems else None,
        health_alerts=alerts
    )


@app.websocket("/ws/tasks/{task_id}/metrics")
async def websocket_task_metrics(websocket: WebSocket, task_id: str):
    """
    WebSocket 实时时序性能推流频道
    专供前端 ECharts 动态折线大屏实时渲染，任务后台探针每完成一次 5 秒采样便自动向当前频道广播一条最新的指标 JSON。
    """
    await websocket.accept()
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
        performance_monitor.unsubscribe_metrics(task_id, queue)


@app.post(
    "/api/metrics/cleanup",
    tags=["4. 多核全栈性能监控"],
    summary="手动触发滚动清理历史过期性能打点数据",
    description="支持指定保留天数（默认 7 天），滚动清理超期性能打点，释放存储空间保障极速读写。"
)
def trigger_metrics_cleanup(
    retention_days: int = Query(default=7, ge=1, le=90, description="性能时序数据保留天数")
):
    deleted = performance_monitor.cleanup_expired_metrics(retention_days=retention_days)
    return {
        "code": 200,
        "message": f"成功清理 {deleted} 条超过 {retention_days} 天的历史性能时序数据",
        "deleted_count": deleted,
        "retention_days": retention_days
    }


# =============================================================================
# 5. 产物与已测接口目录 API (Task Artifacts & API Registry)
# =============================================================================

@app.get(
    "/api/tasks/{task_id}/apis",
    tags=["2. 巡检任务生命周期调度"],
    summary="获取巡检任务捕获解析的业务 API 接口清单",
    description="自动解析底层网络监听池与单次报告中的 `api_registry.json`，将前端交互触发的全部后端接口分类呈现为 OpenAPI / Postman 风格契约清单。"
)
def get_task_apis(
    task_id: str = FastPath(..., description="巡检任务标识码"),
    db: Session = Depends(get_db)
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
        return {"task_id": task_id, "summary": {}, "page_scopes": {}, "global_flat_apis": []}

    api_path = PROJECT_ROOT / "reports" / "runs" / run_dir / "screenshots" / "api_registry.json"
    if not api_path.exists():
        api_path = PROJECT_ROOT / "reports" / "runs" / run_dir / "api_registry.json"

    if not api_path.exists():
        return {"task_id": task_id, "summary": {}, "page_scopes": {}, "global_flat_apis": []}

    try:
        with open(api_path, "r", encoding="utf-8") as f:
            api_data = json.load(f)
        return {
            "task_id": task_id,
            "run_dir": run_dir,
            "summary": api_data.get("summary", {}),
            "page_scopes": api_data.get("page_scopes", {}),
            "global_flat_apis": api_data.get("global_flat_apis", api_data.get("summary", {}).get("endpoints", []))
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析已测接口清单失败: {e}")


# ==============================================================================
# 5. 客户端生命周期与纯手工测试模式 (Manual Test & Client Control)
# ==============================================================================

@app.post(
    "/api/apps/{app_name}/launch",
    response_model=AppControlResponse,
    tags=["5. 客户端生命周期与手工测试"],
    summary="一键拉起客户端 (纯手工测试模式)",
    description="以指定应用的 CDP 调试端口拉起 Electron 客户端与伴生 UE5 进程。不启动任何自动化测试脚本，供人工自由交互，大盘实时采集性能。"
)
def launch_app_client(app_name: str):
    from config.settings import settings
    from utils.electron_launcher import ElectronLauncher
    cfg = settings.get_app_config(app_name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"未找到应用配置: {app_name}")
    
    exe_path = cfg.get("exe_path", "")
    port = int(cfg.get("debug_port", 9223))
    if not exe_path or not os.path.exists(exe_path):
        raise HTTPException(status_code=400, detail=f"客户端可执行文件不存在: '{exe_path}'")
    
    try:
        launcher = ElectronLauncher(exe_path=exe_path, port=port)
        if launcher.is_cdp_alive():
            pid = launcher.get_electron_pid()
            return AppControlResponse(
                status="success",
                message=f"客户端已在运行中 (CDP端口: {port})，当前可直接纯手工交互！",
                app_name=app_name,
                debug_port=port,
                pid=pid
            )
        
        # 异步线程拉起，避免阻塞 HTTP 响应
        def _launch_worker():
            try:
                launcher.start_app()
            except Exception as err:
                logger.error(f"拉起客户端异常: {err}")

        th = threading.Thread(target=_launch_worker, daemon=True)
        th.start()
        # 缓冲 1.5 秒给进程创建时间
        time.sleep(1.5)
        pid = launcher.get_electron_pid()

        return AppControlResponse(
            status="success",
            message=f"正在以调试模式拉起 {app_name} 客户端 (CDP端口: {port})，大盘已开启实时监控，请直接纯手工操作！",
            app_name=app_name,
            debug_port=port,
            pid=pid
        )
    except Exception as e:
        logger.error(f"拉起客户端失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"拉起客户端失败: {e}")


@app.post(
    "/api/apps/{app_name}/close",
    response_model=AppControlResponse,
    tags=["5. 客户端生命周期与手工测试"],
    summary="一键关闭客户端及其伴生进程",
    description="安全关闭指定应用的 Electron 客户端及其伴生 UE 进程，释放显存与端口资源。"
)
def close_app_client(app_name: str):
    import subprocess
    from config.settings import settings
    cfg = settings.get_app_config(app_name)
    exe_path = cfg.get("exe_path", "") if cfg else ""
    ue_process_name = cfg.get("ue_process_name", "") if cfg else ""
    
    closed_list = []
    if exe_path:
        exe_name = os.path.basename(exe_path)
        subprocess.run(["taskkill", "/F", "/IM", exe_name, "/T"], capture_output=True)
        closed_list.append(exe_name)
    if ue_process_name:
        subprocess.run(["taskkill", "/F", "/IM", ue_process_name, "/T"], capture_output=True)
        closed_list.append(ue_process_name)
        
    return AppControlResponse(
        status="success",
        message=f"已安全关闭 {app_name} 客户端及相关伴生进程 ({', '.join(closed_list) if closed_list else '无'})",
        app_name=app_name
    )


@app.get(
    "/api/apps/{app_name}/status",
    tags=["5. 客户端生命周期与手工测试"],
    summary="获取客户端当前运行与探针在线状态"
)
def get_app_status(app_name: str):
    import psutil
    from config.settings import settings
    from utils.electron_launcher import ElectronLauncher
    cfg = settings.get_app_config(app_name)
    port = int(cfg.get("debug_port", 9223)) if cfg else 9223
    exe_path = cfg.get("exe_path", "") if cfg else ""
    ue_process_name = cfg.get("ue_process_name", "") if cfg else ""
    
    launcher = ElectronLauncher(exe_path=exe_path, port=port)
    cdp_alive = launcher.is_cdp_alive()
    launcher_running = bool(launcher.get_electron_pid()) if exe_path else False
    
    ue_running = False
    if ue_process_name:
        target = ue_process_name.lower().replace(".exe", "")
        for p in psutil.process_iter(['name']):
            try:
                pname = (p.info.get('name') or "").lower()
                if target in pname:
                    ue_running = True
                    break
            except Exception:
                pass
                
    return {
        "app_name": app_name,
        "debug_port": port,
        "cdp_alive": cdp_alive,
        "launcher_running": launcher_running,
        "ue_running": ue_running
    }
