import sqlite3

conn = sqlite3.connect("data/vision_platform.db")
cursor = conn.cursor()

# 1. 检查并添加 task_runs.trigger_type
cols = [r[1] for r in cursor.execute("PRAGMA table_info(task_runs)").fetchall()]
if "trigger_type" not in cols:
    cursor.execute("ALTER TABLE task_runs ADD COLUMN trigger_type VARCHAR(32) DEFAULT 'manual'")
    print("Added task_runs.trigger_type")

# 2. 检查并添加 task_queue 周期调度字段
# cron_mode: once(单次), daily(天), weekly(每周), monthly(每月)
# cron_spec: 周期规则描述，如 "1" (每1天), "1,3,5" (周一三五), "15" (每月15日)
# is_active: 是否启用 (1=启用, 0=停用)
# scheduled_time_str: 保存时间点如 "18:35:00"
q_cols = [r[1] for r in cursor.execute("PRAGMA table_info(task_queue)").fetchall()]
if "cron_mode" not in q_cols:
    cursor.execute("ALTER TABLE task_queue ADD COLUMN cron_mode VARCHAR(32) DEFAULT 'once'")
    print("Added task_queue.cron_mode")
if "cron_spec" not in q_cols:
    cursor.execute("ALTER TABLE task_queue ADD COLUMN cron_spec VARCHAR(64) DEFAULT ''")
    print("Added task_queue.cron_spec")
if "is_active" not in q_cols:
    cursor.execute("ALTER TABLE task_queue ADD COLUMN is_active INTEGER DEFAULT 1")
    print("Added task_queue.is_active")
if "time_of_day" not in q_cols:
    cursor.execute("ALTER TABLE task_queue ADD COLUMN time_of_day VARCHAR(32) DEFAULT ''")
    print("Added task_queue.time_of_day")

# 3. 将已有队列关联的任务更新 trigger_type 为 scheduled
cursor.execute("""
    UPDATE task_runs
    SET trigger_type = 'scheduled'
    WHERE id IN (SELECT task_id FROM task_queue)
""")

conn.commit()
conn.close()
print("Migration completed successfully!")
