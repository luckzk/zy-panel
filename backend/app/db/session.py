"""数据库引擎与会话：SQLite 文件默认落在 ./data/oci-panel.db，启动自动建表。"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings
from .base import Base


def _ensure_sqlite_dir(database_url: str) -> None:
    """SQLite 文件的父目录不存在时自动创建。"""
    if database_url.startswith("sqlite:///"):
        path = database_url[len("sqlite:///"):]
        # 兼容 sqlite:////absolute/path 写法
        if path.startswith("/"):
            path = "/" + path.lstrip("/")
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)


_settings = get_settings()


def _resolve_database_url(url: str) -> str:
    """品牌重命名迁移：默认库文件名由 oci-panel.db 改为 zy-panel.db；
    若老文件存在而新文件不存在，继续沿用老文件，避免数据丢失。"""
    if url == "sqlite:///./data/zy-panel.db":
        old, new = "./data/oci-panel.db", "./data/zy-panel.db"
        if os.path.exists(old) and not os.path.exists(new):
            return "sqlite:///./data/oci-panel.db"
    return url


DATABASE_URL = _resolve_database_url(_settings.database_url)
_ensure_sqlite_dir(DATABASE_URL)

_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """创建所有表（不存在才建），并为已存在的表补齐新增列（轻量迁移）。"""
    from . import models  # noqa: F401  确保模型被注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    _migrate_missing_columns()


# 新增列的轻量迁移：表名 -> [(列名, SQLite 类型定义)]
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "tenants": [
        ("last_tested_at", "DATETIME"),
        ("test_status", "VARCHAR(16) DEFAULT ''"),
        ("account_type", "VARCHAR(16) DEFAULT ''"),
        ("provider", "VARCHAR(16) DEFAULT 'oci'"),
        ("credentials_enc", "TEXT"),
    ],
    "snatch_tasks": [
        ("compartment_id", "VARCHAR(255) DEFAULT ''"),
        ("ocpus", "FLOAT"),
        ("memory_in_gbs", "FLOAT"),
        ("display_name", "VARCHAR(255) DEFAULT ''"),
        ("assign_public_ip", "BOOLEAN DEFAULT 1"),
        ("ssh_public_key", "TEXT"),
        ("last_attempt_at", "DATETIME"),
        ("next_attempt_at", "DATETIME"),
        ("availability_domains", "TEXT"),
        ("boot_volume_id", "VARCHAR(255) DEFAULT ''"),
        ("recent_logs", "TEXT"),
    ],
    "users": [
        ("mfa_enabled", "BOOLEAN DEFAULT 0"),
    ],
    "ip_tasks": [
        ("attempts", "INTEGER DEFAULT 0"),
        ("max_retries", "INTEGER DEFAULT 3"),
        ("next_attempt_at", "DATETIME"),
        ("dns_updated", "BOOLEAN DEFAULT 0"),
    ],
}


def _migrate_missing_columns() -> None:
    """检查已有表是否缺少模型中新增的列，缺则 ALTER TABLE 补上。"""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _MIGRATION_COLUMNS.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))


def seed_admin(username: str = "admin", password: str = "admin123") -> None:
    """播种默认管理员账号（已存在则跳过）。"""
    from ..core.security import hash_password
    from . import models

    db = SessionLocal()
    try:
        exists = db.query(models.User).filter(models.User.username == username).first()
        if not exists:
            db.add(models.User(username=username, password_hash=hash_password(password), is_admin=True))
            db.commit()
    finally:
        db.close()
