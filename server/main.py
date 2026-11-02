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
    WebSocket,
    WebSocketDisconnect
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .models import TaskRun, BugRecord, PerformanceMetric
from .schemas import (
    TaskCreate,
    TaskResponse,
    BugResponse,
    PerformanceMetricResponse,
    ConfigOptionsResponse
)
from .task_manager import task_manager

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("server.api")

app = FastAPI(
    title="Electron AI Vision Testing Platform API",
    description="端到端多模态自动化巡检与性能监控中枢平台",
    version="1.0.0"
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
    logger.info("⚡ 正在初始化数据库引擎与表结构...")
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
                        screenshot_path=rb.get("crash_screenshot") or rb.get("screenshot"),
                        occurrences=rb.get("occurrences", 1)
                    )
                    db.add(b_rec)
            db.commit()
            logger.info("✨ 已将本地已有全局缺陷库同步入库！")
        db.close()
    except Exception as e:
        logger.debug(f"冷启动同步历史缺陷异常 (可忽略): {e}")


# 静态文件挂载：直接访问测试产物报告与截图
REPORTS_DIR = PROJECT_ROOT / "reports"
if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


# =============================================================================
# 1. 基础配置与选项 API (免敲命令，选项化核心)
# =============================================================================

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Electron AI Vision Platform",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }


@app.get("/api/config/options", response_model=ConfigOptionsResponse)
def get_config_options():
    """提供前端一键选择的应用、模式与提示词模板库"""
    apps = [
        {"key": "zhaiwan", "name": "寨湾矿山 (Zhaiwan)", "desc": "包含中央 UE5 像素流三维矿山与两侧 2D 业务看板"},
        {"key": "liwutong", "name": "李屋塘矿山 (Liwutong)", "desc": "数字孪生采矿与智能选矿平台"}
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
    
    # 检查禅道是否具备配置
    zentao_ok = bool(os.getenv("ZENTAO_PASSWORD"))
    return ConfigOptionsResponse(
        apps=apps,
        modes=modes,
        prompt_templates=templates,
        zentao_configured=zentao_ok
    )


# =============================================================================
# 2. 任务调度管理 API (任务创建、启动、终止、日志与状态)
# =============================================================================

@app.post("/api/tasks", response_model=TaskResponse)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    """根据前端表单选项创建巡检任务"""
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


@app.get("/api/tasks", response_model=List[TaskResponse])
def list_tasks(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """查询任务列表"""
    q = db.query(TaskRun).order_by(TaskRun.start_time.desc())
    if status:
        q = q.filter(TaskRun.status == status)
    return q.offset(offset).limit(limit).all()


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    """获取单任务详情与最新 KPI"""
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/tasks/{task_id}/start")
def start_task_execution(task_id: str, db: Session = Depends(get_db)):
    """一键触发启动指定任务"""
    task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "running":
        return {"code": 200, "message": "任务已经在运行中", "task_id": task_id, "pid": task.pid}

    success = task_manager.start_task(task_id)
    if not success:
        raise HTTPException(status_code=500, detail="拉起任务进程失败，请检查运行环境或日志")
    return {"code": 200, "message": "任务启动成功", "task_id": task_id}


@app.post("/api/tasks/{task_id}/stop")
def stop_task_execution(task_id: str):
    """一键安全终止任务执行"""
    stopped = task_manager.stop_task(task_id)
    if not stopped:
        return {"code": 200, "message": "任务未在运行或已处于终态", "task_id": task_id}
    return {"code": 200, "message": "任务已安全终止并归档", "task_id": task_id}


@app.get("/api/tasks/{task_id}/logs")
def get_task_logs(task_id: str, tail: int = 150):
    """获取任务最近的控制台日志"""
    logs = task_manager.get_logs(task_id, tail=tail)
    return {"task_id": task_id, "count": len(logs), "logs": logs}


@app.websocket("/ws/tasks/{task_id}/logs")
async def websocket_task_logs(websocket: WebSocket, task_id: str):
    """WebSocket 实时日志推流频道"""
    await websocket.accept()
    queue = task_manager.subscribe_logs(task_id)
    try:
        # 先将已有的最后 50 行日志推过去建立初始态
        recent = task_manager.get_logs(task_id, tail=50)
        for line in recent:
            await websocket.send_text(line)

        # 持续推送实时日志流
        while True:
            line = await queue.get()
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        task_manager.unsubscribe_logs(task_id, queue)


# =============================================================================
# 3. 缺陷管理与一键推单 API (Bug Management & ZenTao)
# =============================================================================

@app.get("/api/bugs", response_model=List[BugResponse])
def list_bugs(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """多维度检索系统缺陷"""
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


@app.post("/api/bugs/{bug_id}/sync_zentao")
def sync_bug_to_zentao(bug_id: str, assignee: Optional[str] = None, db: Session = Depends(get_db)):
    """在 Web 控制台一键将缺陷提交至禅道"""
    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if not bug:
        raise HTTPException(status_code=404, detail="Bug not found")

    try:
        from utils.zentao_sync import ZenTaoClient, format_bug_details_html, find_bug_in_databases, resolve_bug_assignee
        from config.settings import settings

        zentao = ZenTaoClient()
        product_id = getattr(settings, "zentao", {}).get("default_product_id", 10) or 10

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
            app_key="zhaiwan",
            assignee_name=assignee_name,
            assignee_account=assignee_account
        )

        res = zentao.submit_bug(
            product_id=product_id,
            title=f"【AI自动化·寨湾矿山】[{bug.id}] {bug.title}",
            steps_html=steps_html,
            severity=3 if bug.severity == "High" else 2,
            assigned_to=assignee_account
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
# 4. 性能监控数据 API (Performance Metrics)
# =============================================================================

@app.get("/api/metrics/{task_id}", response_model=List[PerformanceMetricResponse])
def get_task_metrics(task_id: str, db: Session = Depends(get_db)):
    """获取任务的时序性能指标列表 (供 ECharts 绘制 DOM / JSHeap / UE CPU 曲线)"""
    return db.query(PerformanceMetric).filter(
        PerformanceMetric.task_id == task_id
    ).order_by(PerformanceMetric.timestamp.asc()).all()
