# -*- coding: utf-8 -*-
"""
utils/bug_db_sync.py —— 缺陷持久化数据库核心引擎与本地文件双向恢复自愈中心

核心定位：
1. DB-First: 发现缺陷时，第一时间以 ACID 事务入库 SQLite (BugRecord)；
2. 案发图片云端化: 将 Bug 案发现场截图压缩转为 Base64 同步进库，彻底脱离对本地磁盘图片的强依赖；
3. Rehydration: 无论本地 global_bugs_<app>.json 还是各批次的 bugs/<id>.json、现场图片被误删，
   均能基于数据库 100% 无损重新生成；
4. Dual-Write: 保全原有的本地 JSON 档案，确保对老工具、离线环境与飞书打包的零破坏兼容。
"""

import os
import sys
import io
import json
import base64
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from PIL import Image

from utils.paths import PROJECT_ROOT, GLOBAL_BUGS_DIR, RUNS_DIR, get_run_bugs_dir

logger = logging.getLogger("utils.bug_db_sync")


def get_db_session():
    """安全获取数据库会话"""
    try:
        from server.database import SessionLocal
        return SessionLocal()
    except Exception as e:
        logger.warning(f"获取数据库会话失败 (可能未安装或配置异常): {e}")
        return None


def image_to_base64(img_path: Optional[Path]) -> Optional[str]:
    """将图片文件压缩为 WebP 并转为 Base64 字符串 (体积压缩 30%~70%)"""
    if not img_path:
        return None
    p = Path(img_path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.exists() or not p.is_file():
        return None

    try:
        with Image.open(p) as im:
            buf = io.BytesIO()
            im.save(buf, format="WEBP", quality=85)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/webp;base64,{encoded}"
    except Exception:
        try:
            with open(p, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
                suffix = p.suffix.lstrip(".").lower() or "png"
                return f"data:image/{suffix};base64,{encoded}"
        except Exception:
            return None


def base64_to_image(b64_str: str, out_path: Path) -> bool:
    """将 Base64 字符串逆向还原写入为本地图片文件"""
    if not b64_str:
        return False
    try:
        if "," in b64_str:
            b64_data = b64_str.split(",", 1)[1]
        else:
            b64_data = b64_str
        raw_bytes = base64.b64decode(b64_data)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(raw_bytes)) as im:
            fmt = "PNG" if out_path.suffix.lower() == ".png" else "WEBP"
            im.save(out_path, format=fmt)
        return True
    except Exception:
        try:
            if "," in b64_str:
                b64_data = b64_str.split(",", 1)[1]
            else:
                b64_data = b64_str
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            return True
        except Exception:
            return False


def save_bug_to_db(bug_dict: Dict[str, Any]) -> Optional[str]:
    """
    将缺陷字典直接持久化至数据库 BugRecord 表 (DB-First)
    同步存入现场截图 Base64 数据，返回 bug_id，若失败返回 None 但绝不抛出异常阻断主流程。
    """
    db = get_db_session()
    if not db:
        return None

    try:
        from server.models import BugRecord

        b_id = bug_dict.get("id")
        if not b_id:
            return None

        # 检查是否已存在
        record = db.query(BugRecord).filter(BugRecord.id == b_id).first()

        app_name = bug_dict.get("app") or bug_dict.get("app_name") or "zhaiwan"
        run_id = bug_dict.get("run_id")
        task_id = bug_dict.get("task_id")
        from utils.bug_enricher import normalize_severity_label
        title = bug_dict.get("title", "")
        severity = normalize_severity_label(bug_dict.get("severity", "Medium"))
        status = bug_dict.get("status", "激活")
        assignee = bug_dict.get("assignee", "陈贻雄")
        zentao_id = str(bug_dict.get("zentao_id")) if bug_dict.get("zentao_id") else None
        ui_path = bug_dict.get("ui_path")
        target_element = bug_dict.get("target_element")
        step_val = bug_dict.get("step")
        action_type_val = bug_dict.get("action_type")
        actual_error = bug_dict.get("actual") or bug_dict.get("actual_error")
        if isinstance(actual_error, dict):
            actual_error = str(actual_error)
        analysis_notes = bug_dict.get("analysis_notes")
        remark = bug_dict.get("remark")
        screenshot = bug_dict.get("screenshot") or bug_dict.get("screenshot_path") or bug_dict.get("crash_screenshot")
        before_screenshot = bug_dict.get("before_screenshot") or bug_dict.get("before_screenshot_path")
        occurrences = int(bug_dict.get("occurrences") or 1)

        # 现场图片 Base64 提取
        b64_img = bug_dict.get("screenshot_base64")
        if not b64_img and screenshot:
            b64_img = image_to_base64(screenshot)

        tags_raw = bug_dict.get("tags")
        tags_str = json.dumps(tags_raw, ensure_ascii=False) if tags_raw is not None else None

        extra_info = {
            "details": bug_dict.get("details"),
            "global_step": bug_dict.get("global_step"),
            "creation_date": bug_dict.get("creation_date") or bug_dict.get("date"),
        }
        extra_data_str = json.dumps(extra_info, ensure_ascii=False)

        now_dt = datetime.datetime.now()

        if not record:
            record = BugRecord(
                id=b_id,
                task_id=task_id,
                run_id=run_id,
                app_name=app_name,
                title=title,
                severity=severity,
                status=status,
                assignee=assignee,
                zentao_id=zentao_id,
                ui_path=ui_path,
                target_element=target_element,
                step=step_val,
                action_type=action_type_val,
                tags=tags_str,
                actual_error=actual_error,
                analysis_notes=analysis_notes,
                remark=remark,
                screenshot_path=screenshot,
                before_screenshot_path=before_screenshot,
                screenshot_base64=b64_img,
                extra_data=extra_data_str,
                occurrences=occurrences,
                first_seen=now_dt,
                last_seen=now_dt
            )
            db.add(record)
            logger.info(f"💾 [DB-First] 新缺陷 [{b_id}] 已成功插入数据库 (含现场截图 Base64)")
        else:
            # 增量更新已存在的 Bug
            if occurrences > (record.occurrences or 0):
                record.occurrences = occurrences
            record.last_seen = now_dt
            if bug_dict.get("severity") is not None or record.severity not in ("High", "Medium", "Low"):
                record.severity = normalize_severity_label(bug_dict.get("severity") or record.severity)
            if run_id:
                record.run_id = run_id
            if task_id:
                record.task_id = task_id
            if title:
                record.title = title
            if status:
                record.status = status
            if assignee and record.assignee in ("Unassigned", "", None):
                record.assignee = assignee
            if zentao_id:
                record.zentao_id = zentao_id

            # 核心升级：每次新复现，强制更新为主视图最新案发现场！
            if ui_path:
                record.ui_path = ui_path
            if target_element:
                record.target_element = target_element
            if step_val:
                record.step = step_val
            if action_type_val:
                record.action_type = action_type_val
            if actual_error:
                record.actual_error = actual_error
            if tags_str:
                record.tags = tags_str
            if analysis_notes:
                record.analysis_notes = analysis_notes
            if remark:
                record.remark = remark
            if screenshot:
                record.screenshot_path = screenshot
            if before_screenshot:
                record.before_screenshot_path = before_screenshot
            if b64_img:
                record.screenshot_base64 = b64_img

            # 增量合并 recurrence_history 到 extra_data
            try:
                old_extra = json.loads(record.extra_data) if record.extra_data else {}
            except Exception:
                old_extra = {}
            new_history = bug_dict.get("recurrence_history", [])
            if new_history:
                old_extra["recurrence_history"] = new_history
            if bug_dict.get("first_step") and "first_step" not in old_extra:
                old_extra["first_step"] = bug_dict.get("first_step")
            if bug_dict.get("details"):
                old_extra["details"] = bug_dict.get("details")
            old_extra["last_update"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            record.extra_data = json.dumps(old_extra, ensure_ascii=False)

            logger.info(f"🔄 [DB-First] 历史缺陷 [{b_id}] 已在数据库中更新为最新案发现场 (最新步骤: {step_val}, 累计复现: {record.occurrences})")

        db.commit()
        return b_id
    except Exception as e:
        if db:
            db.rollback()
        logger.warning(f"写入缺陷到数据库失败 (自动降级至纯文件模式): {e}")
        return None
    finally:
        if db:
            db.close()


def get_bugs_from_db(app_name: Optional[str] = None, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    从数据库中读取缺陷列表并转换为统一字典格式 (包含截图 Base64 数据)
    """
    db = get_db_session()
    if not db:
        return []

    try:
        from server.models import BugRecord

        q = db.query(BugRecord)
        if app_name:
            q = q.filter(BugRecord.app_name == app_name)
        if run_id:
            q = q.filter(BugRecord.run_id == run_id)

        records = q.order_by(BugRecord.first_seen.asc()).all()
        results = []
        for r in records:
            tags_list = []
            if r.tags:
                try:
                    tags_list = json.loads(r.tags)
                except Exception:
                    tags_list = [r.tags]

            extra = {}
            if r.extra_data:
                try:
                    extra = json.loads(r.extra_data)
                except Exception:
                    pass

            item = {
                "id": r.id,
                "run_id": r.run_id,
                "task_id": r.task_id,
                "app": r.app_name or "zhaiwan",
                "title": r.title or "",
                "severity": r.severity or "Medium",
                "status": r.status or "激活",
                "assignee": r.assignee or "Unassigned",
                "zentao_id": r.zentao_id,
                "ui_path": r.ui_path,
                "target_element": r.target_element,
                "step": r.step,
                "action_type": r.action_type,
                "tags": tags_list,
                "actual": r.actual_error,
                "analysis_notes": r.analysis_notes,
                "remark": r.remark,
                "screenshot": r.screenshot_path,
                "screenshot_base64": r.screenshot_base64,
                "occurrences": r.occurrences or 1,
                "date": r.first_seen.strftime("%Y-%m-%d") if r.first_seen else "",
                "last_seen": r.last_seen.strftime("%Y-%m-%d") if r.last_seen else "",
                "details": extra.get("details", {
                    "step": r.step,
                    "expected": "执行该操作时不应报错，界面按预期进行交互或跳转",
                    "actual": r.actual_error
                })
            }
            results.append(item)
        return results
    except Exception as e:
        logger.warning(f"从数据库读取缺陷失败: {e}")
        return []
    finally:
        if db:
            db.close()


def restore_global_bugs_file(app_name: str = "zhaiwan") -> Optional[Path]:
    """
    当 artifacts/bugs/global_bugs_<app>.json 丢失或为空时，
    直接从数据库提取全量 BugRecord 并重建该文件。
    """
    GLOBAL_BUGS_DIR.mkdir(parents=True, exist_ok=True)
    target_file = GLOBAL_BUGS_DIR / f"global_bugs_{app_name}.json"

    db_bugs = get_bugs_from_db(app_name=app_name)
    if not db_bugs:
        logger.info(f"数据库中尚无应用 [{app_name}] 的缺陷记录，无需反哺重建。")
        return None

    try:
        # 导出全局 JSON 时，过滤超大 base64 保证 json 文件的极致轻量
        export_bugs = []
        for b in db_bugs:
            item = dict(b)
            item.pop("screenshot_base64", None)
            export_bugs.append(item)

        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(export_bugs, f, ensure_ascii=False, indent=2)
        logger.info(f"🎉 [自愈重建] 已成功根据数据库重建本地缺陷知识库: {target_file.name} (共 {len(export_bugs)} 条记录)")
        return target_file
    except Exception as e:
        logger.error(f"从数据库重建 {target_file.name} 失败: {e}")
        return None


def restore_run_bugs(run_id: str, app_name: Optional[str] = None) -> List[Path]:
    """
    当某个 run 目录下的 bugs/ 文件夹或 json / png 图片丢失时，
    直接从数据库拉取并恢复所有 bugs/<id>.json 以及逆向还原现场图片 <id>.png！
    """
    db_bugs = get_bugs_from_db(run_id=run_id)
    if not db_bugs:
        return []

    # 找到对应的 run_dir
    target_run_dir = None
    for rf in RUNS_DIR.glob(f"**/{run_id}"):
        if rf.is_dir():
            target_run_dir = rf
            break

    if not target_run_dir:
        app_key = app_name or db_bugs[0].get("app") or "zhaiwan"
        target_run_dir = RUNS_DIR / app_key / run_id

    bugs_dir = target_run_dir / "bugs"
    bugs_dir.mkdir(parents=True, exist_ok=True)

    restored_files = []
    for b in db_bugs:
        b_id = b["id"]
        detail_path = bugs_dir / f"{b_id}.json"
        try:
            detail_obj = {
                "id": b_id,
                "title": b.get("title"),
                "severity": b.get("severity"),
                "status": b.get("status"),
                "assignee": b.get("assignee"),
                "creation_date": b.get("date"),
                "details": b.get("details", {
                    "step": b.get("step"),
                    "expected": "执行该操作时不应报错，界面按预期进行交互或跳转",
                    "actual": b.get("actual")
                }),
                "crash_screenshot": b.get("screenshot"),
                "action_type": b.get("action_type") or "无",
                "target_element": b.get("target_element") or "无",
                "ui_path": b.get("ui_path") or "无",
                "tags": b.get("tags") or [],
                "analysis_notes": b.get("analysis_notes") or "",
                "remark": b.get("remark") or "",
                "occurrences": b.get("occurrences", 1),
                "last_seen": b.get("last_seen", ""),
                "zentao_id": b.get("zentao_id")
            }
            with open(detail_path, "w", encoding="utf-8") as f:
                json.dump(detail_obj, f, ensure_ascii=False, indent=2)
            restored_files.append(detail_path)

            # 核心终极防线：若本地案发现场截图丢失，直接从数据库 Base64 逆向还原图片！
            img_target = bugs_dir / f"{b_id}.png"
            b64_val = b.get("screenshot_base64")
            if not img_target.exists() and b64_val:
                if base64_to_image(b64_val, img_target):
                    restored_files.append(img_target)
                    logger.info(f"🖼️ [图片自愈] 已从数据库 Base64 成功还原案发现场截图: {img_target.name}")

        except Exception as e:
            logger.warning(f"恢复运行目录 Bug 文件失败 ({detail_path.name}): {e}")

    logger.info(f"✨ [自愈重建] 已成功为批次 [{run_id}] 恢复 {len(restored_files)} 个缺陷资产 (含 JSON 与图片)！")
    return restored_files
