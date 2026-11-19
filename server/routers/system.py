"""
平台基础配置、健康检查与静态报告门户重定向
"""

import datetime
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ConfigOptionsResponse, HealthCheckResponse, HotSyncResponse
from .websockets import platform_subscribers

CURRENT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CURRENT_DIR.parent

WEB_DIR = PROJECT_ROOT / "web"
_DIST_DIR = WEB_DIR / "platform" / "dist"
STATIC_DIR = _DIST_DIR if _DIST_DIR.exists() else (WEB_DIR / "platform" if (WEB_DIR / "platform").exists() else CURRENT_DIR / "static")
REPORTS_DIR = PROJECT_ROOT / "reports"

logger = logging.getLogger("server.system")
router = APIRouter()

@router.get("/report-hub", include_in_schema=False)
@router.get("/reports-hub", include_in_schema=False)
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


@router.get("/", include_in_schema=False)
def serve_index():
    """Web 控制台首页面入口 (强制不缓存 HTML，确保更新后即刻生效)"""

    index_file = STATIC_DIR / "index.html"

    if index_file.exists():
        resp = FileResponse(str(index_file))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    return {"message": "Vision Platform API Server Running"}


@router.get("/favicon.ico", include_in_schema=False)
def serve_favicon():
    """网站专属图标 (Favicon)"""
    icon_file = STATIC_DIR / "favicon.svg"
    if icon_file.exists():
        return FileResponse(str(icon_file), media_type="image/svg+xml")
    return Response(status_code=204)



@router.get(
    "/api/health",
    response_model=HealthCheckResponse,
    tags=["1. 平台基础与选项"],
    summary="平台健康心跳检查",
    description="检测后端平台服务核心服务、数据库会话与运行时间戳是否处于正常就绪状态。",
)
def health_check():
    """
    检测后端平台服务健康状态与当前 UTC 时间戳。

    Returns:
        HealthCheckResponse: 包含 healthy 状态与 ISO 8601 时间戳
    """
    return {
        "status": "healthy",
        "service": "Electron AI Vision Platform",
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
    }


def _mask_secret(value: str) -> str:
    """对敏感凭据做安全脱敏，绝不向前端下发明文密钥或密码"""
    if not value:
        return ""
    s = str(value).strip()
    if len(s) <= 6:
        return "***"
    return f"{s[:3]}****{s[-3:]}"


def _builtin_apps_catalog():
    return [
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


def _builtin_modes_catalog():
    return [
        {
            "key": "explore",
            "name": "自主探索模式 (Explorer)",
            "desc": "多模态大模型动态驱动，自主规划链路与挖掘未知深层 Crash",
        },
        {
            "key": "smoke",
            "name": "全量冒烟巡检 (Smoke Tour)",
            "desc": "自动按序地毯式遍历全系统二级菜单，执行无声崩溃、接口通信与视觉呈现三阶门禁体检",
        },
        {
            "key": "case",
            "name": "确定性用例回放 (YAML Case)",
            "desc": "精确重现已通过静态合规检验的标准自然语言回归流程",
        },
    ]


def _builtin_prompt_templates():
    return [
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


@router.get(
    "/api/config/options",
    response_model=ConfigOptionsResponse,
    tags=["1. 平台基础与选项"],
    summary="获取前端表单可选项与提示词模板库",
    description="为前端工作台提供一键选择的矿山应用、测试模式列表、开箱即用的高阶探索 Prompt 模板库以及禅道鉴权配置状态。",
)
def get_config_options():
    apps = _builtin_apps_catalog()
    modes = _builtin_modes_catalog()

    yaml_cases = [{"name": "运行全量用例 (批量回归)", "path": ""}]
    test_cases_dir = Path("test_cases")
    if test_cases_dir.exists():
        for p in sorted(test_cases_dir.glob("*.yaml")):
            if p.is_file() and p.stat().st_size > 0:
                yaml_cases.append({
                    "name": p.name,
                    "path": str(p).replace("\\", "/")
                })

    templates = _builtin_prompt_templates()

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


@router.get(
    "/api/system/config-overview",
    tags=["1. 平台基础与选项"],
    summary="获取系统生效配置只读总览",
    description="汇总返回当前平台从 .env、config.yaml、settings.py 及代码内置字典加载的全部生效配置（敏感凭据已脱敏），仅作只读透明化展示。",
)
def get_system_config_overview():
    from config.settings import settings

    env_exists = (PROJECT_ROOT / ".env").exists()
    yaml_exists = (PROJECT_ROOT / "config.yaml").exists()

    builtin_map = {a["key"]: a for a in _builtin_apps_catalog()}
    yaml_apps = getattr(settings, "apps", {}) or {}
    merged_keys = list(dict.fromkeys([*builtin_map.keys(), *yaml_apps.keys()]))

    apps_detail = []
    for k in merged_keys:
        b = builtin_map.get(k, {})
        c = yaml_apps.get(k, {}) if isinstance(yaml_apps.get(k), dict) else {}
        vp = c.get("viewport") or {}
        apps_detail.append({
            "key": k,
            "name": b.get("name") or c.get("name") or k,
            "desc": b.get("desc") or c.get("desc") or "",
            "is_active": k == getattr(settings, "active_app", ""),
            "in_yaml": k in yaml_apps,
            "in_builtin": k in builtin_map,
            "exe_path": c.get("exe_path", ""),
            "debug_port": c.get("debug_port", 9222),
            "ue_process_name": c.get("ue_process_name", f"{k}.exe"),
            "expected_page_url": c.get("expected_page_url", "main.html"),
            "expected_page_title": c.get("expected_page_title", "主界面"),
            "startup_timeout": c.get("startup_timeout", 40.0),
            "start_delay": c.get("start_delay", 15.0),
            "no_proxy": c.get("no_proxy", ""),
            "rules_file": c.get("rules_file", f"docs/explore_rules_{k}.md"),
            "viewport": {
                "width": vp.get("width", getattr(settings, "default_width", 2560)),
                "height": vp.get("height", getattr(settings, "default_height", 1440)),
                "device_pixel_ratio": vp.get("device_pixel_ratio", getattr(settings, "device_pixel_ratio", 1.5)),
            },
            "env_check": c.get("env_check", {}),
            "zentao_product_id": c.get("zentao_product_id"),
            "zentao_project_id": c.get("zentao_project_id"),
            "zentao_execution_id": c.get("zentao_execution_id"),
        })

    api_key = getattr(settings, "llm_api_key", "") or ""
    zentao_pwd = os.getenv("ZENTAO_PASSWORD") or getattr(settings, "zentao_password", "") or ""
    test_pwd = getattr(settings, "test_password", "") or ""

    return {
        "active_app": getattr(settings, "active_app", "default"),
        "config_sources": {
            "env_file_exists": env_exists,
            "config_yaml_exists": yaml_exists,
            "settings_module": "config/settings.py",
            "builtin_catalog": "server/routers/system.py",
        },
        "apps": apps_detail,
        "llm": {
            "provider": getattr(settings, "llm_provider", ""),
            "base_url": getattr(settings, "llm_base_url", ""),
            "model": getattr(settings, "llm_model", ""),
            "bug_analysis_model": getattr(settings, "llm_bug_analysis_model", ""),
            "api_key_configured": bool(api_key),
            "api_key_masked": _mask_secret(api_key),
            "timeout": getattr(settings, "llm_timeout", 60.0),
            "temperature": getattr(settings, "llm_temperature", 0.1),
            "max_tokens": getattr(settings, "llm_max_tokens", 1024),
            "max_retries": getattr(settings, "llm_max_retries", 3),
            "step_timeout": getattr(settings, "step_timeout", 90.0),
            "max_planner_failures": getattr(settings, "max_planner_failures", 8),
            "oom_kill_enabled": getattr(settings, "oom_kill_enabled", False),
        },
        "zentao": {
            "url": (getattr(settings, "zentao_url", "") or "").rstrip("/"),
            "account": getattr(settings, "zentao_account", ""),
            "password_configured": bool(zentao_pwd),
            "default_product_id": getattr(settings, "zentao_default_product_id", 11),
            "default_project_id": getattr(settings, "zentao_default_project_id", 26),
            "default_execution_id": getattr(settings, "zentao_default_execution_id", 30),
        },
        "runtime": {
            "headless": getattr(settings, "headless", False),
            "test_username_configured": bool(getattr(settings, "test_username", "")),
            "test_username": getattr(settings, "test_username", ""),
            "test_password_configured": bool(test_pwd),
            "log_level": getattr(settings, "log_level", "INFO"),
            "log_to_console": getattr(settings, "log_to_console", True),
            "log_to_file": getattr(settings, "log_to_file", True),
            "log_file_path": getattr(settings, "log_file_path", ""),
            "screenshot_on_failure": getattr(settings, "screenshot_on_failure", True),
        },
        "modes": _builtin_modes_catalog(),
        "prompt_templates": _builtin_prompt_templates(),
    }




@router.post(
    "/api/sync/hot",
    response_model=HotSyncResponse,
    tags=["1. 平台全局总览与控制"],
    summary="强制从磁盘热同步最新运行批次与缺陷",
    description="主动扫描 reports/runs/ 运行目录和 artifacts/bugs/ 缺陷库，增量写入数据库并实时广播更新。",
)
async def trigger_hot_sync_endpoint(db: Session = Depends(get_db)):
    """
    强制执行磁盘物理运行目录与缺陷库到数据库的增量热同步。

    Args:
        db: 数据库会话

    Returns:
        HotSyncResponse: 同步增量结果统计 (包含新增任务数、新增 Bug 数与耗时)
    """
    from ..sync_service import perform_hot_sync

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


@router.get(
    "/api/system/storage",
    tags=["1. 平台全局总览与控制"],
    summary="获取工程产物磁盘占用大盘",
    description="扫描 artifacts/ 与 reports/runs/ 磁盘占用分布，实时返回过程截图、Bug 现场证据、检查点与日志的字节数与人类可读格式。",
)
def get_system_storage():
    from utils.cleaner import get_disk_usage_summary

    return get_disk_usage_summary()


@router.post(
    "/api/system/cleanup",
    tags=["1. 平台全局总览与控制"],
    summary="安全执行产物存储瘦身",
    description="安全清理或原地 WebP 压缩指定天数前的临时过程截图（默认自动跳过仍含「激活」Bug 的未处理报告，100% 保留上下文与 Bug 现场）。",
)
def trigger_system_cleanup(
    retain_days: int = 7,
    compress_webp: bool = False,
    protect_active_bugs: bool = True,
    clean_resolved_bug_shots: bool = False,
    dry_run: bool = False,
):
    from utils.cleaner import clean_temp_screenshots, get_disk_usage_summary

    result = clean_temp_screenshots(
        retain_days=retain_days,
        dry_run=dry_run,
        compress_webp=compress_webp,
        protect_active_bugs=protect_active_bugs,
        clean_resolved_bug_shots=clean_resolved_bug_shots,
    )
    result["storage_after"] = get_disk_usage_summary()
    return result


