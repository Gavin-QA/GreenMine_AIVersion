import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 默认零配置 SQLite 数据库路径 (单机即开即用零运维)
DEFAULT_SQLITE_URL = f"sqlite:///{DATA_DIR / 'vision_platform.db'}"

# 支持从环境变量或配置文件动态重载为企业级 MySQL:
# 例: DATABASE_URL=mysql+pymysql://user:pwd@ip:3306/ai_vision?charset=utf8mb4
DATABASE_URL = os.getenv("VISION_DATABASE_URL", DEFAULT_SQLITE_URL)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖注入 DB 会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def backup_database(max_backups: int = 5) -> Optional[str]:
    """
    冷启动或任务执行前，自动对 SQLite 数据库创建带时间戳的本地物理镜像快照，
    滚动保留最近 5 份备份，杜绝因极端异常导致数据资产损毁。
    """
    import shutil
    import datetime
    import logging
    logger = logging.getLogger("server.database")

    if not DATABASE_URL.startswith("sqlite"):
        return None

    db_path = DATA_DIR / "vision_platform.db"
    if not db_path.exists():
        return None

    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"vision_platform_{now_str}.db.bak"

    try:
        shutil.copy2(db_path, backup_file)
        # 滚动清理超量历史备份
        all_backups = sorted(backup_dir.glob("vision_platform_*.db.bak"), key=os.path.getmtime)
        while len(all_backups) > max_backups:
            oldest = all_backups.pop(0)
            try:
                oldest.unlink()
            except Exception:
                pass
        logger.info(f"🛡️ [DatabaseBackup] 已完成本地数据库自动快照备份: {backup_file.name} (保留最近 {max_backups} 份)")
        return str(backup_file)
    except Exception as e:
        logger.warning(f"⚠️ [DatabaseBackup] 备份数据库异常 (非致命): {e}")
        return None


def init_db():
    """初始化数据库表结构并自动平滑升级增量字段 (兼容 SQLite 与 MySQL)"""
    from sqlalchemy import inspect, text
    from . import models  # 确保所有模型类已装载

    Base.metadata.create_all(bind=engine)

    # 针对已有旧表结构平滑补齐阶段 2 新增监控列，避免 OperationalError
    inspector = inspect(engine)
    if "performance_metrics" in inspector.get_table_names():
        existing_cols = {col["name"] for col in inspector.get_columns("performance_metrics")}
        expected_migrations = [
            ("page_scope", "VARCHAR(256)"),
            ("js_heap_total_mb", "FLOAT DEFAULT 0.0"),
            ("canvas_count", "INTEGER DEFAULT 0"),
            ("webrtc_fps", "FLOAT"),
            ("chrome_pid", "INTEGER"),
            ("chrome_cpu_percent", "FLOAT"),
            ("chrome_memory_mb", "FLOAT"),
        ]
        with engine.begin() as conn:
            for col_name, col_ddl in expected_migrations:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE performance_metrics ADD COLUMN {col_name} {col_ddl}"))

    # 针对已有 bug_records 表平滑补齐 remark 备注列
    if "bug_records" in inspector.get_table_names():
        bug_cols = {col["name"] for col in inspector.get_columns("bug_records")}
        if "remark" not in bug_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE bug_records ADD COLUMN remark TEXT"))


