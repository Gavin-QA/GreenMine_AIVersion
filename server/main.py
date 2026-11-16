"""
=============================================================================
Electron Vision AI - 智能巡检与多核性能中枢平台服务入口 (Main Application)
=============================================================================
FastAPI 主应用实例初始化、生命周期管理、中间件配置、静态资源托管与模块化路由挂载。
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .performance_monitor import performance_monitor
from .routers import (
    system_router,
    presets_router,
    queue_router,
    tasks_router,
    bugs_router,
    performance_router,
    cases_router,
    websockets_router,
    active_websockets,
    platform_subscribers,
)

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
    {
        "name": "5. 用例资产管理",
        "description": "测试用例资产列表、YAML 源码读取与 AI 逆向探索用例固化晋升",
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
        with performance_monitor._lock:
            for task_id, stop_event in list(performance_monitor._stop_events.items()):
                stop_event.set()
    except Exception:
        pass
    logger.info("✨ [Shutdown] 所有长连接与守护线程释放完毕，服务退出/重载就绪！")


# 静态文件挂载：优先挂载 Vite 构建产物 web/platform/dist/，兼容旧版目录回退
WEB_DIR = PROJECT_ROOT / "web"
_DIST_DIR = WEB_DIR / "platform" / "dist"
STATIC_DIR = _DIST_DIR if _DIST_DIR.exists() else (WEB_DIR / "platform" if (WEB_DIR / "platform").exists() else CURRENT_DIR / "static")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

REPORTS_DIR = PROJECT_ROOT / "reports"
if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
if ARTIFACTS_DIR.exists():
    app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")

# =============================================================================
# 模块化路由注册 (保持严格路由匹配优先权)
# =============================================================================
app.include_router(system_router)
app.include_router(presets_router)
app.include_router(queue_router)
app.include_router(tasks_router)
app.include_router(bugs_router)
app.include_router(performance_router)
app.include_router(cases_router)
app.include_router(websockets_router)
