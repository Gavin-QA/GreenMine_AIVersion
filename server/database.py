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


def init_db():
    """初始化数据库表结构"""
    from . import models  # 确保所有模型类已装载
    Base.metadata.create_all(bind=engine)
