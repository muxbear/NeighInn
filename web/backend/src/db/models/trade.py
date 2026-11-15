from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


class Order(Entity):
    """订单（SRS 9.1 Order、4.3 状态机）。三种交易方式共用聚合：
    货币交易走担保支付（BR-11）；赠与申请-确认-交割（BR-12）；互换含交换物品快照（BR-13）。
    同一物品同一时刻只能有一个有效订单（BR-08），由服务层以行锁/唯一约束保证。

    状态机见 domain/enums.py OrderStatus / state.py。"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("items.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    seller_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    trade_type: Mapped[str] = mapped_column(String(16), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    # 互换物品快照：[{"item_id","title","image","condition"}]（BR-13）
    offered_items: Mapped[dict] = mapped_column(JsonDict, default=list)
    status: Mapped[str] = mapped_column(String(24), default="PENDING_PAYMENT", index=True)
    escrow_status: Mapped[str] = mapped_column(String(24), default="UNPAID", index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    cancel_reason: Mapped[str] = mapped_column(String(255), default="")
    # 预约验货（M06-01/02：时间、地点、备注、状态）
    appointment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appointment_place: Mapped[str] = mapped_column(String(128), default="")
    appointment_note: Mapped[str] = mapped_column(String(255), default="")
    appointment_status: Mapped[str] = mapped_column(String(16), default="NONE")
    # 超时控制（支付 30min / 确认 48h / 放款 72h，均可配置）
    pay_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirm_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderEvent(Base):
    """订单时间轴与双方确认记录（M06-04/09）。每次状态迁移与双方确认均追加，
    成交快照（M06-12）由本表 + 订单/物品快照导出。"""

    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), index=True)
    # CREATED / PAID / ESCROWED / APPOINTED / INSPECT_SATISFIED / INSPECT_REJECTED /
    # RELEASED / REFUNDED / CONFIRMED_BY_BUYER / CONFIRMED_BY_SELLER / DISPUTED / CANCELLED / COMPLETED
    event: Mapped[str] = mapped_column(String(32), index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="SYSTEM")
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(String(500), default="")
    payload: Mapped[dict] = mapped_column(JsonDict, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    """互评（M06-10）：仅真实交易双方可互评；赠与交易同样计入信用（BR-12）。
    评分 1–5 星 + 标签（描述相符/态度好/守时/物超所值等），评价计入信用流水。"""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    reviewee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    tags: Mapped[dict] = mapped_column(JsonDict, default=list)
    content: Mapped[str] = mapped_column(String(500), default="")
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    # BUYER_TO_SELLER / SELLER_TO_BUYER
    direction: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
