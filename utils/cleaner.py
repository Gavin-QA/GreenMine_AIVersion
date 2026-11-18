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
    python utils/cleaner.py --retain-days 7        # 清理 7 天前的过程截图（自动保护仍含激活 Bug 的报告，保留 Bug 现场与记忆）
    python utils/cleaner.py --retain-days 0        # 清理所有历史运行的临时过程截图（仅留 Bug 和记忆，仍受激活 Bug 保护）
    python utils/cleaner.py --force                # 忽略激活 Bug 保护盾，强制按天数清理
    python utils/cleaner.py --compress-webp        # 原地将臃肿过程大图无损/高压缩比转码为 WebP（体积缩减 ~85%%）
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
    """使用 os.scandir 高速计算目录的总字节数与文件数（Windows 下比 rglob+stat 快数倍）"""
    if not path.exists():
        return 0, 0
    total_size = 0
    file_count = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total_size += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass
    return total_size, file_count


def format_size(bytes_size: int) -> str:
    """人类可读的文件大小格式化"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def get_disk_usage_summary() -> dict:
    """获取工程产物结构化磁盘占用大盘数据（单次高速 scandir 扫描，避免重复遍历）"""
    gb_size, gb_count = get_dir_size_and_count(GLOBAL_BUGS_DIR)
    top_size, top_count = get_dir_size_and_count(TOPOLOGY_DIR)
    art_size = gb_size + top_size
    art_count = gb_count + top_count
    # 兼容 artifacts/ 下除 bugs、topology 外的其余目录（仅扫描顶层子项）
    if ARTIFACTS_DIR.exists():
        try:
            with os.scandir(ARTIFACTS_DIR) as it:
                for entry in it:
                    if entry.path in (str(GLOBAL_BUGS_DIR), str(TOPOLOGY_DIR)):
                        continue
                    if entry.is_file(follow_symlinks=False):
                        art_size += entry.stat(follow_symlinks=False).st_size
                        art_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        sz, cnt = get_dir_size_and_count(Path(entry.path))
                        art_size += sz
                        art_count += cnt
        except OSError:
            pass

    run_folders = get_all_run_folders()
    runs_size = 0
    shots_size = 0
    shots_count = 0
    bugs_size = 0
    mem_size = 0
    log_size = 0

    for r in run_folders:
        try:
            with os.scandir(r) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            f_sz = entry.stat(follow_symlinks=False).st_size
                            runs_size += f_sz
                            if entry.name.endswith(".log"):
                                log_size += f_sz
                        elif entry.is_dir(follow_symlinks=False):
                            sz, cnt = get_dir_size_and_count(Path(entry.path))
                            runs_size += sz
                            if entry.name == "screenshots":
                                shots_size += sz
                                shots_count += cnt
                            elif entry.name == "bugs":
                                bugs_size += sz
                            elif entry.name == "checkpoint":
                                mem_size += sz
                    except OSError:
                        pass
        except OSError:
            pass

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


def get_active_bug_run_ids() -> dict:
    """基于数据库与全局缺陷库获取当前仍处于『激活』状态的缺陷所属 run_id 映射（run_id -> [bug_id, ...]）"""
    import json
    active_map: dict = {}

    db_loaded = False
    try:
        from server.database import SessionLocal
        from server.models import BugRecord

        db = SessionLocal()
        try:
            rows = db.query(BugRecord).filter(BugRecord.status.in_(["激活", "Open", ""])).all()
            for b in rows:
                if b.run_id:
                    active_map.setdefault(b.run_id, []).append(b.id)
            db_loaded = True
        finally:
            db.close()
    except Exception:
        pass

    if not db_loaded and GLOBAL_BUGS_DIR.exists():
        for gf in GLOBAL_BUGS_DIR.glob("global_bugs*.json"):
            try:
                items = json.loads(gf.read_text(encoding="utf-8"))
                for b in items:
                    st = (b.get("status") or "激活").strip()
                    if st in ("激活", "Open", "") and b.get("run_id"):
                        active_map.setdefault(b["run_id"], []).append(b.get("id", ""))
            except Exception:
                pass

    return active_map


def clean_temp_screenshots(
    retain_days: int = 7,
    dry_run: bool = False,
    compress_webp: bool = False,
    quality: int = 65,
    protect_active_bugs: bool = True,
) -> dict:
    """安全清理或原地 WebP 压缩过程截图，默认自动保护仍含激活 Bug 的运行目录以保留完整操作上下文"""
    if not RUNS_DIR.exists():
        print("未检测到 reports/runs/ 目录。")
        return {"cleaned_files": 0, "freed_bytes": 0, "freed_human": "0.00 B", "protected_runs": [], "dry_run": dry_run}

    cutoff_date = datetime.now() - timedelta(days=retain_days)
    run_folders = get_all_run_folders()
    active_bug_runs = get_active_bug_run_ids() if (protect_active_bugs and not compress_webp) else {}

    cleaned_bytes = 0
    cleaned_files = 0
    protected_runs = []

    mode_desc = "WebP 原地高压缩瘦身" if compress_webp else "过期临时大图清理"
    print(f"\n🧹 启动{mode_desc}程序 | 保留天数: {retain_days} 天 (早于 {cutoff_date.strftime('%Y-%m-%d')} 的过程截图将处理)")
    if protect_active_bugs and not compress_webp:
        print("🛡️ 激活 Bug 保护盾已开启：含未处理「激活」Bug 的报告将保留全部上下文过程截图。")
    if dry_run:
        print("🔍 当前为 [预演模式 (Dry-Run)]，不执行实际写删。")
    sys.stdout.flush()

    if compress_webp and not dry_run:
        try:
            from PIL import Image
            from concurrent.futures import ThreadPoolExecutor
        except ImportError:
            print("❌ 缺少 Pillow (PIL) 库，无法执行 WebP 压缩！")
            return {"cleaned_files": 0, "freed_bytes": 0, "freed_human": "0.00 B", "protected_runs": [], "error": "Missing PIL"}

    img_exts = (".png", ".jpg", ".jpeg", ".webp")
    compress_targets = []
    affected_runs_map = {}

    def _record_file(run_id: str, shots_path: Path, filename: str, est_bytes: int):
        entry = affected_runs_map.get(run_id)
        if entry is None:
            try:
                rel_dir = str(shots_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            except ValueError:
                rel_dir = str(shots_path).replace("\\", "/")
            entry = {
                "run_id": run_id,
                "dir": rel_dir,
                "file_count": 0,
                "freed_bytes": 0,
                "files": [],
            }
            affected_runs_map[run_id] = entry
        entry["file_count"] += 1
        entry["freed_bytes"] += est_bytes
        entry["files"].append(filename)

    for r in run_folders:
        shots_dir = r / "screenshots"
        if not shots_dir.exists():
            continue

        mtime = datetime.fromtimestamp(r.stat().st_mtime)
        if mtime >= cutoff_date and retain_days > 0:
            continue

        # 🛡️ 激活 Bug 保护盾：删除模式下跳过仍挂有未处理激活 Bug 的报告目录
        if protect_active_bugs and not compress_webp and r.name in active_bug_runs:
            protected_runs.append({"run_id": r.name, "bug_ids": active_bug_runs[r.name]})
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
                    est_saved = int(file_sz * 0.85)
                    cleaned_bytes += est_saved
                    cleaned_files += 1
                    _record_file(r.name, shots_dir, shot.name, est_saved)
                else:
                    compress_targets.append((r.name, shots_dir, shot, file_sz))
            else:
                cleaned_bytes += file_sz
                cleaned_files += 1
                _record_file(r.name, shots_dir, shot.name, file_sz)
                if not dry_run:
                    try:
                        shot.unlink()
                    except Exception as e:
                        print(f"删除失败: {shot} ({e})")

    if compress_webp and not dry_run and compress_targets:
        def _compress_one(item):
            run_id, shots_path, shot_path, orig_sz = item
            try:
                with Image.open(shot_path) as img:
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.save(shot_path, format="WEBP", quality=quality, method=4)
                new_sz = shot_path.stat().st_size
                return run_id, shots_path, shot_path.name, max(0, orig_sz - new_sz), True
            except Exception as e:
                print(f"压缩失败: {shot_path} ({e})")
                return run_id, shots_path, shot_path.name, 0, False

        workers = min(8, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for run_id, shots_path, fname, saved_b, ok in pool.map(_compress_one, compress_targets):
                if ok:
                    cleaned_bytes += saved_b
                    cleaned_files += 1
                    _record_file(run_id, shots_path, fname, saved_b)

    affected_runs = []
    for entry in affected_runs_map.values():
        entry["freed_human"] = format_size(entry["freed_bytes"])
        affected_runs.append(entry)

    action_label = "预计释放" if dry_run else "成功释放"
    freed_human = format_size(cleaned_bytes)
    verb = "压缩" if compress_webp else "清理"
    print(f"\n✅ 瘦身完成！{action_label} 空间: {freed_human} ({verb}了 {cleaned_files} 张临时过程大图)")
    if affected_runs:
        print(f"📋 本次涉及 {len(affected_runs)} 个运行目录的文件明细：")
        for ar in affected_runs:
            preview = ", ".join(ar["files"][:5])
            more = f" ... 等共 {ar['file_count']} 个文件" if ar["file_count"] > 5 else ""
            print(f"   📁 {ar['dir']} ({ar['file_count']} 个, {ar['freed_human']}): {preview}{more}")
    if protected_runs:
        print(f"🛡️ 已保护 {len(protected_runs)} 个含「激活」Bug 的报告目录（完整保留上下文过程图）：")
        for pr in protected_runs:
            print(f"   ⏭️ {pr['run_id']} (关联激活缺陷: {', '.join(pr['bug_ids'])})")
    print("🔒 安全保障已生效：所有 Bug 崩溃现场截图、检查点记忆(checkpoint)、数据 JSON 及日志均已 100% 完整保留！\n", flush=True)

    return {
        "cleaned_files": cleaned_files,
        "freed_bytes": cleaned_bytes,
        "freed_human": freed_human,
        "retain_days": retain_days,
        "compress_webp": compress_webp,
        "protect_active_bugs": protect_active_bugs,
        "protected_runs": protected_runs,
        "protected_count": len(protected_runs),
        "affected_runs": affected_runs,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="Electron AI Vision 产物安全瘦身与磁盘维护工具")
    parser.add_argument("--info", action="store_true", help="查看当前产物磁盘占用分布大盘")
    parser.add_argument("--retain-days", type=int, default=None, help="保留最近 N 天的过程截图，更早的临时截图将被安全清理或压缩（推荐 7）")
    parser.add_argument("--compress-webp", action="store_true", help="不删除文件，而是将膨胀的过程大图原地压缩为 WebP 格式（体积缩减 ~85%%）")
    parser.add_argument("--quality", type=int, default=65, help="WebP 压缩画质 (1-100，默认 65)")
    parser.add_argument("--force", action="store_true", help="强制清理，忽略激活 Bug 保护盾")
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
        protect_active_bugs=not args.force,
    )


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
    main()
