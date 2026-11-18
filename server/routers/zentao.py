"""
禅道提单预览与动态元数据级联路由 (ZenTao Preview & Dynamic Metadata Router)
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FastPath, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BugRecord
from ..schemas import (
    ZentaoBuildOption,
    ZentaoCascadedMetadataResponse,
    ZentaoOptionItem,
    ZentaoPreviewDefaults,
    ZentaoPreviewOptions,
    ZentaoPreviewResponse,
    ZentaoUserOption,
)

logger = logging.getLogger(__name__)
router = APIRouter()

ZENTAO_BUG_TYPES: List[Dict[str, str]] = [
    {"id": "codeerror", "name": "代码错误"},
    {"id": "interface", "name": "界面优化"},
    {"id": "config", "name": "配置相关"},
    {"id": "install", "name": "安装部署"},
    {"id": "security", "name": "安全相关"},
    {"id": "performance", "name": "性能问题"},
    {"id": "standard", "name": "标准规范"},
    {"id": "automation", "name": "测试脚本"},
    {"id": "others", "name": "其他"},
]


def _format_local_screenshot_url(raw_path: Optional[str]) -> Optional[str]:
    if not raw_path:
        return None
    normalized = str(raw_path).replace("\\", "/")
    for marker in ("/reports/", "/artifacts/"):
        idx = normalized.find(marker)
        if idx != -1:
            return normalized[idx:]
    p = Path(raw_path)
    if p.exists():
        parts = p.as_posix()
        for marker in ("/reports/", "/artifacts/"):
            idx = parts.find(marker)
            if idx != -1:
                return parts[idx:]
    return None


def _build_option_list(raw_items: List[Dict[str, Any]]) -> List[ZentaoOptionItem]:
    items: List[ZentaoOptionItem] = []
    for it in raw_items or []:
        item_id = it.get("id")
        name = it.get("name") or it.get("title") or str(item_id or "")
        if item_id is not None:
            items.append(ZentaoOptionItem(id=item_id, name=str(name)))
    return items


def _build_module_list(raw_modules: List[Dict[str, Any]]) -> List[ZentaoOptionItem]:
    items: List[ZentaoOptionItem] = [ZentaoOptionItem(id=0, name="/")]
    for m in raw_modules or []:
        mid = m.get("id")
        name = m.get("name")
        if mid is not None and name:
            items.append(ZentaoOptionItem(id=int(mid), name=f"/{name}"))
    return items


def _format_build_options(raw_builds: List[Dict[str, Any]]) -> List[ZentaoBuildOption]:
    options: List[ZentaoBuildOption] = []
    for b in raw_builds or []:
        bid = str(b.get("id") or "")
        name = str(b.get("name") or bid)
        lower_name = name.lower()
        tag = "web" if "web" in lower_name else ("ue" if "ue" in lower_name else "")
        options.append(
            ZentaoBuildOption(
                id=bid,
                name=name,
                product=b.get("product"),
                execution=b.get("execution"),
                date=b.get("date"),
                tag=tag,
            )
        )
    options.append(ZentaoBuildOption(id="trunk", name="主干 (trunk)", tag="trunk"))
    return options


def _fetch_zentao_metadata_bundle(
    zentao: Any,
    project_id: int,
    product_id: int,
    include_globals: bool = True,
) -> Dict[str, Any]:
    """并发拉取禅道动态字典，减少等待耗时"""
    result: Dict[str, Any] = {
        "products": [],
        "projects": [],
        "executions": [],
        "modules": [],
        "builds": [],
        "users": [],
        "errors": [],
    }

    def _safe_call(key: str, fn, *args):
        try:
            return key, fn(*args), None
        except Exception as e:
            return key, [], f"{key}: {e}"

    tasks = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        if include_globals:
            tasks.append(pool.submit(_safe_call, "products", zentao.get_products))
            tasks.append(pool.submit(_safe_call, "projects", zentao.get_projects))
            tasks.append(pool.submit(_safe_call, "users", zentao.get_users, 200))
        if project_id:
            tasks.append(pool.submit(_safe_call, "executions", zentao.get_executions, project_id))
            tasks.append(pool.submit(_safe_call, "builds", zentao.get_builds, project_id))
        if product_id:
            tasks.append(pool.submit(_safe_call, "modules", zentao.get_modules, product_id))

        for fut in tasks:
            key, data, err = fut.result()
            result[key] = data
            if err:
                result["errors"].append(err)

    return result


@router.get(
    "/api/bugs/{bug_id}/zentao_preview",
    response_model=ZentaoPreviewResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="获取推禅道前的完整预览数据与动态字典",
    description="实时从禅道拉取产品、项目、执行、模块、最近构建版本（自动匹配最近2条 UE+Web）及成员列表，并组装 AI 默认研判字段与富文本步骤预览。",
)
def get_zentao_bug_preview(
    bug_id: str = FastPath(..., description="本地缺陷编号，如 BUG-20261108-001"),
    db: Session = Depends(get_db),
):
    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if not bug:
        raise HTTPException(status_code=404, detail=f"未找到缺陷记录: {bug_id}")

    from config.settings import settings
    from utils.bug_enricher import normalize_severity
    from utils.zentao_sync import (
        APP_NAME_MAP,
        ZenTaoClient,
        format_bug_details_html,
        format_zentao_bug_title,
        pick_default_opened_builds,
        resolve_bug_app_key,
        resolve_bug_assignee,
    )

    resolved_run_id = bug.run_id or (
        Path(bug.task.run_dir).name if (bug.task and bug.task.run_dir) else None
    )
    resolved_app = bug.app_name or (bug.task.app_name if bug.task else None)
    bug_dict_for_app = {
        "app": resolved_app,
        "run_id": resolved_run_id,
        "ui_path": bug.ui_path,
        "screenshot": bug.screenshot_path,
        "crash_screenshot": bug.screenshot_path,
        "target_element": bug.target_element,
        "title": bug.title,
        "actual": bug.actual_error,
    }
    app_key = resolve_bug_app_key(bug_dict_for_app)
    app_chinese = APP_NAME_MAP.get(app_key, "寨湾矿山")
    app_mapping = settings.get_zentao_app_mapping(app_key)

    product_id = int(app_mapping.get("product_id") or 11)
    project_id = int(app_mapping.get("project_id") or 26)
    execution_id = int(app_mapping.get("execution_id") or 0)

    target_assignee = bug.assignee or None
    assignee_name, assignee_account, assignee_reason = resolve_bug_assignee(
        {
            "assignee": target_assignee,
            "analysis_notes": bug.analysis_notes,
            "actual": bug.actual_error,
            "title": bug.title,
        },
        override=target_assignee,
    )

    sev_int = normalize_severity(bug.severity)
    deadline_str = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    zentao_ok = bool(os.getenv("ZENTAO_PASSWORD") or getattr(settings, "zentao_password", None))
    zentao_url = (getattr(settings, "zentao_url", None) or "http://192.140.163.129:8080").rstrip("/")

    bundle: Dict[str, Any] = {
        "products": [],
        "projects": [],
        "executions": [],
        "modules": [],
        "builds": [],
        "users": [],
        "errors": [],
    }
    warning_msg: Optional[str] = None

    if zentao_ok:
        try:
            zentao = ZenTaoClient()
            zentao.get_token()
            bundle = _fetch_zentao_metadata_bundle(
                zentao, project_id=project_id, product_id=product_id, include_globals=True
            )
            if bundle["errors"]:
                warning_msg = "部分禅道字典拉取失败: " + "; ".join(bundle["errors"])
        except Exception as e:
            logger.warning(f"拉取禅道预览元数据异常: {e}")
            warning_msg = f"连接禅道服务器获取实时字典失败，已降级为默认配置 ({e})"
    else:
        warning_msg = "未配置 ZENTAO_PASSWORD，当前仅展示本地默认值"

    # 若配置中 execution_id 为 0 或不在列表，且禅道返回了执行列表，则自动取第一个（或优先匹配名称含“测试”的）
    executions_raw = bundle.get("executions") or []
    if executions_raw:
        exec_ids = {int(e.get("id")) for e in executions_raw if e.get("id") is not None}
        if execution_id not in exec_ids:
            test_exec = next((e for e in executions_raw if "测试" in str(e.get("name") or "")), None)
            execution_id = int((test_exec or executions_raw[0]).get("id") or 0)

    raw_builds = bundle.get("builds") or []
    recommended_builds = pick_default_opened_builds(raw_builds, product_id=product_id)

    screenshot_url = _format_local_screenshot_url(bug.screenshot_path)
    extra_dict: Dict[str, Any] = {}
    if bug.extra_data:
        try:
            import json
            extra_dict = json.loads(bug.extra_data) or {}
        except Exception:
            extra_dict = {}

    raw_bug_dict = {
        "id": bug.id,
        "title": bug.title,
        "ui_path": bug.ui_path,
        "first_ui_path": extra_dict.get("first_ui_path"),
        "affected_modules": extra_dict.get("affected_modules") or [],
        "recurrence_history": bug.recurrence_history or [],
        "target_element": bug.target_element,
        "actual": bug.actual_error,
        "analysis_notes": bug.analysis_notes,
        "crash_screenshot": bug.screenshot_path,
        "occurrences": bug.occurrences,
        "run_id": resolved_run_id,
        "last_seen": bug.last_seen.strftime("%Y-%m-%d %H:%M:%S") if bug.last_seen else "",
    }
    steps_html, _ = format_bug_details_html(
        bug=raw_bug_dict,
        app_key=app_key,
        assignee_name=assignee_name,
        assignee_account=assignee_account,
        uploaded_image_url=screenshot_url,
    )

    users_options = [
        ZentaoUserOption(
            account=str(u.get("account") or ""),
            realname=str(u.get("realname") or u.get("account") or ""),
        )
        for u in (bundle.get("users") or [])
        if u.get("account")
    ]
    if assignee_account and all(u.account != assignee_account for u in users_options):
        users_options.insert(0, ZentaoUserOption(account=assignee_account, realname=assignee_name))

    return ZentaoPreviewResponse(
        zentao_configured=zentao_ok,
        zentao_base_url=zentao_url,
        warning=warning_msg,
        defaults=ZentaoPreviewDefaults(
            bug_id=bug.id,
            app_key=app_key,
            app_name=app_chinese,
            title=format_zentao_bug_title(bug.title, ui_path=bug.ui_path, app_chinese=app_chinese),
            product_id=product_id,
            project_id=project_id,
            execution_id=execution_id,
            module_id=0,
            type="codeerror",
            severity=sev_int,
            pri=sev_int,
            status="active",
            status_label="激活",
            assigned_to=assignee_account,
            assigned_to_name=assignee_name,
            assignee_reason=assignee_reason,
            deadline=deadline_str,
            opened_build=recommended_builds,
            os="windows",
            browser="electron",
            steps_html=steps_html,
            screenshot_url=screenshot_url,
        ),
        options=ZentaoPreviewOptions(
            products=_build_option_list(bundle.get("products") or []),
            projects=_build_option_list(bundle.get("projects") or []),
            executions=_build_option_list(executions_raw),
            modules=_build_module_list(bundle.get("modules") or []),
            builds=_format_build_options(raw_builds),
            users=users_options,
            bug_types=[ZentaoOptionItem(**t) for t in ZENTAO_BUG_TYPES],
        ),
    )


@router.get(
    "/api/zentao/metadata",
    response_model=ZentaoCascadedMetadataResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="级联查询禅道项目/产品关联的执行、模块与构建版本",
    description="在预览弹窗中切换所属项目或所属产品时调用，实时刷新对应执行阶段、产品模块、影响版本及推荐的最近 2 条版本 (UE+Web)。",
)
def get_zentao_cascaded_metadata(
    project_id: Optional[int] = Query(default=None, description="选中的禅道项目 ID"),
    product_id: Optional[int] = Query(default=None, description="选中的禅道产品 ID"),
):
    from utils.zentao_sync import ZenTaoClient, pick_default_opened_builds

    try:
        zentao = ZenTaoClient()
        zentao.get_token()
        bundle = _fetch_zentao_metadata_bundle(
            zentao,
            project_id=int(project_id or 0),
            product_id=int(product_id or 0),
            include_globals=False,
        )
        raw_builds = bundle.get("builds") or []
        recommended = pick_default_opened_builds(raw_builds, product_id=product_id) if project_id else ["trunk"]
        return ZentaoCascadedMetadataResponse(
            executions=_build_option_list(bundle.get("executions") or []),
            modules=_build_module_list(bundle.get("modules") or []),
            builds=_format_build_options(raw_builds),
            recommended_builds=recommended,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"拉取禅道级联元数据失败: {e}")


@router.get(
    "/api/zentao/users",
    response_model=List[ZentaoUserOption],
    tags=["3. 缺陷治理与禅道同步"],
    summary="动态获取禅道系统成员列表",
    description="实时从禅道拉取成员列表，供缺陷编辑弹窗责任人下拉选择；若禅道暂不可达则返回核心分流成员兜底。",
)
def get_zentao_users():
    from utils.zentao_sync import ZenTaoClient

    fallback_users = [
        ZentaoUserOption(account="chenyixiong", realname="陈贻雄"),
        ZentaoUserOption(account="meibenxia", realname="梅本霞"),
        ZentaoUserOption(account="liyuncong", realname="李云骢"),
        ZentaoUserOption(account="jinzhengwu", realname="靳正武"),
    ]
    try:
        zentao = ZenTaoClient()
        users = zentao.get_users(limit=200)
        parsed = [
            ZentaoUserOption(
                account=str(u.get("account") or ""),
                realname=str(u.get("realname") or u.get("account") or ""),
            )
            for u in users
            if u.get("account")
        ]
        return parsed or fallback_users
    except Exception as e:
        logger.warning(f"动态拉取禅道成员列表失败，已降级核心成员列表: {e}")
        return fallback_users

