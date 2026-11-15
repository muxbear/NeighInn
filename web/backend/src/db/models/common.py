from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

# 跨库类型：生产 PostgreSQL 使用 JSONB/BigInteger；
# 集成测试 SQLite 退化为 JSON/Integer（行为等价，测试可离线运行）。
JsonDict = JSON().with_variant(JSONB(), "postgresql")
BigIntPk = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    """统一 UTC 时间（naive）。PostgreSQL timestamptz 与 SQLite 均可安全比较。"""
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """从 SQLite 读回的 datetime 为 naive；统一视为 UTC 后再比较。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


class TimestampMixin:
    """时间戳使用客户端默认值（utcnow）而非 server_default/onupdate=func.now()：
    避免 flush 后属性过期触发惰性刷新（异步会话下抛 MissingGreenlet）。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class VersionMixin:
    """乐观锁版本列。更新必须 WHERE id=? AND version=?，冲突返回 40903。"""

    version: Mapped[int] = mapped_column(default=0, nullable=False)


class Entity(TimestampMixin, VersionMixin, Base):
    """业务实体公共基类：created_at / updated_at / version。
    必须继承 Base 才会注册进 metadata（抽象基类，不单独建表）。"""

    __abstract__ = True
