# -*- coding: utf-8 -*-
"""
实时双轨内存穿透交互式巡检工具 (Live Dual-Track Memory Inspector)
直观展示：物理工作集 (RAM) + 专用提交量 (Private Bytes/Commit)，穿透 Pagefile 假象
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

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["ACTIVE_APP"] = "tianrui"
from utils.system_guard import SystemMemoryGuard

def inspect_current():
    sample = SystemMemoryGuard.sample_all_memory()
    now_str = datetime.now().strftime("%H:%M:%S")
    ue_mb = sample.get("companion_mem_mb", 0.0)
    ue_priv_mb = sample.get("companion_private_mb", 0.0)
    launch_mb = sample.get("launcher_mem_mb", 0.0)
    host_load = sample.get("host_load_percent", 0)
    host_avail_gb = sample.get("host_avail_mb", 0.0) / 1024.0
    commit_load = sample.get("host_commit_load_percent", 0)
    commit_avail_gb = sample.get("host_commit_avail_gb", 0.0)

    return {
        "time": now_str,
        "ue_ws_mb": ue_mb,
        "ue_priv_mb": ue_priv_mb,
        "ue_priv_gb": ue_priv_mb / 1024.0,
        "launch_mb": launch_mb,
        "host_ram_load": host_load,
        "host_ram_avail_gb": host_avail_gb,
        "host_commit_load": commit_load,
        "host_commit_avail_gb": commit_avail_gb,
    }

if __name__ == "__main__":
    curr = inspect_current()
    print(
        f"[{curr['time']}] 天瑞 UE: RAM={curr['ue_ws_mb']:.1f} MB | "
        f"专用提交(Commit)={curr['ue_priv_mb']:.1f} MB ({curr['ue_priv_gb']:.2f} GB) | "
        f"宿主机RAM={curr['host_ram_load']}% (剩余 {curr['host_ram_avail_gb']:.2f} GB) | "
        f"宿主机Commit={curr['host_commit_load']}% (剩余 {curr['host_commit_avail_gb']:.2f} GB)"
    )
