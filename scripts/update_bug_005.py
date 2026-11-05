import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
from server.database import SessionLocal
from server.models import BugRecord

bug_id = "BUG-20261030-005"
new_status = "误报"
new_title = "[误报-过度断言] 【三级安全教育完成情况】统计模块 (数据442人与接口一致)"
new_remark = "UI 显示在册 442 人与接口 onboardingCount=442 一致。环形图仅展示总体完成率，业务未设计分层级明细，属 AI 自主探索时脑补层级字段过度断言产生的误报。"

# 1. Update SQLite DB
db = SessionLocal()
b_rec = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
if b_rec:
    b_rec.status = new_status
    b_rec.title = new_title
    b_rec.remark = new_remark
    db.commit()
    print("DB BugRecord updated.")
else:
    print("BugRecord not found in DB!")
db.close()

# 2. Update global_bugs_zhaiwan.json
global_file = Path("artifacts/bugs/global_bugs_zhaiwan.json")
if global_file.exists():
    with open(global_file, "r", encoding="utf-8") as f:
        g_bugs = json.load(f)
    for b in g_bugs:
        if b.get("id") == bug_id:
            b["status"] = new_status
            b["title"] = new_title
            b["remark"] = new_remark
            print("global_bugs_zhaiwan.json item updated.")
            break
    with open(global_file, "w", encoding="utf-8") as f:
        json.dump(g_bugs, f, ensure_ascii=False, indent=2)

# 3. Update single run bug file
run_bug_file = Path("reports/runs/zhaiwan/explore_20261030_193525/bugs/BUG-20261030-005.json")
if run_bug_file.exists():
    with open(run_bug_file, "r", encoding="utf-8") as f:
        r_bug = json.load(f)
    r_bug["status"] = new_status
    r_bug["title"] = new_title
    r_bug["remark"] = new_remark
    with open(run_bug_file, "w", encoding="utf-8") as f:
        json.dump(r_bug, f, ensure_ascii=False, indent=2)
    print("run BUG-20261030-005.json updated.")

print("BUG-20261030-005 marked as 误报 successfully!")

