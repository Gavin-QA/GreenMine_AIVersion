# -*- coding: utf-8 -*-
"""
diagnose_active_bugs.py — 针对当前处于【激活】状态的缺陷执行架构师级 AI 根因诊断与责任人归因
"""

import sys
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.vision.agent import VisionAgent
from config.settings import settings
from utils.bug_analysis_expert import analyze_bug_expertly
from utils.bug_updater import update_bug_record
from utils.zentao_sync import resolve_bug_assignee

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diagnose_active_bugs")


def main():
    logger.info("🚀 开始对当前【激活】状态缺陷进行研发架构师级 AI 深度初诊...")

    global_bugs_file = PROJECT_ROOT / "artifacts" / "bugs" / "global_bugs_zhaiwan.json"
    if not global_bugs_file.exists():
        logger.error(f"找不到全局缺陷库文件: {global_bugs_file}")
        sys.exit(1)

    with open(global_bugs_file, "r", encoding="utf-8") as f:
        bugs_data = json.load(f)

    # 提取所有激活中的 Bug
    active_bugs = [b for b in bugs_data if b.get("status") in ("激活", "Active")]
    logger.info(f"📋 共筛选出 {len(active_bugs)} 个激活中缺陷，准备逐项诊断:\n")

    agent = VisionAgent()
    model = getattr(settings, "llm_bug_analysis_model", None) or "qwen3-vl-plus"

    diagnosed_count = 0
    results_summary = []

    for idx, bug in enumerate(active_bugs, 1):
        bug_id = bug.get("id")
        title = bug.get("title", "未命名缺陷")
        logger.info(f"[{idx}/{len(active_bugs)}] 🔍 正在深度诊断 [{bug_id}]: {title[:40]}...")

        try:
            formatted_md, res_dict = analyze_bug_expertly(
                agent=agent,
                model=model,
                bug=bug,
                crash_image_path=bug.get("screenshot") or bug.get("crash_screenshot"),
                app_key="zhaiwan"
            )

            # 智能解析责任归属 (陈贻雄 / 梅本霞)
            temp_bug = dict(bug)
            temp_bug["analysis_notes"] = formatted_md
            assignee_name, assignee_account, reason = resolve_bug_assignee(temp_bug)

            # 多端持久化回填 (全局JSON + 运行目录单据 + SQLite数据库)
            update_res = update_bug_record({
                "bug_id": bug_id,
                "analysis_notes": formatted_md,
                "assignee": assignee_name,
            })

            category = res_dict.get("category", "技术定性完成")
            logger.info(f"  ✨ [{bug_id}] 诊断成功！技术分类: {category} | 归因责任人: 【{assignee_name}】 ({reason})")
            diagnosed_count += 1
            results_summary.append({
                "id": bug_id,
                "title": title,
                "category": category,
                "assignee": assignee_name,
                "reason": reason
            })

        except Exception as e:
            logger.error(f"  ❌ [{bug_id}] 诊断失败: {e}", exc_info=True)

    print("\n" + "=" * 80)
    print(f"🎉 诊断闭环完成！成功完成 {diagnosed_count} / {len(active_bugs)} 个激活缺陷的深度研判！")
    print("=" * 80)
    for r in results_summary:
        print(f"• [{r['id']}] 指派人: {r['assignee']} ({r['reason']}) | 定性: {r['category']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

