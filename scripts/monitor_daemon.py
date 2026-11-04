# -*- coding: utf-8 -*-
"""
午间天瑞与宿主机物理内存连续监控守护脚本 (Noon Memory Tracking Daemon)
每 30 秒采集一次数据，持续写入 reports/memory_monitor_noon.csv 与 log，
供下午上班后直接复盘内存变化曲线，分析是否存在线性爬坡泄露。
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 注入项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 动态确保当前环境为 tianrui
os.environ["ACTIVE_APP"] = "tianrui"
from utils.system_guard import SystemMemoryGuard

REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
CSV_FILE = REPORTS_DIR / "memory_monitor_noon.csv"
LOG_FILE = REPORTS_DIR / "memory_monitor_noon.log"

# 初始化 CSV 表头
if not CSV_FILE.exists():
    with open(CSV_FILE, "w", encoding="utf-8") as f:
        f.write("timestamp,host_load_percent,host_avail_mb,tianrui_ue_mb,launcher_mb\n")

print(f"🚀 [Memory Daemon] 午间内存监控已启动，采样日志将写入: {CSV_FILE}")

baseline_ue_mb = None
baseline_host_load = None

try:
    while True:
        sample = SystemMemoryGuard.sample_all_memory()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        host_load = sample.get("host_load_percent", 0)
        host_avail = sample.get("host_avail_mb", 0.0)
        ue_mb = sample.get("companion_mem_mb", 0.0)
        launch_mb = sample.get("launcher_mem_mb", 0.0)

        if baseline_ue_mb is None and ue_mb > 0:
            baseline_ue_mb = ue_mb
            baseline_host_load = host_load

        delta_ue_str = f"({ue_mb - baseline_ue_mb:+.1f}MB)" if baseline_ue_mb is not None else ""

        log_line = (
            f"[{now_str}] 宿主机负荷: {host_load}% (可用 {host_avail/1024:.2f}GB) | "
            f"天瑞 UE: {ue_mb:.1f}MB {delta_ue_str} | "
            f"启动器: {launch_mb:.1f}MB\n"
        )

        with open(CSV_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now_str},{host_load},{host_avail},{ue_mb},{launch_mb}\n")

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line)

        time.sleep(30.0)
except KeyboardInterrupt:
    print("🛑 监控守护已手动退出。")
