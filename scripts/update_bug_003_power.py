import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
from server.database import SessionLocal
from server.models import BugRecord

bug_id = "BUG-20261031-003"
new_title = "[explore_20261104_183209] UI数据与接口原始报文不匹配: '左侧‘配电室概览’卡片中的‘每日用电量(kWh)’数值‘360.60’'"
new_run_id = "explore_20261104_183209"
new_task_id = "task_20261104_183208"
new_ui_path = "智控管理 -> 智能供配电"
new_target = "左侧‘配电室概览’卡片中的‘每日用电量(kWh)’"
new_status = "误报"
new_remark = "【核验通过 / 误报关闭】前端显示的 360.60 kWh 与后端接口 fdbPowerSupplyBasic/getFdbPowerSupplyBasicList 的 data.list[0].latestValueDetail.totalActiveEnergy.formatValue 字段数值完全一致。该 Bug 属 AI 接口校验时倒排索引未命中该接口导致的纯误报。"
new_analysis = """### 🤖 AI 架构师缺陷复核与归档结论

**【核验结论】**：【纯误报 / 自动校验漏检】UI 显示的每日用电量 360.60 kWh 与后端接口数据 100% 吻合

**【真实数据链路】**：
- **后端接口**：`fdbPowerSupplyBasic/getFdbPowerSupplyBasicList`
- **字段路径**：`data.list[0].latestValueDetail.totalActiveEnergy.formatValue`
- **原始返回值**：`"360.60"` (kWh)

**【误报归因】**：
AI 在执行 `Auto-API` 自动核验时，倒排索引仅检索了 `getPowerConsumptionStatistic` 等耗电统计接口，未能命中基础设备列表中的测控明细字段，误将接口未命中判定为 MISMATCH。经人工复核，前端数据绑定完全符合业务契约，正式归档为【误报】关闭。"""

# 1. Update SQLite DB
db = SessionLocal()
b_rec = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
if b_rec:
    b_rec.title = new_title
    b_rec.run_id = new_run_id
    b_rec.task_id = new_task_id
    b_rec.ui_path = new_ui_path
    b_rec.target_element = new_target
    b_rec.status = new_status
    b_rec.remark = new_remark
    b_rec.analysis_notes = new_analysis
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
            b["run_id"] = new_run_id
            b["task_id"] = new_task_id
            b["ui_path"] = new_ui_path
            b["target_element"] = new_target
            b["status"] = new_status
            b["remark"] = new_remark
            b["analysis_notes"] = new_analysis
            print("global_bugs_zhaiwan.json item updated.")
            break
    with open(global_file, "w", encoding="utf-8") as f:
        json.dump(g_bugs, f, ensure_ascii=False, indent=2)

# 3. Update single run bug files
for run_id in ["explore_20261104_183209", "explore_20261031_151626"]:
    run_bug_file = Path(f"reports/runs/zhaiwan/{run_id}/bugs/BUG-20261031-003.json")
    if run_bug_file.exists():
        with open(run_bug_file, "r", encoding="utf-8") as f:
            r_bug = json.load(f)
        r_bug["title"] = new_title
        r_bug["status"] = new_status
        r_bug["remark"] = new_remark
        r_bug["analysis_notes"] = new_analysis
        with open(run_bug_file, "w", encoding="utf-8") as f:
            json.dump(r_bug, f, ensure_ascii=False, indent=2)
        print(f"run {run_id} BUG-20261031-003.json updated.")

print("BUG-20261031-003 successfully synchronized as 误报 across all targets!")

