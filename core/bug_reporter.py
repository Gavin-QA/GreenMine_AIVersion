import os

import json

import shutil

import logging

import base64

import threading

from datetime import datetime

from pathlib import Path

from core.vision.agent import VisionAgent

from utils.paths import GLOBAL_BUGS_DIR, get_run_bugs_dir

logger = logging.getLogger("core.bug_reporter")

class BugReporter:

    def __init__(self, vision_agent=None):

        self._lock = threading.Lock()

        # 全局持久资产目录: artifacts/bugs/

        self.global_bugs_dir = GLOBAL_BUGS_DIR

        self.global_bugs_dir.mkdir(parents=True, exist_ok=True)

        from config.settings import settings

        self.active_app = getattr(settings, "active_app", "default")

        # 严格按应用专属文件管理 (多项目彻底物理隔离，绝不生成无后缀 legacy 文件)

        self.global_json = self.global_bugs_dir / f"global_bugs_{self.active_app}.json"

        # 允许外部传入已有的 VisionAgent，若没有则自己实例化一个用于 LLM 推理

        self.vision = vision_agent if vision_agent else VisionAgent()

        # Load global bugs

        self.global_bugs = []

        if self.global_json.exists():

            try:

                with open(self.global_json, "r", encoding="utf-8") as f:

                    self.global_bugs = json.load(f)

                logger.info(f"🐞 成功加载应用【{self.active_app}】专属缺陷库: {self.global_json.name} (共 {len(self.global_bugs)} 条记录)")

            except Exception as e:

                logger.error(f"无法读取应用专属 Bug 库: {e}")

        else:

            logger.info(f"✨ 应用【{self.active_app}】尚无历史缺陷库，将初始化新库: {self.global_json.name}")

        # 自愈反哺：若本地 JSON 不存在或被清空，自动基于数据库重建
        if not self.global_bugs:
            try:
                from utils.bug_db_sync import restore_global_bugs_file
                restored_path = restore_global_bugs_file(self.active_app)
                if restored_path and restored_path.exists():
                    with open(restored_path, "r", encoding="utf-8") as f:
                        self.global_bugs = json.load(f)
                    logger.info(f"✨ [自愈重建] 成功从数据库重建应用【{self.active_app}】缺陷库: {len(self.global_bugs)} 条记录")
            except Exception as re_err:
                logger.debug(f"从数据库自愈缺陷库跳过: {re_err}")

    def report_bug(self, run_id: str, title: str, step_prompt: str, actual_result: str, crash_image_path: str = None, before_image_path: str = None, **kwargs):

        """记录一个新的崩溃现场，自动查重并保存。支持双图对比（操作前/案发瞬间）及扩展参数。"""

        logger.info("=" * 60)

        logger.info(f"🐞 捕获到缺陷异常，开始生成 Bug 报告...")

        # 1. 智能查重

        dup_id = self._check_duplicate(
            step_prompt,
            actual_result,
            ui_path=kwargs.get("ui_path"),
            target_element=kwargs.get("target_element"),
        )

        # 单次运行现场统一收敛至 reports/runs/<run_id>/bugs/

        run_dir = get_run_bugs_dir(run_id)

        now_date = datetime.now().strftime("%Y-%m-%d")

        if dup_id:

            logger.info(f"🔍 发现重复缺陷，将追加复现记录到历史 Bug: [{dup_id}]")

            bug_record = next((b for b in self.global_bugs if b["id"] == dup_id), None)

            if bug_record:

                bug_record["occurrences"] = bug_record.get("occurrences", 1) + 1

                bug_record["last_seen"] = now_date

                bug_id = dup_id

                # 核心改进：若命中了已关闭/误报屏蔽的历史已知问题，直接静默阻断，不落盘产生新Bug快照

                is_closed = bug_record.get("status") in ("已关闭", "误报")

                is_noise = "误报" in str(bug_record.get("tags", [])) or "误报" in str(bug_record.get("analysis_notes", ""))

                if is_closed or is_noise:

                    logger.info(f"🛡️ [Silent Suppress] 该异常命中历史已关闭/误报屏蔽条目 [{dup_id}]，已同步复现频次并静默屏蔽，不生成新 Bug 档案。")

                    self._save_globals()

                    return dup_id

            else:

                # 极端异常情况：查到了 ID 但库里找不到

                bug_id = self._create_new_bug(run_id, title, step_prompt, actual_result, now_date)

                bug_record = self.global_bugs[-1]

        else:

            bug_id = self._create_new_bug(run_id, title, step_prompt, actual_result, now_date)

            bug_record = self.global_bugs[-1]

        # 2. 将案发现场截图复制一份到专属目录，实现物理隔离，防止 logs 被清理

        new_img_path = None

        if crash_image_path and Path(crash_image_path).exists():

            img_suffix = Path(crash_image_path).suffix

            new_img_path = run_dir / f"{bug_id}{img_suffix}"

            if new_img_path.exists():

                timestamp = datetime.now().strftime("%H%M%S")

                new_img_path = run_dir / f"{bug_id}_{timestamp}{img_suffix}"

            try:

                import shutil

                shutil.copy2(crash_image_path, new_img_path)

                if bug_record:

                    bug_record["screenshot"] = str(new_img_path).replace('\\', '/')

            except Exception as e:

                logger.warning(f"复制案发现场截图失败: {e}")

                new_img_path = None

        before_image_path = before_image_path or kwargs.get("before_image_path")
        new_before_img_path = None
        if before_image_path and Path(before_image_path).exists():
            b_suffix = Path(before_image_path).suffix or ".png"
            new_before_img_path = run_dir / f"{bug_id}_before{b_suffix}"
            if new_before_img_path.exists():
                b_timestamp = datetime.now().strftime("%H%M%S")
                new_before_img_path = run_dir / f"{bug_id}_{b_timestamp}_before{b_suffix}"
            try:
                import shutil
                shutil.copy2(before_image_path, new_before_img_path)
                if bug_record:
                    bug_record["before_screenshot"] = str(new_before_img_path).replace('\\', '/')
            except Exception as e:
                logger.warning(f"复制操作前现场截图失败: {e}")
                new_before_img_path = None
        elif bug_record and new_img_path:
            # 本次复现仅提供了 1 张出错现场图：成套替换，清空上一次遗留的旧操作前截图
            bug_record["before_screenshot"] = None

        # 提取与智能推导元数据字段 (action_type, target_element, ui_path, tags, global_step, severity)

        action_type = kwargs.get("action_type")

        target_element = kwargs.get("target_element")

        ui_path = kwargs.get("ui_path")

        global_step = kwargs.get("global_step")

        from utils.bug_enricher import normalize_severity_label
        severity = normalize_severity_label(kwargs.get("severity", "Medium"))

        tags = kwargs.get("tags")

        analysis_notes = kwargs.get("analysis_notes", "")

        import re

        if not action_type or not target_element or not ui_path:

            m = re.search(r"\[([A-Z_]+)\]\s*(?:交互目标[:：]\s*)?['\"]?(.*?)['\"]?\s*(?:\((?:页面路径[:：]\s*)?(.*?)\))?$", step_prompt)

            if m:

                if not action_type: action_type = m.group(1).strip()

                if not target_element: target_element = m.group(2).strip()

                if not ui_path and m.group(3): ui_path = m.group(3).strip()

        if not tags:

            auto_tags = []

            if action_type: auto_tags.append(action_type)

            if ui_path and ui_path != "无": auto_tags.extend([p.strip() for p in ui_path.split("->") if p.strip()])

            if target_element:

                for k in ["一级菜单", "二级菜单", "按钮", "图表", "弹窗", "折线图", "柱状图", "表格"]:

                    if k in target_element and k not in auto_tags: auto_tags.append(k)

            tags = list(dict.fromkeys(auto_tags)) if auto_tags else ["常规交互"]

        # Ensure run_id and metadata in bug_record is always up to date

        if bug_record:

            bug_record["run_id"] = run_id

            if dup_id:
                # 1. 首发元数据冷冻：若尚未记录首次触发信息，保留首发静态画像
                if "first_step" not in bug_record:
                    bug_record["first_step"] = bug_record.get("step") or step_prompt
                    bug_record["first_ui_path"] = bug_record.get("ui_path") or ui_path
                    bug_record["first_target_element"] = bug_record.get("target_element") or target_element
                    bug_record["first_screenshot"] = bug_record.get("screenshot")
                    bug_record["first_run_id"] = bug_record.get("first_run_id") or bug_record.get("run_id")

                # 2. 时序时间轴追加 (保留最近 10 次复现踪迹)
                now_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                history_item = {
                    "run_id": run_id,
                    "timestamp": now_time_str,
                    "step": step_prompt,
                    "ui_path": ui_path,
                    "target_element": target_element,
                    "action_type": action_type,
                    "actual_error": actual_result,
                    "global_step": global_step,
                    "screenshot": str(new_img_path).replace('\\', '/') if new_img_path else None,
                    "before_screenshot": str(new_before_img_path).replace('\\', '/') if new_before_img_path else None
                }
                rec_history = bug_record.get("recurrence_history", [])
                if not isinstance(rec_history, list):
                    rec_history = []
                rec_history.append(history_item)
                bug_record["recurrence_history"] = rec_history[-10:]

                # 3. 核心升级：每次新复现，彻底热刷新主视图为最新案发现场！
                bug_record["step"] = step_prompt
                bug_record["actual"] = actual_result
                if ui_path: bug_record["ui_path"] = ui_path
                mods = list(bug_record.get("affected_modules") or [])
                for cand_m in (bug_record.get("first_ui_path"), ui_path):
                    cm = str(cand_m or "").strip()
                    if cm and cm not in ("无", "未知", "未知路径", "未指定") and cm not in mods:
                        mods.append(cm)
                if mods:
                    bug_record["affected_modules"] = mods
                if target_element: bug_record["target_element"] = target_element
                if action_type: bug_record["action_type"] = action_type
                if global_step:
                    bug_record["last_recurrence_step"] = global_step
                    bug_record["global_step"] = global_step
                if new_img_path:
                    bug_record["screenshot"] = str(new_img_path).replace('\\', '/')
                    bug_record["before_screenshot"] = (
                        str(new_before_img_path).replace('\\', '/') if new_before_img_path else None
                    )
                elif new_before_img_path:
                    bug_record["before_screenshot"] = str(new_before_img_path).replace('\\', '/')

            else:

                if action_type: bug_record["action_type"] = action_type

                if target_element: bug_record["target_element"] = target_element

                if ui_path: bug_record["ui_path"] = ui_path

                if global_step: bug_record["global_step"] = global_step

            if tags and not bug_record.get("tags"): bug_record["tags"] = tags

            if severity: bug_record["severity"] = severity

            if analysis_notes: bug_record["analysis_notes"] = analysis_notes

        # 3. 创建单次运行的 JSON 详细报告

        bug_detail = {

            "id": bug_id,

            "title": title,

            "severity": severity,

            "status": "激活",     # 默认状态

            "assignee": bug_record.get("assignee", "Unassigned") if bug_record else "Unassigned",

            "creation_date": now_date,

            "details": {

                "step": step_prompt,

                "expected": "执行该操作时不应报错，界面按预期进行交互或跳转",

                "actual": actual_result,

            },

            "crash_screenshot": str(new_img_path) if new_img_path else None,

            "before_screenshot": str(new_before_img_path).replace('\\', '/') if new_before_img_path else None,

            "action_type": action_type or "无",

            "target_element": target_element or "无",

            "ui_path": ui_path or "无",

            "global_step": global_step,

            "tags": tags or [],

            "analysis_notes": analysis_notes

        }

        detail_path = run_dir / f"{bug_id}.json"

        if detail_path.exists():

            timestamp = datetime.now().strftime("%H%M%S")

            detail_path = run_dir / f"{bug_id}_{timestamp}.json"

        with open(detail_path, "w", encoding="utf-8") as f:

            json.dump(bug_detail, f, ensure_ascii=False, indent=2)

        # 4. DB-First: 立即事务性同步落库 SQLite
        try:
            from utils.bug_db_sync import save_bug_to_db
            db_payload = {
                "id": bug_id,
                "run_id": run_id,
                "app": self.active_app,
                "title": title,
                "severity": severity,
                "status": bug_record.get("status", "激活") if bug_record else "激活",
                "assignee": bug_record.get("assignee", "Unassigned") if bug_record else "Unassigned",
                "zentao_id": bug_record.get("zentao_id") if bug_record else None,
                "ui_path": ui_path,
                "target_element": target_element,
                "step": step_prompt,
                "action_type": action_type,
                "tags": tags,
                "actual_error": actual_result,
                "analysis_notes": bug_record.get("analysis_notes") if bug_record else analysis_notes,
                "remark": bug_record.get("remark") if bug_record else None,
                "screenshot": str(new_img_path).replace('\\', '/') if new_img_path else None,
                "before_screenshot": str(new_before_img_path).replace('\\', '/') if new_before_img_path else None,
                "occurrences": bug_record.get("occurrences", 1) if bug_record else 1,
                "details": bug_detail.get("details"),
                "global_step": global_step,
                "date": now_date,
                "recurrence_history": bug_record.get("recurrence_history", []) if bug_record else [],
                "affected_modules": bug_record.get("affected_modules", []) if bug_record else ([ui_path] if ui_path else []),
                "first_step": bug_record.get("first_step") if bug_record else None,
                "first_ui_path": bug_record.get("first_ui_path") if bug_record else None,
                "first_screenshot": bug_record.get("first_screenshot") if bug_record else None,
            }
            save_bug_to_db(db_payload)
        except Exception as dbe:
            logger.warning(f"DB-First 入库异常 (已自动降级保全本地文件): {dbe}")

        # 4. 同步更新三大全局大盘

        self._save_globals()

        logger.info(f"✅ 缺陷报告固化完毕: {detail_path}")

        logger.info("=" * 60)

        # 5. 严格保证时序：必须在单次缺陷文件与全局库 100% 完全写入闭环落盘后，才启动后台异步分析，杜绝读写冲突
        # 方案 B 核心：无论是新 Bug 还是重复 Bug 复现，只要未传入硬编码分析，均触发后台异步 AI 智能深度初诊与热刷新
        if not analysis_notes:
            self._start_async_analysis(
                bug_id=bug_id,
                detail_path=detail_path,
                title=title,
                step_prompt=step_prompt,
                actual_result=actual_result,
                ui_path=ui_path,
                crash_image_path=str(new_img_path) if new_img_path else None,
                is_recurrent=bool(dup_id),
                occurrences=bug_record.get("occurrences", 1) if bug_record else 1
            )

        return bug_id

    def _create_new_bug(self, run_id, title, step, actual, date):

        # 自动生成全平台全局唯一递增 ID（跨所有矿山 JSON 库 + SQLite 主键表取最大序号 + 1，杜绝跨项目撞号或删单回退撞号）

        date_prefix = datetime.now().strftime("%Y%m%d")
        id_prefix = f"BUG-{date_prefix}-"
        max_num = 0

        def _extract_seq(bid: str) -> int:
            if not bid or not str(bid).startswith(id_prefix):
                return 0
            tail = str(bid)[len(id_prefix):]
            return int(tail) if tail.isdigit() else 0

        for b in self.global_bugs:
            max_num = max(max_num, _extract_seq(b.get("id", "")))

        try:
            for g_file in self.global_bugs_file.parent.glob("global_bugs*.json"):
                try:
                    g_list = json.loads(g_file.read_text(encoding="utf-8"))
                    if isinstance(g_list, list):
                        for gb in g_list:
                            max_num = max(max_num, _extract_seq(gb.get("id", "")))
                except Exception:
                    pass
        except Exception:
            pass

        try:
            from server.database import SessionLocal
            from server.models import BugRecord
            _db = SessionLocal()
            try:
                rows = _db.query(BugRecord.id).filter(BugRecord.id.like(f"{id_prefix}%")).all()
                for (row_id,) in rows:
                    max_num = max(max_num, _extract_seq(row_id))
            finally:
                _db.close()
        except Exception:
            pass

        next_num = max_num + 1

        bug_id = f"BUG-{date_prefix}-{next_num:03d}"

        new_bug = {

            "id": bug_id,

            "run_id": run_id,

            "title": title,

            "severity": "Medium",

            "status": "激活",

            "date": date,

            "occurrences": 1,

            "last_seen": date,

            "step": step,

            "actual": actual,

            "app": self.active_app,

            "assignee": "Unassigned"

        }

        self.global_bugs.append(new_bug)

        return bug_id

    def _check_duplicate(self, step_prompt: str, actual_result: str, ui_path: str = None, target_element: str = None) -> str:

        """调用大模型查重，返回重复的 Bug ID，如果是新 Bug 则返回 None"""

        if not self.global_bugs:

            return None

        # 1. 筛选近期激活或未解决的 Bug（为了省 token，只传前 25 个未关闭的）

        active_bugs = [b for b in self.global_bugs if b.get("status") not in ("已关闭", "误报")][-25:]

        # 2. 筛选已关闭或标记为误报屏蔽的历史已知条目（最多取最近 20 个，用于防范历史误报再次被当作新Bug）

        closed_or_noise_bugs = [

            b for b in self.global_bugs 

            if b.get("status") in ("已关闭", "误报") or "误报" in str(b.get("tags", [])) or "误报" in str(b.get("analysis_notes", ""))

        ][-20:]

        candidate_bugs = active_bugs + [b for b in closed_or_noise_bugs if b not in active_bugs]

        if not candidate_bugs:

            return None

        bugs_context = json.dumps(candidate_bugs, ensure_ascii=False, indent=2)

        system_prompt = (

            "你是一个专业的测试架构师，负责进行缺陷查重 (Bug Deduplication)。\n"

            "用户会提供一个【新的崩溃报错】（包含执行的步骤和实际报错结果）。\n"

            "你需要将其与【全局 Bug 库】中已有的缺陷进行对比判定。\n"

            "【注意】：全局 Bug 库中包含【激活中】的问题以及【已关闭/误报屏蔽】的历史已知问题。\n"

            "如果这个新崩溃的核心原因和某个已存在的 Bug 是同一个（比如同样是在同一模块找不到同一个元素，或者同样的静态资源404、同样的服务端接口500、或者同一页面内点击不同列表条目/文件行触发的同一底层 JS 报错如 crypto.randomUUID is not a function），请判定为重复，并返回该老 Bug 的 ID。\n"

            "【跨页面全局技术报错可合并】：若属于与具体业务无关的全局公共库/浏览器运行时错误（如相同的 `[page_error]` 堆栈 `crypto.randomUUID is not a function`、`ChunkLoadError` 或相同的静态资源 404），即使出现在不同 `ui_path` 页面，也可合并到同一根因老 Bug。\n"

            "【严禁跨业务模块误合并铁律】：对于业务强绑定的报错——包括不同页面路径（ui_path）、不同业务模块/卡片/表格、不同接口名的报错（尤其是 UI 数据与接口不匹配 MISMATCH 类问题、图表核验、物理常识异常，如‘隐患整改反馈’ vs ‘异常报警’），即使报错模式相似，也绝对不能判定为重复！\n"

            "特别地，如果匹配到了【已关闭】或【误报屏蔽】的已知历史条目，也必须判定为重复并返回对应的 ID！\n"

            "如果这是一个全新的问题，请判定为不重复。\n"

            "你必须且只能返回合法的 JSON 对象，格式要求：\n"

            "{\"is_duplicate\": true/false, \"duplicate_id\": \"对应的Bug ID，如果没有则是null\", \"reason\": \"你的判定理由\"}\n"

            "不要输出任何 Markdown 标识符。"

        )

        user_prompt = (

            f"【全局 Bug 库候选条目】：\n{bugs_context}\n\n"

            f"【新的崩溃报错】：\n"

            f"- 所属页面路径 (ui_path): {ui_path or '未指定'}\n"

            f"- 目标交互元素 (target_element): {target_element or '未指定'}\n"

            f"- 执行步骤: {step_prompt}\n"

            f"- 报错结果: {actual_result}\n\n"

            "请判定是否为重复 Bug。"

        )

        try:

            logger.info("🧠 正在请大模型进行智能缺陷查重...")

            # 注意：此处不传 base64_image，纯文本分析

            result = self.vision._call_llm(

                system_prompt=system_prompt,

                user_prompt=user_prompt

            )

            is_dup = result.get("is_duplicate", False)

            dup_id = result.get("duplicate_id")

            reason = result.get("reason", "无")

            if is_dup and dup_id:
                # 代码级硬防呆：若新旧 Bug 均明确带有 ui_path 且所属页面路径不同，拦截跨模块误合并
                def _norm_ui_path(p: str) -> str:
                    if not p:
                        return ""
                    s = str(p).strip()
                    for prefix in ("路径:", "路径：", "页面路径:", "页面路径："):
                        if s.startswith(prefix):
                            s = s[len(prefix):].strip()
                    return "" if s in ("无", "未知路径", "首页", "未指定") else s

                new_p = _norm_ui_path(ui_path)
                old_bug = next((b for b in candidate_bugs if b.get("id") == dup_id), None)
                old_p = _norm_ui_path(old_bug.get("ui_path") if old_bug else "")
                old_actual = str(old_bug.get("actual") or old_bug.get("actual_error") or "") if old_bug else ""
                new_actual = str(actual_result or "")

                def _is_global_shared_js_error(a: str, b: str) -> bool:
                    """仅当新旧报错均为全局公共 JS 运行时/资源加载错误，或命中完全相同的后端接口 URL + 业务报错时，才允许跨 ui_path 合并"""
                    global_markers = (
                        "crypto.randomUUID",
                        "ChunkLoadError",
                        "Loading chunk",
                        "ERR_CONNECTION_REFUSED",
                    )
                    if any(m in a and m in b for m in global_markers):
                        return True
                    # 同为 [page_error] 且剥离前缀后核心报错文本完全一致
                    if "[page_error]" in a and "[page_error]" in b:
                        core_a = a.split("[page_error]", 1)[1].strip().splitlines()[0].strip()
                        core_b = b.split("[page_error]", 1)[1].strip().splitlines()[0].strip()
                        if core_a and core_a == core_b:
                            return True
                    # 同为 [api_biz_error] 且命中相同的底层接口 URL（如公共组件/悬浮入口接口报错）
                    if "[api_biz_error]" in a and "[api_biz_error]" in b:
                        urls_a = set(re.findall(r"URL:\s*([^\s,\)]+)", a))
                        urls_b = set(re.findall(r"URL:\s*([^\s,\)]+)", b))
                        if urls_a and urls_b and (urls_a & urls_b):
                            return True
                    return False

                if new_p and old_p and new_p != old_p and not _is_global_shared_js_error(new_actual, old_actual):
                    logger.warning(f"🛡️ [Deduplicate Guard] 拦截跨模块误合并: 新报错路径 '{new_p}' != 候选 Bug [{dup_id}] 路径 '{old_p}'，按新 Bug 处理。")
                    return None

                logger.info(f"💡 查重理由: {reason}")

                return dup_id

        except Exception as e:

            logger.warning(f"智能查重请求失败，将按新 Bug 处理: {e}")

        return None

    def _save_globals(self):

        with self._lock:

            with open(self.global_json, "w", encoding="utf-8") as f:

                json.dump(self.global_bugs, f, ensure_ascii=False, indent=2)

    def _start_async_analysis(
        self,
        bug_id: str,
        detail_path: Path,
        title: str,
        step_prompt: str,
        actual_result: str,
        ui_path: str,
        crash_image_path: str = None,
        is_recurrent: bool = False,
        occurrences: int = 1,
    ):
        """
        启动后台守护线程进行 AI 智能初诊，绝不阻塞主测试探索流程。
        前提保障：调用此方法时，单次 Bug JSON 与全局 Bug 库均已完全完成磁盘写入与落盘。
        """
        thread = threading.Thread(
            target=self._async_analyze_worker,
            args=(bug_id, Path(detail_path), title, step_prompt, actual_result, ui_path, crash_image_path, is_recurrent, occurrences),
            daemon=True,
            name=f"BugAnalysis-{bug_id}"
        )
        thread.start()

    def _async_analyze_worker(
        self,
        bug_id: str,
        detail_path: Path,
        title: str,
        step_prompt: str,
        actual_result: str,
        ui_path: str,
        crash_image_path: str = None,
        is_recurrent: bool = False,
        occurrences: int = 1,
    ):
        """后台异步执行大模型研发级深度根因诊断并静默回填缺陷归因备注（线程安全）"""
        try:
            from config.settings import settings
            analysis_model = getattr(settings, "llm_bug_analysis_model", None) or self.vision.model
            log_desc = f"复现缺陷 (第 {occurrences} 次)" if is_recurrent else "新缺陷"
            logger.info(f"🧠 [AI 智能初诊] 开始异步分析{log_desc} [{bug_id}] (分析模型: {analysis_model})...")

            from utils.bug_analysis_expert import analyze_bug_expertly
            bug_dict = {
                "id": bug_id,
                "title": title,
                "step": step_prompt,
                "actual": actual_result,
                "ui_path": ui_path,
                "app": self.active_app,
                "screenshot": crash_image_path,
                "occurrences": occurrences,
            }
            formatted_notes, res_dict = analyze_bug_expertly(
                agent=self.vision,
                model=analysis_model,
                bug=bug_dict,
                crash_image_path=crash_image_path,
                app_key=self.active_app
            )

            # 智能推断责任人 (前端: 陈贻雄 / 后端: 梅本霞)
            resolved_assignee = None
            try:
                from utils.zentao_sync import resolve_bug_assignee
                temp_bug = {
                    "title": title,
                    "step": step_prompt,
                    "actual": actual_result,
                    "analysis_notes": formatted_notes,
                }
                resolved_assignee, _, _ = resolve_bug_assignee(temp_bug)
            except Exception:
                pass

            # 回填更新本地单次运行 json 与全局缺陷库（线程互斥保护，防止写入冲突）
            with self._lock:
                if detail_path.exists():
                    try:
                        with open(detail_path, "r", encoding="utf-8") as f:
                            d_json = json.load(f)
                        existing_d_notes = d_json.get("analysis_notes", "")
                        if "已关闭误报" in existing_d_notes:
                            d_json["analysis_notes"] = f"{existing_d_notes}\n\n---\n**【第 {occurrences} 次复现最新 AI 初诊】**\n{formatted_notes}"
                        else:
                            d_json["analysis_notes"] = formatted_notes
                        if resolved_assignee and d_json.get("assignee") in ("Unassigned", "", None):
                            d_json["assignee"] = resolved_assignee
                        with open(detail_path, "w", encoding="utf-8") as f:
                            json.dump(d_json, f, ensure_ascii=False, indent=2)
                    except Exception as fe:
                        logger.warning(f"回填运行目录 Bug 文件失败 ({detail_path.name}): {fe}")

                final_notes = formatted_notes
                for b in self.global_bugs:
                    if b.get("id") == bug_id:
                        existing_notes = b.get("analysis_notes", "")
                        if "已关闭误报" in existing_notes or b.get("status") in ("已关闭", "误报"):
                            final_notes = f"{existing_notes}\n\n---\n**【第 {occurrences} 次复现最新 AI 初诊】**\n{formatted_notes}"
                            b["analysis_notes"] = final_notes
                        else:
                            b["analysis_notes"] = formatted_notes
                            final_notes = formatted_notes
                        if resolved_assignee and b.get("assignee") in ("Unassigned", "", None):
                            b["assignee"] = resolved_assignee
                        break

                with open(self.global_json, "w", encoding="utf-8") as f:
                    json.dump(self.global_bugs, f, ensure_ascii=False, indent=2)

            # 同步更新数据库初诊与责任人
            try:
                from utils.bug_db_sync import save_bug_to_db
                save_bug_to_db({
                    "id": bug_id,
                    "analysis_notes": final_notes,
                    "assignee": resolved_assignee
                })
            except Exception as dbe:
                logger.debug(f"更新初诊信息到数据库跳过: {dbe}")

            assignee_str = f"，责任人已指派至: 【{resolved_assignee}】" if resolved_assignee else ""
            logger.info(f"✨ [AI 智能初诊完成] 已成功为缺陷 [{bug_id}] 回填最新排查思路{assignee_str}！")

        except Exception as e:
            logger.warning(f"⚠️ [AI 智能初诊跳过] 后台异步分析缺陷 [{bug_id}] 发生异常 (不影响测试运行): {e}")

