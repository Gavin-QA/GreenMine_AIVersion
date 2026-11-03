"""
==============================================================================
utils/backfill_bug_analysis.py —— 历史缺陷 AI 智能归因与排查指引批量补齐引擎
==============================================================================

功能与职责：
1. 扫描当前应用缺陷库 (artifacts/bugs/global_bugs_*.json)；
2. 过滤出尚未拥有 AI 归因初诊备注 (analysis_notes) 的有效缺陷；
3. 调用配置的多模态大模型 (qwen3-vl-plus) 结合报错日志、交互步骤、业务路径与现场截图进行智能深度初诊；
4. 自动回填持久化写入全局库及各运行目录，并触发大盘数据重构。
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from pathlib import Path

# Windows GBK
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from core.vision.agent import VisionAgent
from utils.paths import GLOBAL_BUGS_DIR, get_all_run_folders

logger = logging.getLogger("backfill_analysis")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def analyze_single_bug(agent: VisionAgent, model: str, bug: dict) -> str:
    from utils.bug_analysis_expert import analyze_bug_expertly
    formatted_md, _ = analyze_bug_expertly(
        agent=agent,
        model=model,
        bug=bug,
        crash_image_path=bug.get("screenshot") or bug.get("crash_screenshot"),
        app_key=bug.get("app")
    )
    return formatted_md


def main():
    parser = argparse.ArgumentParser(description="历史缺陷 AI 智能归因批量补齐工具")
    parser.add_argument("--app", type=str, default=None, help="目标矿山项目 (zhaiwan / liwutong)")
    parser.add_argument("--limit", type=int, default=15, help="本次最多补齐的 Bug 数量 (默认 15)")
    parser.add_argument("--bug-id", type=str, default=None, help="仅补齐指定单号 (如 BUG-20261026-002)")
    args = parser.parse_args()

    active_app = args.app or getattr(settings, "active_app", "zhaiwan")
    global_file = GLOBAL_BUGS_DIR / f"global_bugs_{active_app}.json"
    if not global_file.exists():
        logger.error(f"找不到全局缺陷库文件: {global_file}")
        sys.exit(1)

    with open(global_file, "r", encoding="utf-8") as f:
        bugs = json.load(f)

    # 筛选需要补齐的缺陷
    if args.bug_id:
        targets = [b for b in bugs if b.get("id") == args.bug_id]
    else:
        # 优先补齐最近的未分析缺陷
        targets = [b for b in reversed(bugs) if not b.get("analysis_notes") or b.get("analysis_notes") == "无"][:args.limit]

    if not targets:
        logger.info("🎉 当前没有需要补齐 AI 初诊的缺陷！")
        return

    logger.info(f"📋 共筛选出 {len(targets)} 个待补齐 AI 分析的缺陷...")
    agent = VisionAgent()
    model = getattr(settings, "llm_bug_analysis_model", "qwen3-vl-plus")
    logger.info(f"🧠 使用分析模型: {model}")

    run_folders = get_all_run_folders()
    success_count = 0

    for idx, b in enumerate(targets, 1):
        b_id = b.get("id")
        logger.info(f"\n[{idx}/{len(targets)}] 正在深度初诊缺陷: {b_id} ({b.get('title')[:30]}...)...")
        try:
            notes = analyze_single_bug(agent, model, b)
            b["analysis_notes"] = notes

            # 同步更新单次运行目录中的 bug json
            for r_dir in run_folders:
                rf = r_dir / "bugs" / f"{b_id}.json"
                if rf.exists():
                    try:
                        with open(rf, "r", encoding="utf-8") as r_file:
                            r_data = json.load(r_file)
                        r_data["analysis_notes"] = notes
                        with open(rf, "w", encoding="utf-8") as r_file:
                            json.dump(r_data, r_file, ensure_ascii=False, indent=2)
                    except Exception as re_err:
                        logger.warning(f"更新运行目录单据失败 ({rf.name}): {re_err}")

            success_count += 1
            logger.info(f"✅ {b_id} 智能分析完成！")
        except Exception as e:
            logger.error(f"❌ 分析 {b_id} 失败: {e}")

    # 写回全局库
    with open(global_file, "w", encoding="utf-8") as f:
        json.dump(bugs, f, ensure_ascii=False, indent=2)

    logger.info(f"\n🎉 批量补齐完成！成功补全 {success_count}/{len(targets)} 个缺陷的 AI 根因初诊！")

    # 触发大盘重新编译
    try:
        from utils.report_hub import ReportHub
        hub = ReportHub()
        hub.build_index_html()
        logger.info("🎉 静态大盘已自动重构更新！")
    except Exception as he:
        logger.warning(f"大盘重构提醒: {he}")


if __name__ == "__main__":
    main()
