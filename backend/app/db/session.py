from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import ROOT_DIR, settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明式模型基类。"""


# 数据目录固定在项目根目录，避免从 backend 启动时误创建 backend/data。
(ROOT_DIR / "data").mkdir(exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 数据库依赖，确保请求结束后释放连接。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """导入模型并创建数据表，适合课程项目的本地快速启动。"""
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_compatible_columns()


def _ensure_sqlite_compatible_columns() -> None:
    """为已存在的 SQLite 旧表补充新列，避免课程演示阶段手动迁移。"""
    if not settings.database_url.startswith("sqlite"):
        return

    required_columns = {
        "guide_sources": {
            "raw_url": "TEXT",
            "resolved_url": "TEXT",
            "category": "TEXT",
            "crawl_status": "TEXT DEFAULT 'indexed'",
        },
        "users": {
            "username": "TEXT",
            "password_salt": "TEXT",
            "password_hash": "TEXT",
            "display_name": "TEXT",
            "home_city": "TEXT",
            "travel_style": "TEXT",
            "budget_level": "INTEGER DEFAULT 2",
            "updated_at": "TIMESTAMP",
        },
        "conversations": {
            "user_id": "INTEGER",
            "is_favorite": "INTEGER DEFAULT 0",
            "tags_json": "TEXT",
            "destination_city": "TEXT",
            "budget": "INTEGER",
            "start_date": "TEXT",
        },
        "guide_import_records": {
            "mode": "TEXT DEFAULT 'link'",
            "content": "TEXT",
            "structured_json": "TEXT",
            "category": "TEXT",
            "resolved_url": "TEXT",
            "author": "TEXT",
        },
        "guide_import_tasks": {
            "category": "TEXT",
            "force_reimport": "INTEGER DEFAULT 0",
            "mode": "TEXT DEFAULT 'preview'",
            "status": "TEXT DEFAULT 'queued'",
            "stage": "TEXT DEFAULT 'queued'",
            "progress": "INTEGER DEFAULT 5",
            "title": "TEXT",
            "message": "TEXT",
            "result_json": "TEXT",
            "error_message": "TEXT",
            "updated_at": "TIMESTAMP",
            "finished_at": "TIMESTAMP",
        },
    }

    with engine.begin() as connection:
        for table_name, columns in required_columns.items():
            existing = {
                row[1]
                for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            }
            for column_name, column_sql in columns.items():
                if column_name not in existing:
                    # 仅对本项目内固定表名和列名执行补列，不接收用户输入，避免 SQL 注入风险。
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
                    )
