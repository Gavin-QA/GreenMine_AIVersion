"""
安全瘦身与归档清理工具 (Cleaner)

设计原则与安全红线：
1. 绝对不删 artifacts/ (全局 Bug 知识库、拓扑树基线、归档用例永久安全)
2. 绝对不删各运行目录下的 bugs/ (现场大图与报错 JSON 永久留存)
3. 绝对不删各运行目录下的 checkpoint/ (记忆字典与架构状态永久留存，随时支持断点续跑)
4. 绝对不删各运行目录下的 generated_cases/ 与 *.log
5. 仅清理指定天数前（或全部历史）的 screenshots/ 临时过程大图（背景变暗图、探索过渡图等，占体积 90%+）

用法：
    python utils/cleaner.py --info                 # 查看当前各目录磁盘占用详情
    python utils/cleaner.py --retain-days 7        # 清理 7 天前的过程截图（保留 Bug 现场与记忆）
    python utils/cleaner.py --retain-days 0        # 清理所有历史运行的临时过程截图（仅留 Bug 和记忆）
    python utils/cleaner.py --dry-run              # 仅演练，计算可释放空间，不实际删除
"""

import os
import sys
import io
import shutil
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

# Windows GBK 终端 UTF-8 安全编码保护
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.paths import (
    ARTIFACTS_DIR,
    RUNS_DIR,
    GLOBAL_BUGS_DIR,
    TOPOLOGY_DIR,
    get_all_run_folders,
)


def get_dir_size_and_count(path: Path):
    """计算目录的总字节数与文件数"""
    total_size = 0
    file_count = 0
    if not path.exists():
        return 0, 0
    for p in path.rglob("*"):
        if p.is_file():
            total_size += p.stat().st_size
            file_count += 1
    return total_size, file_count


def format_size(bytes_size: int) -> str:
    """人类可读的文件大小格式化"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def print_disk_usage_info():
    """打印详细的磁盘占用大盘"""
    print("\n" + "=" * 65)
    print("📊 【Electron AI Vision 工程产物存储大盘】")
    print("=" * 65)

    # 1. 全局资产
    art_size, art_count = get_dir_size_and_count(ARTIFACTS_DIR)
    print(f"💎 全局持久资产库 [artifacts/]: {format_size(art_size)} ({art_count} 个核心资产文件)")
    
    gb_size, _ = get_dir_size_and_count(GLOBAL_BUGS_DIR)
    top_size, _ = get_dir_size_and_count(TOPOLOGY_DIR)
    print(f"   ├── 全局 Bug 库: {format_size(gb_size)}")
    print(f"   └── 全局拓扑树与快照: {format_size(top_size)}")

    # 2. 运行产物
    runs_size, runs_count = get_dir_size_and_count(RUNS_DIR)
    run_folders = get_all_run_folders()
    print(f"\n📦 单次运行产物区 [reports/runs/]: {format_size(runs_size)} (共 {len(run_folders)} 次运行)")

    # 细分分析
    shots_size = 0
    bugs_size = 0
    mem_size = 0
    log_size = 0
    for r in run_folders:
        s_sz, _ = get_dir_size_and_count(r / "screenshots")
        b_sz, _ = get_dir_size_and_count(r / "bugs")
        m_sz, _ = get_dir_size_and_count(r / "checkpoint")
        shots_size += s_sz
        bugs_size += b_sz
        mem_size += m_sz
        for log_f in r.glob("*.log"):
            log_size += log_f.stat().st_size

    print(f"   ├── 临时过程截图 (可安全清理): {format_size(shots_size)} ({shots_size/max(runs_size,1)*100:.1f}%)")
    print(f"   ├── 🐞 崩溃案发现场凭据 (永久留存): {format_size(bugs_size)}")
    print(f"   ├── 🧠 检查点记忆 (永久留存): {format_size(mem_size)}")
    print(f"   └── 📄 控制台日志: {format_size(log_size)}")

    print("=" * 65 + "\n")


def clean_temp_screenshots(retain_days: int = 7, dry_run: bool = False):
    """安全清理过程截图，永久保留 Bug 现场与记忆"""
    if not RUNS_DIR.exists():
        print("未检测到 reports/runs/ 目录。")
        return

    cutoff_date = datetime.now() - timedelta(days=retain_days)
    run_folders = get_all_run_folders()
    
    cleaned_bytes = 0
    cleaned_files = 0

    print(f"\n🧹 启动安全瘦身程序 | 保留天数: {retain_days} 天 (早于 {cutoff_date.strftime('%Y-%m-%d')} 的过程截图将被清理)")
    if dry_run:
        print("🔍 当前为 [预演模式 (Dry-Run)]，不执行实际删除。")

    for r in run_folders:
        shots_dir = r / "screenshots"
        if not shots_dir.exists():
            continue

        # 检查运行时间
        mtime = datetime.fromtimestamp(r.stat().st_mtime)
        if mtime >= cutoff_date and retain_days > 0:
            continue

        for shot in list(shots_dir.glob("*.png")):
            file_sz = shot.stat().st_size
            cleaned_bytes += file_sz
            cleaned_files += 1
            if not dry_run:
                try:
                    shot.unlink()
                except Exception as e:
                    print(f"删除失败: {shot} ({e})")

    action_label = "预计释放" if dry_run else "成功释放"
    print(f"\n✅ 瘦身完成！{action_label} 空间: {format_size(cleaned_bytes)} (清理了 {cleaned_files} 张临时过程大图)")
    print("🔒 安全保障已生效：所有 Bug 崩溃现场截图、检查点记忆(checkpoint)及日志均已 100% 完整保留！\n")


def main():
    parser = argparse.ArgumentParser(description="Electron AI Vision 产物安全瘦身与磁盘维护工具")
    parser.add_argument("--info", action="store_true", help="查看当前产物磁盘占用分布大盘")
    parser.add_argument("--retain-days", type=int, default=None, help="保留最近 N 天的过程截图，更早的临时截图将被安全清理（默认不清理，推荐 7）")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，仅计算可释放空间，不执行实际删除")
    args = parser.parse_args()

    if args.info or args.retain_days is None:
        print_disk_usage_info()
        if args.retain_days is None:
            print("💡 提示: 可通过 'python utils/cleaner.py --retain-days 7' 安全清理 7 天前的临时过程截图。\n")
        return

    if args.retain_days is not None:
        clean_temp_screenshots(retain_days=args.retain_days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
