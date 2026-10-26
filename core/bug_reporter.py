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

    def report_bug(self, run_id: str, title: str, step_prompt: str, actual_result: str, crash_image_path: str = None, **kwargs):
        """记录一个新的崩溃现场，自动查重并保存。支持扩展参数。"""
        logger.info("=" * 60)
        logger.info(f"🐞 捕获到缺陷异常，开始生成 Bug 报告...")
        
        # 1. 智能查重
        dup_id = self._check_duplicate(step_prompt, actual_result)
        
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
                is_closed = bug_record.get("status") == "已关闭"
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

        # 提取与智能推导元数据字段 (action_type, target_element, ui_path, tags, global_step, severity)
        action_type = kwargs.get("action_type")
        target_element = kwargs.get("target_element")
        ui_path = kwargs.get("ui_path")
        global_step = kwargs.get("global_step")
        severity = kwargs.get("severity", "Medium")
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
                # 查重合并时：保持首次触发该 Bug 的核心元数据（首发动作与首发步数）不变，仅记录最新复现步数
                if global_step:
                    bug_record["last_recurrence_step"] = global_step
                if "global_step" not in bug_record or not bug_record["global_step"]:
                    bug_record["global_step"] = global_step
                if "target_element" not in bug_record or not bug_record["target_element"]:
                    bug_record["target_element"] = target_element
                if "action_type" not in bug_record or not bug_record["action_type"]:
                    bug_record["action_type"] = action_type
                if "ui_path" not in bug_record or not bug_record["ui_path"]:
                    bug_record["ui_path"] = ui_path
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
            
        # 4. 同步更新三大全局大盘
        self._save_globals()
        
        logger.info(f"✅ 缺陷报告固化完毕: {detail_path}")
        logger.info("=" * 60)

        # 5. 严格保证时序：必须在单次缺陷文件与全局库 100% 完全写入闭环落盘后，才启动后台异步分析，杜绝读写冲突
        if not dup_id and not analysis_notes:
            self._start_async_analysis(
                bug_id=bug_id,
                detail_path=detail_path,
                title=title,
                step_prompt=step_prompt,
                actual_result=actual_result,
                ui_path=ui_path,
                crash_image_path=str(new_img_path) if new_img_path else None
            )

        return bug_id

    def _create_new_bug(self, run_id, title, step, actual, date):
        # 自动生成递增 ID
        date_prefix = datetime.now().strftime("%Y%m%d")
        todays_bugs = [b for b in self.global_bugs if b["id"].startswith(f"BUG-{date_prefix}")]
        next_num = len(todays_bugs) + 1
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

    def _check_duplicate(self, step_prompt: str, actual_result: str) -> str:
        """调用大模型查重，返回重复的 Bug ID，如果是新 Bug 则返回 None"""
        if not self.global_bugs:
            return None
            
        # 1. 筛选近期激活或未解决的 Bug（为了省 token，只传前 25 个未关闭的）
        active_bugs = [b for b in self.global_bugs if b.get("status") != "已关闭"][-25:]
        # 2. 筛选已关闭或标记为误报屏蔽的历史已知条目（最多取最近 20 个，用于防范历史误报再次被当作新Bug）
        closed_or_noise_bugs = [
            b for b in self.global_bugs 
            if b.get("status") == "已关闭" or "误报" in str(b.get("tags", [])) or "误报" in str(b.get("analysis_notes", ""))
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
            "如果这个新崩溃的核心原因和某个已存在的 Bug 是同一个（比如同样是在某个模块找不到某个元素，或者同样的静态资源404、同样的服务端接口500），请判定为重复，并返回该老 Bug 的 ID。\n"
            "特别地，如果匹配到了【已关闭】或【误报屏蔽】的已知历史条目，也必须判定为重复并返回对应的 ID！\n"
            "如果这是一个全新的问题，请判定为不重复。\n"
            "你必须且只能返回合法的 JSON 对象，格式要求：\n"
            "{\"is_duplicate\": true/false, \"duplicate_id\": \"对应的Bug ID，如果没有则是null\", \"reason\": \"你的判定理由\"}\n"
            "不要输出任何 Markdown 标识符。"
        )
        
        user_prompt = (
            f"【全局 Bug 库候选条目】：\n{bugs_context}\n\n"
            f"【新的崩溃报错】：\n"
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
                logger.info(f"💡 查重理由: {reason}")
                return dup_id
        except Exception as e:
            logger.warning(f"智能查重请求失败，将按新 Bug 处理: {e}")
            
        return None

    def _save_globals(self):
        with self._lock:
            with open(self.global_json, "w", encoding="utf-8") as f:
                json.dump(self.global_bugs, f, ensure_ascii=False, indent=2)

    def _start_async_analysis(self, bug_id: str, detail_path: Path, title: str, step_prompt: str, actual_result: str, ui_path: str, crash_image_path: str = None):
        """
        启动后台守护线程进行 AI 智能初诊，绝不阻塞主测试探索流程。
        前提保障：调用此方法时，单次 Bug JSON 与全局 Bug 库均已完全完成磁盘写入与落盘。
        """
        thread = threading.Thread(
            target=self._async_analyze_worker,
            args=(bug_id, Path(detail_path), title, step_prompt, actual_result, ui_path, crash_image_path),
            daemon=True,
            name=f"BugAnalysis-{bug_id}"
        )
        thread.start()

    def _async_analyze_worker(self, bug_id: str, detail_path: Path, title: str, step_prompt: str, actual_result: str, ui_path: str, crash_image_path: str = None):
        """后台异步执行大模型根因诊断并静默回填缺陷归因备注（线程安全）"""
        try:
            from config.settings import settings
            analysis_model = getattr(settings, "llm_bug_analysis_model", None) or self.vision.model
            logger.info(f"🧠 [AI 智能初诊] 开始异步分析新缺陷 [{bug_id}] (分析模型: {analysis_model})...")

            system_prompt = (
                "你是一个资深的端到端 UI 自动化测试专家与全栈排查架构师。\n"
                "当测试框架捕获到一个新的缺陷（包括网络异常、控制台报错或断言冲突）时，请结合步骤、路径、报错日志以及案发现场截图，进行客观、严谨、精炼的【AI 智能初诊与排查指引】。\n"
                "你必须且只能返回合法的 JSON 对象，格式要求：\n"
                "{\n"
                '  "category": "缺陷定位与表现（如：页面白屏 / 前端组件报错 / 网络接口 404/500 / UI与数据报文不符）",\n'
                '  "root_cause": "核心疑点与推断根因（提取最关键的报错线索如 URL、状态码、字段名，推断可能的技术原因）",\n'
                '  "troubleshooting": "建议排查方向（建议找哪端开发，如前端大屏/后端微服务/流媒体，以及人工复核时的关注点）"\n'
                "}\n"
                "不要输出任何 Markdown 标识符。"
            )

            user_prompt = (
                f"【缺陷基本信息】\n"
                f"- 缺陷编号: {bug_id}\n"
                f"- 缺陷标题: {title}\n"
                f"- 交互步骤: {step_prompt}\n"
                f"- 业务路径: {ui_path}\n"
                f"- 实际报错详情:\n{actual_result}\n\n"
                "请输出针对该缺陷的结构化初诊分析 JSON。"
            )

            base64_img = None
            if crash_image_path and Path(crash_image_path).exists():
                try:
                    with open(crash_image_path, "rb") as f:
                        base64_img = base64.b64encode(f.read()).decode("utf-8")
                except Exception as ie:
                    logger.debug(f"读取缺陷截图 base64 失败 (将降级为纯文本分析): {ie}")

            result = self.vision._call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                base64_image=base64_img,
                model=analysis_model
            )

            category = result.get("category", "待定")
            root_cause = result.get("root_cause", "暂无推断根因")
            troubleshooting = result.get("troubleshooting", "暂无排查建议")

            formatted_notes = (
                f"🤖【AI 智能初诊与排查指引】\n"
                f"1. 缺陷定位与表现：{category}\n"
                f"2. 核心疑点与推断根因：{root_cause}\n"
                f"3. 建议排查方向：{troubleshooting}"
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
                        # 仅在尚未有人工写入备注时才回填
                        if not d_json.get("analysis_notes"):
                            d_json["analysis_notes"] = formatted_notes
                        if resolved_assignee and d_json.get("assignee") in ("Unassigned", "", None):
                            d_json["assignee"] = resolved_assignee
                        with open(detail_path, "w", encoding="utf-8") as f:
                            json.dump(d_json, f, ensure_ascii=False, indent=2)
                    except Exception as fe:
                        logger.warning(f"回填运行目录 Bug 文件失败 ({detail_path.name}): {fe}")

                for b in self.global_bugs:
                    if b.get("id") == bug_id:
                        if not b.get("analysis_notes"):
                            b["analysis_notes"] = formatted_notes
                        if resolved_assignee and b.get("assignee") in ("Unassigned", "", None):
                            b["assignee"] = resolved_assignee
                        break
                with open(self.global_json, "w", encoding="utf-8") as f:
                    json.dump(self.global_bugs, f, ensure_ascii=False, indent=2)

            assignee_str = f"，责任人已指派至: 【{resolved_assignee}】" if resolved_assignee else ""
            logger.info(f"✨ [AI 智能初诊完成] 已成功为新缺陷 [{bug_id}] 回填排查思路{assignee_str}！")

        except Exception as e:
            logger.warning(f"⚠️ [AI 智能初诊跳过] 后台异步分析缺陷 [{bug_id}] 发生异常 (不影响测试运行): {e}")

