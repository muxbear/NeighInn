from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity


class Region(Base):
    """行政区划树：PROVINCE / CITY / DISTRICT / STREET。"""

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("regions.id"), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sort: Mapped[int] = mapped_column(default=0)


class Community(Entity):
    """社区档案（W04-01）。坐标是距离计算的数据基础（SRS 8.2：门址级精度，误差 ≤50m）；
    邻近规则（半径/最大小区数/跨小区开关）由参数配置（W04-02、BR-03）。
    停用后移动端不可见，已绑定业主保留历史数据。"""

    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("regions.id"), index=True)
    street_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("regions.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(32), default="商品房社区")
    address: Mapped[str] = mapped_column(String(255), default="")
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    property_contact_enc: Mapped[str] = mapped_column(Text, default="")
    households: Mapped[int] = mapped_column(default=0)
    population: Mapped[int] = mapped_column(default=0)
    manager_name: Mapped[str] = mapped_column(String(64), default="")
    # OPERATING / PREPARING / SUSPENDED
    status: Mapped[str] = mapped_column(String(24), default="OPERATING", index=True)
    opened_at: Mapped[date | None] = mapped_column(Date)
