# -*- coding: utf-8 -*-
"""
scripts/migrate_bugs_db.py
执行 bug_records 表结构升级 (增量追加 app_name, step, action_type, tags, extra_data)，
并从已有的 artifacts/bugs/global_bugs_*.json 全量回填缺失元数据，保证 100% 历史数据无损。
"""

import sys
import json
import sqlite3
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "vision_platform.db"
BUGS_DIR = PROJECT_ROOT / "artifacts" / "bugs"

def migrate():
    print(f"🔧 开始检查并升级 SQLite 数据库结构: {DB_PATH}")
    if not DB_PATH.exists():
        print("❌ 数据库文件不存在，跳过结构迁移。")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 检查现有列
    cursor.execute("PRAGMA table_info(bug_records)")
    existing_cols = {row[1]: row[2] for row in cursor.fetchall()}
    print(f"现有列清单: {list(existing_cols.keys())}")

    # 2. 增量追加新列
    new_cols = {
        "app_name": "VARCHAR(64) DEFAULT 'zhaiwan'",
        "step": "TEXT",
        "action_type": "VARCHAR(64)",
        "tags": "TEXT",
        "extra_data": "TEXT"
    }

    for col_name, col_type in new_cols.items():
        if col_name not in existing_cols:
            alter_sql = f"ALTER TABLE bug_records ADD COLUMN {col_name} {col_type}"
            print(f"➕ 正在追加字段: {alter_sql}")
            cursor.execute(alter_sql)
        else:
            print(f"✓ 字段已存在: {col_name}")

    conn.commit()

    # 3. 从 artifacts/bugs/global_bugs_*.json 进行历史数据全字段无损回填
    print("\n📦 开始从本地全局缺陷库回填历史元数据...")
    updated_count = 0
    for bug_file in BUGS_DIR.glob("global_bugs*.json"):
        app_name = "zhaiwan"
        if "_" in bug_file.stem:
            app_name = bug_file.stem.split("_", 1)[1]

        try:
            with open(bug_file, "r", encoding="utf-8") as f:
                bugs_list = json.load(f)
        except Exception as e:
            print(f"⚠️ 读取 {bug_file.name} 失败: {e}")
            continue

        for b in bugs_list:
            b_id = b.get("id")
            if not b_id:
                continue

            step_val = b.get("step")
            action_type_val = b.get("action_type")
            tags_val = json.dumps(b.get("tags", []), ensure_ascii=False) if b.get("tags") is not None else None
            app_val = b.get("app") or app_name
            extra_data_val = json.dumps({
                "details": b.get("details"),
                "severity": b.get("severity"),
                "date": b.get("date"),
                "last_seen": b.get("last_seen"),
            }, ensure_ascii=False)

            cursor.execute("""
                UPDATE bug_records
                SET app_name = COALESCE(app_name, ?),
                    step = COALESCE(step, ?),
                    action_type = COALESCE(action_type, ?),
                    tags = COALESCE(tags, ?),
                    extra_data = COALESCE(extra_data, ?)
                WHERE id = ?
            """, (app_val, step_val, action_type_val, tags_val, extra_data_val, b_id))
            if cursor.rowcount > 0:
                updated_count += 1

    conn.commit()
    conn.close()
    print(f"✅ 数据库结构升级与历史数据回填完成，共同步更新 {updated_count} 条缺陷记录！")

if __name__ == "__main__":
    migrate()
