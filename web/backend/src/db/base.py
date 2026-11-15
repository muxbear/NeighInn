from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    # 固定关闭 echo：echo=True 会让 SQLAlchemy 额外安装默认 handler，导致 SQL 重复输出。
    # 需要排查 SQL 时设置 SQL_ECHO=true，由 src/core/logging.py 调整 sqlalchemy.engine 级别。
    echo=False,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """仅开发环境兜底建表；生产一律走 Alembic 迁移（见 alembic/versions）。"""
    if settings.app_env != "dev":
        return
    from src.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
