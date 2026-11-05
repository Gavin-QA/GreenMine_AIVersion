# -*- coding: utf-8 -*-
"""
scripts/restore_bugs_from_db.py —— 缺陷数据灾备一键恢复工具

功能：
当本地 artifacts/bugs/ 目录或各批次 reports/runs/ 的缺陷数据被误删、损坏时，
从 SQLite 数据库 (BugRecord) 100% 提取全量数据，一键重新生成本地 JSON 与静态报告 report.html。
"""

import sys
import argparse
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.bug_db_sync import restore_global_bugs_file, restore_run_bugs, get_bugs_from_db
from utils.report_generator import ReportGenerator
from utils.paths import RUNS_DIR


def main():
    parser = argparse.ArgumentParser(description="从数据库全量恢复本地缺陷 JSON 与 HTML 报告")
    parser.add_argument("--app", type=str, default=None, help="指定恢复的应用代号 (例如 zhaiwan, tianrui, liwutong)")
    parser.add_argument("--run-id", type=str, default=None, help="指定恢复的运行批次 ID (例如 explore_20261104_183209)")
    parser.add_argument("--render-html", action="store_true", help="恢复文件后重新渲染 static report.html")
    parser.add_argument("--all", action="store_true", help="全量恢复所有已知应用与运行批次")
    args = parser.parse_args()

    print("=" * 65)
    print("🚀 [Bug DB Restore] 开始执行从数据库反哺恢复本地资产...")
    print("=" * 65)

    apps_to_restore = []
    if args.app:
        apps_to_restore.append(args.app)
    elif args.all:
        apps_to_restore = ["zhaiwan", "tianrui", "liwutong"]
    else:
        apps_to_restore = ["zhaiwan"]

    # 1. 恢复全局缺陷文件
    for app in apps_to_restore:
        restored = restore_global_bugs_file(app)
        if restored:
            print(f"✅ [全局缺陷库恢复成功] {restored}")
        else:
            print(f"ℹ️ [全局缺陷库未变动或无数据] app={app}")

    # 2. 恢复指定批次或全部批次的单次运行文件与报告
    runs_to_process = []
    if args.run_id:
        runs_to_process.append(args.run_id)
    elif args.all:
        all_bugs = get_bugs_from_db()
        unique_runs = list(set([b.get("run_id") for b in all_bugs if b.get("run_id")]))
        runs_to_process.extend(unique_runs)

    for rid in runs_to_process:
        restored_files = restore_run_bugs(rid)
        print(f"📦 [批次快照恢复] run_id={rid}: 成功恢复 {len(restored_files)} 个缺陷 JSON")

        if args.render_html:
            # 找到对应目录并渲染
            matched_dirs = list(RUNS_DIR.glob(f"**/{rid}"))
            for md in matched_dirs:
                if md.is_dir():
                    try:
                        ReportGenerator(md).generate_html(disable_push=True, update_hub=False)
                        print(f"🎨 [静态报告渲染完成] {md / 'report.html'}")
                    except Exception as e:
                        print(f"⚠️ 静态报告渲染异常 ({rid}): {e}")

    print("=" * 65)
    print("🎉 恢复流程执行完毕！")
    print("=" * 65)


if __name__ == "__main__":
    main()
