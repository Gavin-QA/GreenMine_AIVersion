import os
import json
import csv
import shutil
import logging
from datetime import datetime
from pathlib import Path

from core.vision.agent import VisionAgent

logger = logging.getLogger("core.bug_reporter")


class BugReporter:
    def __init__(self, vision_agent=None):
        self.bugs_dir = Path("bugs")
        self.bugs_dir.mkdir(exist_ok=True)
        self.global_json = self.bugs_dir / "global_bugs.json"
        self.global_md = self.bugs_dir / "global_bugs.md"
        self.global_csv = self.bugs_dir / "global_bugs.csv"
        
        # 允许外部传入已有的 VisionAgent，若没有则自己实例化一个用于 LLM 推理
        self.vision = vision_agent if vision_agent else VisionAgent()
        
        # Load global bugs
        self.global_bugs = []
        if self.global_json.exists():
            try:
                with open(self.global_json, "r", encoding="utf-8") as f:
                    self.global_bugs = json.load(f)
            except Exception as e:
                logger.error(f"无法读取全局 Bug 库: {e}")

    def report_bug(self, run_id: str, title: str, step_prompt: str, actual_result: str, crash_image_path: str = None):
        """记录一个新的崩溃现场，自动查重并保存。"""
        logger.info("=" * 60)
        logger.info(f"🐞 捕获到缺陷异常，开始生成 Bug 报告...")
        
        # 1. 智能查重
        dup_id = self._check_duplicate(step_prompt, actual_result)
        
        run_dir = self.bugs_dir / run_id
        run_dir.mkdir(exist_ok=True)
        
        now_date = datetime.now().strftime("%Y-%m-%d")
        
        if dup_id:
            logger.info(f"🔍 发现重复缺陷，将追加复现记录到历史 Bug: [{dup_id}]")
            bug_record = next((b for b in self.global_bugs if b["id"] == dup_id), None)
            if bug_record:
                bug_record["occurrences"] = bug_record.get("occurrences", 1) + 1
                bug_record["last_seen"] = now_date
                bug_id = dup_id
            else:
                # 极端异常情况：查到了 ID 但库里找不到
                bug_id = self._create_new_bug(title, step_prompt, actual_result, now_date)
        else:
            bug_id = self._create_new_bug(title, step_prompt, actual_result, now_date)
            logger.info(f"✨ 确认是全新问题，新建缺陷档案: [{bug_id}]")
            
        # 2. 将案发现场截图复制一份到专属目录，实现物理隔离，防止 logs 被清理
        new_img_path = None
        if crash_image_path and Path(crash_image_path).exists():
            # 兼容带有时间戳的文件名，或者统一用 bug_id.png
            img_suffix = Path(crash_image_path).suffix
            new_img_path = run_dir / f"{bug_id}{img_suffix}"
            if new_img_path.exists():
                timestamp = datetime.now().strftime("%H%M%S")
                new_img_path = run_dir / f"{bug_id}_{timestamp}{img_suffix}"
            try:
                shutil.copy2(crash_image_path, new_img_path)
            except Exception as e:
                logger.warning(f"复制案发现场截图失败: {e}")
                new_img_path = None
                
        # 3. 创建单次运行的 JSON 详细报告
        bug_detail = {
            "id": bug_id,
            "title": title,
            "severity": "Medium", # 默认严重级别
            "status": "激活",     # 默认状态
            "creation_date": now_date,
            "details": {
                "step": step_prompt,
                "expected": "执行该操作时不应报错，界面按预期进行交互或跳转",
                "actual": actual_result,
            },
            "crash_screenshot": str(new_img_path) if new_img_path else None
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
        return bug_id

    def _create_new_bug(self, title, step, actual, date):
        # 自动生成递增 ID
        date_prefix = datetime.now().strftime("%Y%m%d")
        todays_bugs = [b for b in self.global_bugs if b["id"].startswith(f"BUG-{date_prefix}")]
        next_num = len(todays_bugs) + 1
        bug_id = f"BUG-{date_prefix}-{next_num:03d}"
        
        new_bug = {
            "id": bug_id,
            "title": title,
            "severity": "Medium",
            "status": "激活",
            "date": date,
            "occurrences": 1,
            "last_seen": date,
            "step": step,
            "actual": actual
        }
        self.global_bugs.append(new_bug)
        return bug_id

    def _check_duplicate(self, step_prompt: str, actual_result: str) -> str:
        """调用大模型查重，返回重复的 Bug ID，如果是新 Bug 则返回 None"""
        if not self.global_bugs:
            return None
            
        # 筛选近期激活或未解决的 Bug（为了省 token，只传前 20 个未关闭的）
        active_bugs = [b for b in self.global_bugs if b["status"] != "已关闭"][-20:]
        if not active_bugs:
            return None
            
        bugs_context = json.dumps(active_bugs, ensure_ascii=False, indent=2)
        
        system_prompt = (
            "你是一个专业的测试架构师，负责进行缺陷查重 (Bug Deduplication)。\n"
            "用户会提供一个【新的崩溃报错】（包含执行的步骤和实际报错结果）。\n"
            "你需要将其与【全局 Bug 库】中已有的缺陷进行对比判定。\n"
            "如果这个新崩溃的核心原因和某个已存在的 Bug 是同一个（比如同样是在某个模块找不到某个元素，或者同样的网络接口报错），请判定为重复，并返回该老 Bug 的 ID。\n"
            "如果这是一个全新的问题，请判定为不重复。\n"
            "你必须且只能返回合法的 JSON 对象，格式要求：\n"
            "{\"is_duplicate\": true/false, \"duplicate_id\": \"对应的Bug ID，如果没有则是null\", \"reason\": \"你的判定理由\"}\n"
            "不要输出任何 Markdown 标识符。"
        )
        
        user_prompt = (
            f"【全局 Bug 库】：\n{bugs_context}\n\n"
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
        # 1. JSON
        with open(self.global_json, "w", encoding="utf-8") as f:
            json.dump(self.global_bugs, f, ensure_ascii=False, indent=2)
            
        # 2. Markdown
        md_lines = ["# 全局缺陷大盘 (Global Bug Library)\n"]
        md_lines.append("| ID | BUG标题 | 严重等级 | 状态 | 创建日期 | 最近复现 | 复现次数 |")
        md_lines.append("|---|---|---|---|---|---|---|")
        for b in reversed(self.global_bugs):  # 最新发现的放最前面
            md_lines.append(f"| {b['id']} | {b['title']} | {b['severity']} | {b['status']} | {b['date']} | {b.get('last_seen', b['date'])} | {b.get('occurrences', 1)} |")
            
        with open(self.global_md, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
            
        # 3. CSV
        with open(self.global_csv, "w", encoding="utf-8", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "BUG标题", "严重等级", "状态", "创建日期", "最近复现", "复现次数", "步骤", "报错结果"])
            for b in self.global_bugs:
                writer.writerow([
                    b["id"], b["title"], b["severity"], b["status"],
                    b["date"], b.get("last_seen", b["date"]), b.get("occurrences", 1),
                    b.get("step", ""), b.get("actual", "")
                ])
