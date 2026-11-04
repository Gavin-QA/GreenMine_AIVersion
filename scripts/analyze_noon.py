# -*- coding: utf-8 -*-
import sys
import csv
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

csv_path = Path("reports/memory_monitor_noon.csv")
with open(csv_path, "r", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

active_rows = [r for r in rows if float(r.get("tianrui_ue_mb", 0)) > 0]
zero_rows = [r for r in rows if float(r.get("tianrui_ue_mb", 0)) == 0]

print(f"📊 总采样点: {len(rows)} 个 (时间跨度: {rows[0]['timestamp']} -> {rows[-1]['timestamp']})")
print(f"   - UE 活跃采样点: {len(active_rows)} 个")
print(f"   - 待机/未启动采样点: {len(zero_rows)} 个")

if active_rows:
    ue_mems = [float(r["tianrui_ue_mb"]) for r in active_rows]
    launch_mems = [float(r["launcher_mb"]) for r in active_rows]
    host_loads = [int(r["host_load_percent"]) for r in active_rows]

    max_ue = max(ue_mems)
    min_ue = min(ue_mems)
    avg_ue = sum(ue_mems) / len(ue_mems)
    max_row = next(r for r in active_rows if float(r["tianrui_ue_mb"]) == max_ue)
    min_row = next(r for r in active_rows if float(r["tianrui_ue_mb"]) == min_ue)

    print(f"\n📈 UE 引擎物理内存分析:")
    print(f"   - 峰值物理内存: {max_ue:.1f} MB (出现于 {max_row['timestamp']})")
    print(f"   - 最低物理内存: {min_ue:.1f} MB (出现于 {min_row['timestamp']})")
    print(f"   - 平均物理内存: {avg_ue:.1f} MB")
    print(f"   - 当前最新水位: {ue_mems[-1]:.1f} MB ({active_rows[-1]['timestamp']})")

    print(f"\n🖥️ 宿主机系统整体状态:")
    print(f"   - 内存负载率区间: {min(host_loads)}% ~ {max(host_loads)}% (当前: {host_loads[-1]}%)")
    print(f"   - 启动器内存区间: {min(launch_mems):.1f} MB ~ {max(launch_mems):.1f} MB (当前: {launch_mems[-1]:.1f} MB)")

print("\n⏱️ 关键时序里程碑切片:")
# 检测 UE 启动与状态转折点
prev_state = None
milestones = []
for idx, r in enumerate(rows):
    ue_val = float(r["tianrui_ue_mb"])
    is_active = ue_val > 0
    if is_active != prev_state:
        milestones.append((idx, r, "启动运行" if is_active else "停止/回收"))
        prev_state = is_active

for idx, r, desc in milestones:
    print(f"   [{r['timestamp']}] 状态转折 -> {desc} | 宿主机: {r['host_load_percent']}% | UE: {r['tianrui_ue_mb']} MB | 启动器: {r['launcher_mb']} MB")

# 打印后半段稳定期的数据分布
if active_rows:
    recent_active = active_rows[-10:]
    print("\n🔍 最近 10 次采样 (5分钟内最新趋势):")
    for r in recent_active:
        print(f"   [{r['timestamp']}] 宿主机: {r['host_load_percent']}% | UE: {float(r['tianrui_ue_mb']):.1f} MB | 启动器: {float(r['launcher_mb']):.1f} MB")

