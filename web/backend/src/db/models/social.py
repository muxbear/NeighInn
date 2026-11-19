from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


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


class FriendBlock(Base):
    """拉黑关系（BR-14）：有方向记录，任一方向 ACTIVE 即视为关系阻断。

    同一对用户只保留一行；解除拉黑时置为 RELEASED，再次拉黑时复用。
    """

    __tablename__ = "friend_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_friend_blocks_pair"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    blocker_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    blocked_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    community_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("communities.id"))
    reason: Mapped[str] = mapped_column(String(200), default="")
    # CHAT / LIST / PROFILE / REPORT
    source: Mapped[str] = mapped_column(String(16), default="CHAT")
    # ACTIVE / RELEASED
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FriendRemark(Base):
    """邻居备注：默认邻居关系不物化，备注单独存储，仅 owner 可见。"""

    __tablename__ = "friend_remarks"
    __table_args__ = (
        UniqueConstraint("owner_id", "peer_id", name="uq_friend_remarks_pair"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    peer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    remark: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Conversation(Entity):
    """会话（M05-02/04）：物品会话与好友私信两类。好友私信不依赖具体物品。

    同一对用户的 FRIEND 会话通过 pair_low_id/pair_high_id 保证唯一；
    ITEM 会话通过 item_id + pair 保证唯一。
    """

    __tablename__ = "conversations"
    __table_args__ = (
        # 保留旧约束，兼容已有库；新逻辑以部分唯一索引为准。
        UniqueConstraint("type", "item_id", "user_a_id", "user_b_id", name="uq_conversation"),
        Index(
            "uq_conversations_friend_pair", "pair_low_id", "pair_high_id",
            unique=True,
            postgresql_where=text("type = 'FRIEND'"),
            sqlite_where=text("type = 'FRIEND'"),
        ),
        Index(
            "uq_conversations_item_pair", "item_id", "pair_low_id", "pair_high_id",
            unique=True,
            postgresql_where=text("type = 'ITEM'"),
            sqlite_where=text("type = 'ITEM'"),
        ),
        Index("ix_conversations_user_a_updated", "user_a_id", "updated_at"),
        Index("ix_conversations_user_b_updated", "user_b_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    # ITEM / FRIEND
    type: Mapped[str] = mapped_column(String(16), index=True)
    item_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_a_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    user_b_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    pair_low_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    pair_high_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    last_message: Mapped[str] = mapped_column(String(500), default="")
    last_message_type: Mapped[str] = mapped_column(String(16), default="TEXT")
    last_sender_id: Mapped[int | None] = mapped_column(BigInteger)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seq: Mapped[int] = mapped_column(default=0)
    # 已读游标：未读数 = 对方发送且 seq > 我的游标的消息数。
    last_read_seq_a: Mapped[int] = mapped_column(default=0)
    last_read_seq_b: Mapped[int] = mapped_column(default=0)
    # 单方清空聊天记录的时间；早于该时间的消息对该用户不可见。
    cleared_at_a: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at_b: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    """消息（M05）。client_msg_id 幂等；内容安全审核（A-09）命中违规撤回并提示；
    敏感词/外链命中展示平台风险提醒（M05-05）。"""

    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "uq_messages_client_msg", "conversation_id", "sender_id", "client_msg_id",
            unique=True,
            postgresql_where=text("client_msg_id <> ''"),
            sqlite_where=text("client_msg_id <> ''"),
        ),
        Index("ix_messages_conversation_seq", "conversation_id", "seq"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    client_msg_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    # TEXT / EMOJI / IMAGE / VIDEO / VOICE / ITEM / SYSTEM
    type: Mapped[str] = mapped_column(String(16), default="TEXT")
    content: Mapped[str] = mapped_column(Text, default="")
    image_key: Mapped[str] = mapped_column(String(255), default="")
    # 表情 ID、媒体宽高、时长、缩略图等扩展字段
    extra: Mapped[dict] = mapped_column(JsonDict, default=dict)
    # SENT / READ / RECALLED
    status: Mapped[str] = mapped_column(String(16), default="SENT", index=True)
    # PASSED / PENDING / BLOCKED（内容安全审核）
    audit_status: Mapped[str] = mapped_column(String(16), default="PASSED", index=True)
    risk_flag: Mapped[str] = mapped_column(String(32), default="")
    seq: Mapped[int] = mapped_column(default=0, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
