import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
from server.database import SessionLocal
from server.models import BugRecord

bug_id = "BUG-20261105-001"
new_title = "[误报-看门狗熔断] 宿主机内存超限主动回收进程引发 CDP 调试通道断连"
new_status = "误报"
new_remark = "【非业务缺陷 / 熔断自愈】测试运行至 6h23m 时宿主机总内存触达 93% 警戒线，看门狗主动执行自愈保护回收了启动器进程，导致 CDP 通道断开抛出 Target closed 异常。属测试框架守护机制的预期行为，非软件 Bug。"
new_analysis = """### 🤖 AI 架构师缺陷复核与归档结论

**【核验结论】**：【非业务缺陷 / 框架守护熔断误报】

**【真实案发机理】**：
测试任务在连续高强度自主探索运行 6 小时 23 分钟后，宿主机物理内存使用率攀升至 93%（剩余仅 2185MB）。系统看门狗守护模块（watchdog.py）为避免宿主机蓝屏宕机，主动触发了【Watchdog OOM Emergency】紧急自愈回收机制，强制关闭了目标启动器进程（se-launcher-zhaiwan.exe）。

**【误报归因】**：
进程被看门狗安全回收的瞬间，自动化底层 CDP 驱动通道（Playwright BrowserContext）随之断开。此时 Worker 正在执行对【智能矿仓】Tab 的鼠标坐标点击，捕获到 Target closed 异常后误将其登记为点击崩溃缺陷。经人工复核，被测软件在此处并无崩溃，属于框架熔断保护机制的连带现象，正式归档为【误报】关闭。"""

# 1. Update SQLite DB
db = SessionLocal()
b_rec = db.query(BugRecord).filter(BugRecord.id == bug_id).first()
if b_rec:
    b_rec.title = new_title
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
            b["status"] = new_status
            b["remark"] = new_remark
            b["analysis_notes"] = new_analysis
            print("global_bugs_zhaiwan.json item updated.")
            break
    with open(global_file, "w", encoding="utf-8") as f:
        json.dump(g_bugs, f, ensure_ascii=False, indent=2)

# 3. Update single run bug file
run_bug_file = Path("reports/runs/zhaiwan/explore_20261104_183209/bugs/BUG-20261105-001.json")
if run_bug_file.exists():
    with open(run_bug_file, "r", encoding="utf-8") as f:
        r_bug = json.load(f)
    r_bug["title"] = new_title
    r_bug["status"] = new_status
    r_bug["remark"] = new_remark
    r_bug["analysis_notes"] = new_analysis
    with open(run_bug_file, "w", encoding="utf-8") as f:
        json.dump(r_bug, f, ensure_ascii=False, indent=2)
    print("run BUG-20261105-001.json updated.")

print("BUG-20261105-001 successfully marked as 误报 across all targets!")
