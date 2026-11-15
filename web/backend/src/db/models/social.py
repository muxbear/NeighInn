from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, utcnow


class Friend(Base):
    """好友关系（BR-14）：仅限已实名用户互加；好友数量上限默认 500（可配置）。
    状态机：申请中 → 已好友；已好友 → 已删除 / 已拉黑。"""

    __tablename__ = "friends"
    __table_args__ = (UniqueConstraint("user_id", "friend_id", name="uq_friends_pair"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    friend_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    # ACTIVE / DELETED / BLOCKED
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    remark: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FriendRequest(Base):
    """好友申请（M05-03）：附验证语（需过内容安全审核 A-09）；红点提醒。"""

    __tablename__ = "friend_requests"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    from_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    to_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Entity):
    """会话（M05-02/04）：物品会话与好友私信两类。好友私信不依赖具体物品。"""

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("type", "item_id", "user_a_id", "user_b_id", name="uq_conversation"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    # ITEM / FRIEND
    type: Mapped[str] = mapped_column(String(16), index=True)
    item_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_a_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    user_b_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    last_message: Mapped[str] = mapped_column(String(500), default="")
    last_seq: Mapped[int] = mapped_column(default=0)


class Message(Base):
    """消息（M05）。client_msg_id 幂等；内容安全审核（A-09）命中违规撤回并提示；
    敏感词/外链命中展示平台风险提醒（M05-05）。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    client_msg_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    # TEXT / IMAGE / ITEM / SYSTEM
    type: Mapped[str] = mapped_column(String(16), default="TEXT")
    content: Mapped[str] = mapped_column(Text, default="")
    image_key: Mapped[str] = mapped_column(String(255), default="")
    # SENT / READ / RECALLED
    status: Mapped[str] = mapped_column(String(16), default="SENT", index=True)
    # PASSED / PENDING / BLOCKED（内容安全审核）
    audit_status: Mapped[str] = mapped_column(String(16), default="PASSED", index=True)
    risk_flag: Mapped[str] = mapped_column(String(32), default="")
    seq: Mapped[int] = mapped_column(default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
