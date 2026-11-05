import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
from server.database import SessionLocal
from server.models import BugRecord

bug_id = "BUG-20261030-003"
new_title = "【智能溜破】810溜破锤状态指示区图片加载失败时，_handleImageError 误调 this.$set 导致 TypeError"
new_target = "破碎锤监测区域中【810溜破锤】状态展示区"
new_status = "误报"
new_remark = "【复现步骤修正】1. 打开 智控管理 -> 智能溜破；2. 监测面板图片加载失败或触发状态渲染时发生异常。\n【处理说明】业务大屏‘运行状态’为只读指示灯，禁止点击交互；底层 this.$set 异常先标记为误报关闭，后续再行跟踪排查。"
new_step = "1. 进入【智控管理】->【智能溜破】；2. 破碎锤监测区域中【810溜破锤】面板图片资源加载失败或触发状态渲染异常（注：‘运行状态’仅为只读指示器，非开关按钮）。"
new_expected = "前端组件应做健壮性容错，图片资源加载失败时不应抛出未捕获的 TypeError 崩溃"

# 1. Update SQLite DB
db = SessionLocal()
b_rec = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
if b_rec:
    b_rec.title = new_title
    b_rec.target_element = new_target
    b_rec.status = new_status
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
            b["title"] = new_title
            b["target_element"] = new_target
            b["status"] = new_status
            b["remark"] = new_remark
            if "details" in b and isinstance(b["details"], dict):
                b["details"]["step"] = new_step
                b["details"]["expected"] = new_expected
            print("global_bugs_zhaiwan.json item updated.")
            break
    with open(global_file, "w", encoding="utf-8") as f:
        json.dump(g_bugs, f, ensure_ascii=False, indent=2)

# 3. Update single run bug file
run_bug_file = Path("reports/runs/zhaiwan/explore_20261030_193525/bugs/BUG-20261030-003.json")
if run_bug_file.exists():
    with open(run_bug_file, "r", encoding="utf-8") as f:
        r_bug = json.load(f)
    r_bug["title"] = new_title
    r_bug["target_element"] = new_target
    r_bug["status"] = new_status
    r_bug["remark"] = new_remark
    if "details" in r_bug and isinstance(r_bug["details"], dict):
        r_bug["details"]["step"] = new_step
        r_bug["details"]["expected"] = new_expected
    with open(run_bug_file, "w", encoding="utf-8") as f:
        json.dump(r_bug, f, ensure_ascii=False, indent=2)
    print("run BUG-20261030-003.json updated.")

print("All updates applied successfully!")
