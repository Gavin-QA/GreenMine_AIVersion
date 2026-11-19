"""
测试用例资产管理与探索成果晋升
"""

import logging
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
import yaml

from fastapi import APIRouter, HTTPException, Query

from ..schemas import (
    TestCaseItem,
    TestCaseListResponse,
    TestCaseContentResponse,
    CasePromoteRequest,
    CasePromoteResponse,
)
from utils.paths import PROJECT_ROOT

logger = logging.getLogger("server.cases")
router = APIRouter()

@router.get(
    "/api/cases",
    response_model=TestCaseListResponse,
    tags=["5. 用例资产管理"],
    summary="获取全量测试用例资产列表 (分手工编写与 AI 自动生成两类)",
    description="扫描并汇总 test_cases/ 下的手工编写自然语言用例，以及 reports/runs/**/generated_cases 下 AI 探索沉淀的回归用例。",
)
def get_test_cases():
    """
    拉取全量手工维护用例与 AI 逆向探索沉淀的回归用例清单。

    Returns:
        TestCaseListResponse: 包含 manual_cases、auto_cases 及其总数统计
    """
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
                # p 固定位于 <run_dir>/generated_cases/<file>.yaml，因此 p.parent.parent.name 恒为真实 run_id
                run_id = p.parent.parent.name
                try:
                    from utils.paths import is_month_folder
                    idx = parts.index("runs")
                    if len(parts) > idx + 1:
                        cand_app = parts[idx + 1]
                        if cand_app != run_id and not is_month_folder(cand_app):
                            app_name = cand_app
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


@router.get(
    "/api/cases/content",
    response_model=TestCaseContentResponse,
    tags=["5. 用例资产管理"],
    summary="读取指定用例的 YAML 内容",
    description="读取并返回指定 YAML 用例文件的纯文本代码内容。",
)
def get_case_content(
    path: str = Query(..., description="用例相对工程根目录的路径 (如 test_cases/case_zhaiwan_smoke.yaml)")
):
    """
    在线预览指定用例的 YAML 纯文本源码。

    Args:
        path: 用例相对工程根目录路径

    Returns:
        TestCaseContentResponse: 包含路径、文件名与内容
    """
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


@router.post(
    "/api/cases/promote",
    response_model=CasePromoteResponse,
    tags=["5. 用例资产管理"],
    summary="将 AI 自动生成的用例固化转存为手工常态化回归用例",
    description="将探索过程中大模型自主生成的 YAML 回归链路，一键拷贝固化转存至 test_cases/ 正式用例目录中。",
)
def promote_auto_case(payload: CasePromoteRequest):
    """
    将 AI 自动生成的临时用例固化升级为正式常态化回归用例。

    Args:
        payload: 包含源路径与目标文件名的请求体

    Returns:
        CasePromoteResponse: 包含状态码与固化后的新文件相对路径
    """
    path = payload.path
    target_name = payload.target_name
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

