from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, utcnow


class Favorite(Base):
    """收藏（M02-07）：物品/服务/生活动态统一收藏。"""

    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "target_type", "target_id", name="uq_favorite"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    # ITEM / SERVICE / LIFE / BROADCAST
    target_type: Mapped[str] = mapped_column(String(16), index=True)
    target_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ViewHistory(Base):
    """浏览足迹（M02-07/M07-02，上限 100 条由服务层裁剪）。"""

    __tablename__ = "view_histories"
    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_view_history"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("items.id"), index=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchHistory(Base):
    __tablename__ = "search_histories"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HotKeyword(Base):
    """搜索热词（后台可维护，M02-05）。"""

    __tablename__ = "hot_keywords"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(64), unique=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="启用")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
