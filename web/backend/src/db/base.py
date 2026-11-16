from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings


class Base(DeclarativeBase):
    pass


def _connect_args() -> dict:
    """PostgreSQL 会话统一使用 UTC。

    业务层时间统一为 naive UTC（utcnow()）；若数据库会话时区非 UTC（如本地开发库
    为 Asia/Shanghai），naive 时间会被 timestamptz 当作本地时间写入，导致全部
    时间戳整体偏移。显式固定会话时区可让写入/读回都是同一 UTC 瞬时。
    """
    if settings.database_url.startswith("postgresql"):
        return {"options": "-c timezone=UTC"}
    return {}


engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    connect_args=_connect_args(),
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
