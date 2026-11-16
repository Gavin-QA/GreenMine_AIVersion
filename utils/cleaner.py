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
    python utils/cleaner.py --compress-webp        # 原地将臃肿过程大图无损/高压缩比转码为 WebP（体积缩减 ~85%）
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


def get_disk_usage_summary() -> dict:
    """获取工程产物结构化磁盘占用大盘数据（供 CLI 与平台 API 共用）"""
    art_size, art_count = get_dir_size_and_count(ARTIFACTS_DIR)
    gb_size, _ = get_dir_size_and_count(GLOBAL_BUGS_DIR)
    top_size, _ = get_dir_size_and_count(TOPOLOGY_DIR)

    runs_size, runs_count = get_dir_size_and_count(RUNS_DIR)
    run_folders = get_all_run_folders()

    shots_size = 0
    shots_count = 0
    bugs_size = 0
    mem_size = 0
    log_size = 0
    for r in run_folders:
        s_sz, s_cnt = get_dir_size_and_count(r / "screenshots")
        b_sz, _ = get_dir_size_and_count(r / "bugs")
        m_sz, _ = get_dir_size_and_count(r / "checkpoint")
        shots_size += s_sz
        shots_count += s_cnt
        bugs_size += b_sz
        mem_size += m_sz
        for log_f in r.glob("*.log"):
            log_size += log_f.stat().st_size

    return {
        "artifacts_bytes": art_size,
        "artifacts_human": format_size(art_size),
        "artifacts_count": art_count,
        "global_bugs_bytes": gb_size,
        "global_bugs_human": format_size(gb_size),
        "topology_bytes": top_size,
        "topology_human": format_size(top_size),
        "runs_total_bytes": runs_size,
        "runs_total_human": format_size(runs_size),
        "runs_count": len(run_folders),
        "screenshots_bytes": shots_size,
        "screenshots_human": format_size(shots_size),
        "screenshots_count": shots_count,
        "screenshots_ratio": round(shots_size / max(runs_size, 1) * 100, 1),
        "bugs_bytes": bugs_size,
        "bugs_human": format_size(bugs_size),
        "checkpoint_bytes": mem_size,
        "checkpoint_human": format_size(mem_size),
        "logs_bytes": log_size,
        "logs_human": format_size(log_size),
    }


def print_disk_usage_info():
    """打印详细的磁盘占用大盘"""
    info = get_disk_usage_summary()
    print("\n" + "=" * 65)
    print("📊 【Electron AI Vision 工程产物存储大盘】")
    print("=" * 65)
    print(f"💎 全局持久资产库 [artifacts/]: {info['artifacts_human']} ({info['artifacts_count']} 个核心资产文件)")
    print(f"   ├── 全局 Bug 库: {info['global_bugs_human']}")
    print(f"   └── 全局拓扑树与快照: {info['topology_human']}")
    print(f"\n📦 单次运行产物区 [reports/runs/]: {info['runs_total_human']} (共 {info['runs_count']} 次运行)")
    print(f"   ├── 临时过程截图 (可安全清理): {info['screenshots_human']} ({info['screenshots_ratio']}%)")
    print(f"   ├── 🐞 崩溃案发现场凭据 (永久留存): {info['bugs_human']}")
    print(f"   ├── 🧠 检查点记忆 (永久留存): {info['checkpoint_human']}")
    print(f"   └── 📄 控制台日志: {info['logs_human']}")
    print("=" * 65 + "\n")


def clean_temp_screenshots(
    retain_days: int = 7,
    dry_run: bool = False,
    compress_webp: bool = False,
    quality: int = 65,
) -> dict:
    """安全清理或原地 WebP 压缩过程截图，永久保留 Bug 现场与记忆"""
    if not RUNS_DIR.exists():
        print("未检测到 reports/runs/ 目录。")
        return {"cleaned_files": 0, "freed_bytes": 0, "freed_human": "0.00 B", "dry_run": dry_run}

    cutoff_date = datetime.now() - timedelta(days=retain_days)
    run_folders = get_all_run_folders()

    cleaned_bytes = 0
    cleaned_files = 0

    mode_desc = "WebP 原地高压缩瘦身" if compress_webp else "过期临时大图清理"
    print(f"\n🧹 启动{mode_desc}程序 | 保留天数: {retain_days} 天 (早于 {cutoff_date.strftime('%Y-%m-%d')} 的过程截图将处理)")
    if dry_run:
        print("🔍 当前为 [预演模式 (Dry-Run)]，不执行实际写删。")

    if compress_webp and not dry_run:
        try:
            from PIL import Image
            from concurrent.futures import ThreadPoolExecutor, as_completed
        except ImportError:
            print("❌ 缺少 Pillow (PIL) 库，无法执行 WebP 压缩！")
            return {"cleaned_files": 0, "freed_bytes": 0, "freed_human": "0.00 B", "error": "Missing PIL"}

    img_exts = (".png", ".jpg", ".jpeg", ".webp")
    compress_targets = []
    for r in run_folders:
        shots_dir = r / "screenshots"
        if not shots_dir.exists():
            continue

        mtime = datetime.fromtimestamp(r.stat().st_mtime)
        if mtime >= cutoff_date and retain_days > 0:
            continue

        for shot in list(shots_dir.iterdir()):
            if not shot.is_file() or shot.suffix.lower() not in img_exts:
                continue
            file_sz = shot.stat().st_size

            if compress_webp:
                # 跳过已经很小（<= 450KB）的图，只处理膨胀 PNG 或超大图片
                if file_sz <= 450 * 1024:
                    continue
                if dry_run:
                    # 估算 WebP 压缩节省 ~85%
                    cleaned_bytes += int(file_sz * 0.85)
                    cleaned_files += 1
                else:
                    compress_targets.append((shot, file_sz))
            else:
                cleaned_bytes += file_sz
                cleaned_files += 1
                if not dry_run:
                    try:
                        shot.unlink()
                    except Exception as e:
                        print(f"删除失败: {shot} ({e})")

    if compress_webp and not dry_run and compress_targets:
        def _compress_one(item):
            shot_path, orig_sz = item
            try:
                with Image.open(shot_path) as img:
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.save(shot_path, format="WEBP", quality=quality, method=4)
                new_sz = shot_path.stat().st_size
                return max(0, orig_sz - new_sz), True
            except Exception as e:
                print(f"压缩失败: {shot_path} ({e})")
                return 0, False

        workers = min(8, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for saved_b, ok in pool.map(_compress_one, compress_targets):
                if ok:
                    cleaned_bytes += saved_b
                    cleaned_files += 1

    action_label = "预计释放" if dry_run else "成功释放"
    freed_human = format_size(cleaned_bytes)
    verb = "压缩" if compress_webp else "清理"
    print(f"\n✅ 瘦身完成！{action_label} 空间: {freed_human} ({verb}了 {cleaned_files} 张临时过程大图)")
    print("🔒 安全保障已生效：所有 Bug 崩溃现场截图、检查点记忆(checkpoint)、数据 JSON 及日志均已 100% 完整保留！\n")

    return {
        "cleaned_files": cleaned_files,
        "freed_bytes": cleaned_bytes,
        "freed_human": freed_human,
        "retain_days": retain_days,
        "compress_webp": compress_webp,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="Electron AI Vision 产物安全瘦身与磁盘维护工具")
    parser.add_argument("--info", action="store_true", help="查看当前产物磁盘占用分布大盘")
    parser.add_argument("--retain-days", type=int, default=None, help="保留最近 N 天的过程截图，更早的临时截图将被安全清理或压缩（推荐 7）")
    parser.add_argument("--compress-webp", action="store_true", help="不删除文件，而是将膨胀的过程大图原地压缩为 WebP 格式（体积缩减 ~85%%）")
    parser.add_argument("--quality", type=int, default=65, help="WebP 压缩画质 (1-100，默认 65)")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，仅计算可释放空间，不执行实际删除或覆盖")
    args = parser.parse_args()

    if args.info or (args.retain_days is None and not args.compress_webp):
        print_disk_usage_info()
        if args.retain_days is None and not args.compress_webp:
            print("💡 提示: 可通过 'python utils/cleaner.py --retain-days 7' 安全清理 7 天前的临时过程截图。")
            print("💡 或通过 'python utils/cleaner.py --compress-webp --retain-days 0' 将所有膨胀大图原地压缩为 WebP。\n")
        return

    retain = args.retain_days if args.retain_days is not None else 7
    clean_temp_screenshots(
        retain_days=retain,
        dry_run=args.dry_run,
        compress_webp=args.compress_webp,
        quality=args.quality,
    )


if __name__ == "__main__":
    main()
