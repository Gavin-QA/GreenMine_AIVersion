"""
缺陷资产治理、更新、禅道一键推单与 AI 智能二次研判
"""

import datetime
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, BackgroundTasks, Path as FastPath
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models import TaskRun, BugRecord
from ..schemas import (
    BugResponse,
    BugListResponse,
    BugUpdate,
    BugUpdateCompatibleRequest,
    BugUpdateResultResponse,
    BugDeleteResponse,
    ZentaoSubmitRequest,
    ZentaoSyncResponse,
    BatchZentaoSyncRequest,
    BatchZentaoSyncStartResponse,
    BatchZentaoSyncStatusResponse,
)
from utils.paths import PROJECT_ROOT

logger = logging.getLogger("server.bugs")
router = APIRouter()

_batch_zentao_lock = threading.Lock()
_batch_zentao_jobs: Dict[str, Dict[str, Any]] = {}
_active_batch_job_id: Optional[str] = None

@router.post(
    "/api/update_bug_status",
    response_model=BugUpdateResultResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="大盘门户统一接口：更新缺陷生命周期状态",
    description="统一更新缺陷状态，同步更新全局缺陷库、运行目录与平台数据库。",
)
@router.post(
    "/api/update_bug_detail",
    response_model=BugUpdateResultResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="大盘门户统一接口：更新缺陷详细字段与排查说明",
    description="统一更新责任人、严重度、排查批注或回填禅道单号，同步更新全局缺陷库、运行目录与平台数据库。",
)
async def update_bug_compatible_api(data: BugUpdateCompatibleRequest):
    """
    兼容大盘统一门户与历史脚本调用的缺陷生命周期与字段更新接口。

    Args:
        data: 缺陷更新请求契约模型（包含 bug_id/id、status、severity、assignee、zentao_id 等）

    Returns:
        BugUpdateResultResponse: 更新操作执行结果、持久化状态及更新字段列表
    """
    from utils.bug_updater import update_bug_record

    raw_dict = data.model_dump(exclude_unset=True)
    result = update_bug_record(raw_dict)

    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "更新缺陷记录失败")
        )

    return result



@router.get(
    "/api/bugs",
    response_model=BugListResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="多条件检索全局缺陷资产库 (服务端物理分页)",
    description="支持按状态、严重度、责任人、矿山应用以及模糊关键词检索，返回 total 与物理分页 items。",
)
def list_bugs(
    app_name: Optional[str] = Query(
        default=None, description="所属矿山应用代号过滤 (zhaiwan / tianrui / liwutong)"
    ),
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
    page: int = Query(default=1, ge=1, description="页码 (从1开始)"),
    page_size: int = Query(default=15, ge=1, le=200, description="每页最大拉取条数 (默认15条)"),
    limit: Optional[int] = Query(default=None, ge=1, le=500, description="兼容旧参数：最大返回条数"),
    offset: Optional[int] = Query(default=None, ge=0, description="兼容旧参数：偏移量"),
    db: Session = Depends(get_db),
):

    if sync:
        from ..sync_service import perform_hot_sync

        perform_hot_sync(db, force=False)

    q = db.query(BugRecord).order_by(BugRecord.last_seen.desc())

    if app_name:
        q = q.filter(BugRecord.app_name == app_name)

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

    # 1. 毫秒级计算满足过滤条件的总条数
    total = q.count()

    # 2. 分页参数计算与向下兼容
    if limit is not None:
        actual_limit = limit
        actual_offset = offset if offset is not None else 0
        current_page = (actual_offset // actual_limit) + 1 if actual_limit > 0 else 1
        current_page_size = actual_limit
    else:
        current_page = page
        current_page_size = page_size
        actual_offset = (page - 1) * page_size
        actual_limit = page_size

    items = q.offset(actual_offset).limit(actual_limit).all()

    return {
        "total": total,
        "page": current_page,
        "page_size": current_page_size,
        "items": items,
    }


@router.get(
    "/api/bugs/{bug_id}",
    response_model=BugResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="获取指定单条缺陷详情",
    description="根据全局统一缺陷编号精准查询单条缺陷完整元数据与 AI 根因报告。",
)
def get_bug(
    bug_id: str = FastPath(..., description="待查询的缺陷编号，如 BUG-20261101-002"),
    db: Session = Depends(get_db),
):
    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if not bug:
        raise HTTPException(
            status_code=404, detail=f"未找到编号为 '{bug_id}' 的缺陷记录"
        )
    return bug


@router.put(
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
        from utils.bug_enricher import normalize_severity_label
        norm_sev = normalize_severity_label(payload.severity)
        bug.severity = norm_sev

        update_dict["severity"] = norm_sev

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


@router.delete(
    "/api/bugs/{bug_id}",
    response_model=BugDeleteResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="物理注销/删除单条缺陷记录",
    description="彻底从数据库、全局 JSON 库及测试运行报告中清理缺陷记录。若缺陷已提交至禅道，则触发安全红线拦截，禁止删除。",
)
def delete_bug(
    bug_id: str = FastPath(..., description="待删除的缺陷全局唯一编号，如 BUG-20261101-002"),
    db: Session = Depends(get_db),
):
    """
    物理注销并删除单条缺陷记录及其在所有介质中的副本。

    Args:
        bug_id: 全局缺陷编号
        db: 数据库会话

    Returns:
        BugDeleteResponse: 包含状态码、删除缺陷 ID 及影响载体
    """
    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if not bug:
        raise HTTPException(
            status_code=404, detail=f"未找到编号为 '{bug_id}' 的缺陷记录"
        )

    # 核心安全铁律防线：已提交至禅道的缺陷为正式受控单据，严禁删除
    if bug.zentao_id:
        raise HTTPException(
            status_code=403,
            detail=f"安全保护拦截：缺陷 '{bug_id}' 已同步推送到禅道系统 (工单 #{bug.zentao_id})，作为受控缺陷禁止直接物理删除！如需作废请在禅道系统中进行状态流转。"
        )

    from utils.bug_updater import delete_bug_record
    result = delete_bug_record(bug_id)

    # 如果数据库里还残留（例如之前未被 bug_updater 涵盖的 Session），确保当前 session 也清理
    curr_bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if curr_bug:
        db.delete(curr_bug)
        db.commit()

    return {
        "code": 200,
        "message": f"缺陷 {bug_id} 已成功彻底物理删除",
        "bug_id": bug_id,
        "deleted_targets": result.get("deleted_targets", []),
    }


def _execute_single_zentao_sync(
    bug: BugRecord,
    db: Session,
    zentao=None,
    assignee: Optional[str] = None,
    payload: Optional[ZentaoSubmitRequest] = None,
    builds_cache: Optional[Dict[int, Any]] = None,
    users_cache: Optional[List[Dict[str, Any]]] = None,
):
    """执行单条缺陷提交禅道的核心逻辑，返回 (zentao_id, zentao_url, r_files)。"""
    from utils.zentao_sync import (
        ZenTaoClient,
        format_bug_details_html,
        format_zentao_bug_title,
        find_bug_in_databases,
        image_to_base64_data_uri,
        pick_default_opened_builds,
        resolve_bug_assignee,
        resolve_bug_app_key,
        update_bug_records,
        APP_NAME_MAP,
    )
    from .zentao import _format_local_screenshot_url
    from config.settings import settings
    from utils.bug_enricher import normalize_severity

    if zentao is None:
        zentao = ZenTaoClient()

    # 1. 动态智能判定该 Bug 所属矿山应用 (多级防呆)
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

    # 2. 读取对应矿山应用专属的禅道产品/项目/迭代归属三元组（支持预览弹窗覆盖）
    app_mapping = settings.get_zentao_app_mapping(app_key)
    product_id = int(payload.product_id) if (payload and payload.product_id is not None) else app_mapping["product_id"]
    project_id = int(payload.project_id) if (payload and payload.project_id is not None) else app_mapping["project_id"]
    execution_id = int(payload.execution_id) if (payload and payload.execution_id is not None) else app_mapping["execution_id"]
    module_id = int(payload.module_id) if (payload and payload.module_id is not None) else 0
    app_chinese = APP_NAME_MAP.get(app_key, "寨湾矿山")

    target_assignee = (payload.assigned_to if payload and payload.assigned_to else None) or assignee or bug.assignee or "陈贻雄"

    assignee_name, assignee_account, _ = resolve_bug_assignee(
        {"assignee": target_assignee}, override=target_assignee
    )
    # 如果前端传了明确的禅道账号且与本地映射表不同，尝试用禅道用户列表解析真实姓名
    if payload and payload.assigned_to and assignee_name == assignee_account:
        try:
            u_list = users_cache if users_cache is not None else zentao.get_users(limit=200)
            for u in u_list:
                if u.get("account") == assignee_account:
                    assignee_name = u.get("realname") or assignee_account
                    break
        except Exception:
            pass

    extra_dict: Dict[str, Any] = {}
    if bug.extra_data:
        try:
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

    if payload and payload.steps_html:
        steps_html = payload.steps_html
        local_preview_url = _format_local_screenshot_url(shot_path)
        if local_preview_url and local_preview_url in steps_html:
            replacement_img = uploaded_url or (image_to_base64_data_uri(Path(shot_path)) if shot_path else None)
            if replacement_img:
                steps_html = steps_html.replace(local_preview_url, replacement_img)
    else:
        steps_html, _ = format_bug_details_html(
            bug=raw_bug_dict,
            app_key=app_key,
            assignee_name=assignee_name,
            assignee_account=assignee_account,
            uploaded_image_url=uploaded_url,
        )

    sev_val = int(payload.severity) if (payload and payload.severity is not None) else normalize_severity(bug.severity)
    pri_val = int(payload.pri) if (payload and payload.pri is not None) else sev_val
    bug_type = (payload.type if (payload and payload.type) else "codeerror")
    deadline_val = (payload.deadline if (payload and payload.deadline) else (datetime.datetime.now() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"))
    os_name = (payload.os if (payload and payload.os) else "windows")
    browser_name = (payload.browser if (payload and payload.browser) else "electron")

    if payload and payload.opened_build:
        opened_build = payload.opened_build
    else:
        try:
            if builds_cache is not None and project_id in builds_cache:
                proj_builds = builds_cache[project_id]
            else:
                proj_builds = zentao.get_builds(project_id) if project_id else []
                if builds_cache is not None:
                    builds_cache[project_id] = proj_builds
            opened_build = pick_default_opened_builds(proj_builds, product_id=product_id)
        except Exception:
            opened_build = ["trunk"]

    final_title = (
        payload.title.strip()
        if (payload and payload.title and payload.title.strip())
        else format_zentao_bug_title(bug.title, ui_path=bug.ui_path, app_chinese=app_chinese)
    )

    res = zentao.submit_bug(
        product_id=product_id,
        title=final_title,
        steps_html=steps_html,
        severity=sev_val,
        pri=pri_val,
        bug_type=bug_type,
        assigned_to=assignee_account,
        project_id=project_id,
        execution_id=execution_id,
        module_id=module_id,
        deadline=deadline_val,
        opened_build=opened_build,
        os_name=os_name,
        browser_name=browser_name,
        files=uploaded_file_ids if uploaded_file_ids else None,
    )

    z_id = str(res.get("id"))

    # 更新本地数据库
    bug.zentao_id = z_id
    bug.status = "已提单"
    bug.assignee = assignee_name
    db.commit()

    # 同步回填本地 JSON 库 (禁用耗时的同步渲染离线 HTML 报告)
    _, g_file, r_files = find_bug_in_databases(bug.id)
    update_bug_records(
        bug.id, z_id, g_file, r_files, assignee=assignee_name, sync_reports=False
    )

    zentao_url = f"{zentao.url}/index.php?m=bug&f=view&bugID={z_id}"
    return z_id, zentao_url, r_files


def _run_batch_zentao_sync_job(job_id: str, bug_ids: List[str]) -> None:
    """后台单线程串行执行批量禅道提单任务，避免 JSON 并发写入冲突与接口限流。"""
    global _active_batch_job_id
    from utils.zentao_sync import ZenTaoClient, rebuild_run_reports

    db = SessionLocal()
    all_r_files_map: Dict[str, Path] = {}
    try:
        zentao = ZenTaoClient()
        builds_cache: Dict[int, Any] = {}

        for bid in bug_ids:
            with _batch_zentao_lock:
                _batch_zentao_jobs[job_id]["current_bug_id"] = bid

            try:
                bug = db.query(BugRecord).filter(BugRecord.id == bid).first()
                if not bug:
                    with _batch_zentao_lock:
                        job = _batch_zentao_jobs[job_id]
                        job["failed"] += 1
                        job["processed"] += 1
                        job["results"].append({
                            "bug_id": bid,
                            "status": "failed",
                            "message": "缺陷记录不存在",
                        })
                    continue

                if bug.zentao_id:
                    with _batch_zentao_lock:
                        job = _batch_zentao_jobs[job_id]
                        job["skipped"] += 1
                        job["processed"] += 1
                        job["results"].append({
                            "bug_id": bid,
                            "status": "skipped",
                            "zentao_id": str(bug.zentao_id),
                            "message": f"已存在禅道单号 #{bug.zentao_id}",
                        })
                    continue

                z_id, zentao_url, r_files = _execute_single_zentao_sync(
                    bug=bug,
                    db=db,
                    zentao=zentao,
                    builds_cache=builds_cache,
                )
                for rf in r_files or []:
                    all_r_files_map[str(rf)] = rf

                with _batch_zentao_lock:
                    job = _batch_zentao_jobs[job_id]
                    job["succeeded"] += 1
                    job["processed"] += 1
                    job["results"].append({
                        "bug_id": bid,
                        "status": "success",
                        "zentao_id": z_id,
                        "zentao_url": zentao_url,
                        "message": "提交成功",
                    })
            except Exception as e:
                db.rollback()
                logger.error(f"[BatchZenTao:{job_id}] 提单 {bid} 失败: {e}")
                with _batch_zentao_lock:
                    job = _batch_zentao_jobs[job_id]
                    job["failed"] += 1
                    job["processed"] += 1
                    job["results"].append({
                        "bug_id": bid,
                        "status": "failed",
                        "message": str(e),
                    })

        if all_r_files_map:
            try:
                rebuild_run_reports(list(all_r_files_map.values()))
            except Exception as e:
                logger.warning(f"[BatchZenTao:{job_id}] 批量重渲染历史报告异常: {e}")

        with _batch_zentao_lock:
            job = _batch_zentao_jobs[job_id]
            job["status"] = "completed"
            job["current_bug_id"] = None
            job["finished_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.error(f"[BatchZenTao:{job_id}] 后台任务初始化或运行异常: {e}")
        with _batch_zentao_lock:
            job = _batch_zentao_jobs[job_id]
            job["status"] = "failed"
            job["current_bug_id"] = None
            job["error"] = str(e)
            job["finished_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    finally:
        db.close()
        with _batch_zentao_lock:
            if _active_batch_job_id == job_id:
                _active_batch_job_id = None


@router.post(
    "/api/bugs/batch_sync_zentao",
    response_model=BatchZentaoSyncStartResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="后台串行批量将勾选的缺陷提交至禅道",
    description="接收勾选的缺陷编号列表，在后台单线程按顺序串行提交至禅道并回填本地数据库与 JSON 资产库。",
)
def start_batch_sync_zentao(payload: BatchZentaoSyncRequest):
    """启动后台串行批量禅道提单任务。"""
    global _active_batch_job_id

    unique_ids: List[str] = []
    seen = set()
    for raw_id in payload.bug_ids:
        bid = (raw_id or "").strip()
        if bid and bid not in seen:
            seen.add(bid)
            unique_ids.append(bid)

    if not unique_ids:
        raise HTTPException(status_code=400, detail="请至少勾选一条有效缺陷")

    with _batch_zentao_lock:
        if _active_batch_job_id and _active_batch_job_id in _batch_zentao_jobs:
            active_job = _batch_zentao_jobs[_active_batch_job_id]
            if active_job.get("status") == "running":
                raise HTTPException(
                    status_code=409,
                    detail=f"已有批量推禅道任务正在后台运行中 ({active_job['processed']}/{active_job['total']})，请等待完成后再发起新任务",
                )

        job_id = f"bz_{uuid.uuid4().hex[:10]}"
        _batch_zentao_jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "total": len(unique_ids),
            "processed": 0,
            "succeeded": 0,
            "skipped": 0,
            "failed": 0,
            "current_bug_id": unique_ids[0],
            "started_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "error": None,
            "results": [],
        }
        _active_batch_job_id = job_id

    t = threading.Thread(
        target=_run_batch_zentao_sync_job,
        args=(job_id, unique_ids),
        daemon=True,
        name=f"BatchZentao-{job_id}",
    )
    t.start()

    return {
        "code": 200,
        "message": f"已启动后台串行批量推禅道任务，共 {len(unique_ids)} 条缺陷",
        "job_id": job_id,
        "total": len(unique_ids),
    }


@router.get(
    "/api/bugs/batch_sync_zentao/active",
    response_model=Optional[BatchZentaoSyncStatusResponse],
    tags=["3. 缺陷治理与禅道同步"],
    summary="获取当前正在运行的批量推禅道任务状态",
)
def get_active_batch_sync_zentao():
    """查询当前运行中的批量推禅道任务（无则返回 null）。"""
    with _batch_zentao_lock:
        if _active_batch_job_id and _active_batch_job_id in _batch_zentao_jobs:
            return dict(_batch_zentao_jobs[_active_batch_job_id])
    return None


@router.get(
    "/api/bugs/batch_sync_zentao/{job_id}",
    response_model=BatchZentaoSyncStatusResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="查询批量推禅道任务进度",
)
def get_batch_sync_zentao_status(job_id: str):
    """查询指定批量推禅道任务的实时进度与明细。"""
    with _batch_zentao_lock:
        job = _batch_zentao_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="批量提单任务不存在或已过期")
        return dict(job)


@router.post(
    "/api/bugs/{bug_id}/sync_zentao",
    response_model=ZentaoSyncResponse,
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
    payload: Optional[ZentaoSubmitRequest] = Body(default=None),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    一键将本地捕获的缺陷提报至公司禅道项目系统。

    Args:
        bug_id: 全局缺陷编号
        assignee: 可选手动指派人
        background_tasks: 后台任务实例
        db: 数据库会话

    Returns:
        ZentaoSyncResponse: 包含提单结果、禅道工单号及直接跳转 URL
    """

    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()

    if not bug:
        raise HTTPException(status_code=404, detail="Bug not found")

    try:
        from utils.zentao_sync import rebuild_run_reports

        z_id, zentao_url, r_files = _execute_single_zentao_sync(
            bug=bug,
            db=db,
            assignee=assignee,
            payload=payload,
        )

        # 异步后台任务：默默渲染历史报告与大盘，绝不卡死前端 Web 界面
        if background_tasks and r_files:
            background_tasks.add_task(rebuild_run_reports, r_files)

        return {
            "code": 200,
            "message": "禅道提交成功",
            "bug_id": bug.id,
            "zentao_id": z_id,
            "zentao_url": zentao_url,
        }

    except Exception as e:
        logger.error(f"同步缺陷 {bug_id} 到禅道异常: {e}")

        raise HTTPException(status_code=500, detail=f"提单失败: {e}")


@router.post(
    "/api/bugs/{bug_id}/reanalyze",
    response_model=BugResponse,
    tags=["3. 缺陷治理与禅道同步"],
    summary="对指定缺陷在线触发 AI 重新诊断与根因分析",
    description="在 Web 控制台按需为指定缺陷重新调用大模型进行深度研判，基于最新案发现场提取底层机理、修复补丁并更新责任人。",
)
def reanalyze_bug(
    bug_id: str = FastPath(
        ..., description="待重新诊断的缺陷全局唯一编号，如 BUG-20261101-002"
    ),
    db: Session = Depends(get_db),
):
    """
    在线重新执行大模型研发级深度根因诊断并热刷新缺陷初诊备注与责任人。
    """
    bug = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
    if not bug:
        raise HTTPException(
            status_code=404, detail=f"未找到编号为 '{bug_id}' 的缺陷记录"
        )

    from core.vision.agent import VisionAgent
    from utils.bug_analysis_expert import analyze_bug_expertly
    from utils.zentao_sync import resolve_bug_assignee
    from utils.bug_updater import update_bug_record
    from config.settings import settings

    try:
        agent = VisionAgent()
        analysis_model = getattr(settings, "llm_bug_analysis_model", None) or agent.model
        bug_dict = {
            "id": bug.id,
            "title": bug.title,
            "step": bug.step or "无具体交互步骤",
            "actual": bug.actual_error or "无具体报错堆栈",
            "ui_path": bug.ui_path or "未知",
            "app": bug.app_name or "zhaiwan",
            "screenshot": bug.screenshot_path,
            "occurrences": bug.occurrences or 1,
        }
        formatted_notes, res_dict = analyze_bug_expertly(
            agent=agent,
            model=analysis_model,
            bug=bug_dict,
            crash_image_path=bug.screenshot_path,
            app_key=bug.app_name
        )

        resolved_assignee = None
        try:
            temp_bug = {
                "title": bug.title,
                "step": bug.step,
                "actual": bug.actual_error,
                "analysis_notes": formatted_notes,
            }
            resolved_assignee, _, _ = resolve_bug_assignee(temp_bug)
        except Exception:
            pass

        update_payload = {"bug_id": bug_id, "analysis_notes": formatted_notes}
        bug.analysis_notes = formatted_notes
        if resolved_assignee and bug.assignee in ("Unassigned", "", None):
            bug.assignee = resolved_assignee
            update_payload["assignee"] = resolved_assignee

        db.commit()
        db.refresh(bug)

        # 增量同步至全局 JSON 与运行报告
        try:
            update_bug_record(update_payload)
        except Exception as ue:
            logger.warning(f"重新分析同步写回文件失败 (数据库已保全): {ue}")

        return bug
    except Exception as e:
        logger.error(f"AI 重新诊断缺陷 [{bug_id}] 异常: {e}")
        raise HTTPException(status_code=500, detail=f"AI 重新诊断失败: {str(e)}")



