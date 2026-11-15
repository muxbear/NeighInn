from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


class Dispute(Entity):
    """纠纷（M06-11/W05-02）。结论前必须有双方陈述与证据；资金类结论走
    FinanceAdjustment 双人复核；已解决不可重开，重复争议新建纠纷。"""

    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    dispute_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), index=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    initiator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    respondent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    # OPEN → MEDIATING → PENDING_REVIEW → RESOLVED / CLOSED
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    statement: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    # CONTINUE / CANCEL_REFUND / FORCE_RELEASE / PARTIAL_REFUND / CREDIT / ACCOUNT_FREEZE
    conclusion_type: Mapped[str] = mapped_column(String(24), default="")
    mediator_id: Mapped[int | None] = mapped_column(BigInteger)


class DisputeEvidence(Base):
    """纠纷证据（私有桶，签名 URL 短时效访问，SRS 9.2）。"""

    __tablename__ = "dispute_evidences"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    dispute_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("disputes.id"), index=True)
    uploader_id: Mapped[int] = mapped_column(BigInteger, index=True)
    object_key: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DisputeMessage(Base):
    """调解沟通记录（内部留痕，不可篡改）。"""

    __tablename__ = "dispute_messages"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    dispute_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("disputes.id"), index=True)
    # ADMIN / INITIATOR / RESPONDENT / SYSTEM
    sender_type: Mapped[str] = mapped_column(String(16))
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RepairOrder(Entity):
    """报事报修（物业向）。注意：移动端当前无入口，属二期或需补移动端入口的孤立模块。"""

    __tablename__ = "repair_orders"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    reporter_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    location: Mapped[str] = mapped_column(String(128), default="")
    photos: Mapped[list] = mapped_column(JsonDict, default=list)
    priority: Mapped[str] = mapped_column(String(16), default="普通")
    assignee_id: Mapped[int | None] = mapped_column(BigInteger)
    # PENDING_ASSIGN → PROCESSING → PENDING_ACCEPTANCE → COMPLETED；任意非终态 → CLOSED
    status: Mapped[str] = mapped_column(String(24), default="PENDING_ASSIGN", index=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(Entity):
    """投诉建议。回复需过内容安全审核（A-09）。"""

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    submitter_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    anonymous: Mapped[str] = mapped_column(String(8), default="否")
    category: Mapped[str] = mapped_column(String(32), default="社区建议", index=True)
    content: Mapped[str] = mapped_column(String(1000), nullable=False)
    contact_enc: Mapped[str] = mapped_column(String(255), default="")
    attachments: Mapped[list] = mapped_column(JsonDict, default=list)
    assignee_id: Mapped[int | None] = mapped_column(BigInteger)
    # OPEN / PROCESSING / REPLIED / CLOSED
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    reply: Mapped[str] = mapped_column(Text, default="")
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    satisfaction: Mapped[str] = mapped_column(String(16), default="")
