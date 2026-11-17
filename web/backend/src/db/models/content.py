from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


class Broadcast(Entity):
    """社区喇叭（移动端喇叭站：紧急求助/免费上新/悬赏服务/新上架事件流）。
    与移动端 Broadcast 模型对齐；发布前必须审核（状态机见 enums.ContentStatus）。"""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    author_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # URGENT_HELP / FREE_NEW / REWARD / NEW_ITEM
    type: Mapped[str] = mapped_column(String(24), default="NEW_ITEM", index=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    media: Mapped[dict] = mapped_column(JsonDict, default=list)
    tone: Mapped[str] = mapped_column(String(16), default="new")
    facts: Mapped[dict] = mapped_column(JsonDict, default=list)
    status: Mapped[str] = mapped_column(String(20), default="PENDING_REVIEW", index=True)
    response_count: Mapped[int] = mapped_column(default=0)
    important: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LifePost(Entity):
    """社区生活动态（M02/M 小区生活：小区风景/邻里日常/个人风采/萌宠生活）。"""

    __tablename__ = "life_posts"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="邻里日常", index=True)
    # VIDEO / GALLERY
    media_type: Mapped[str] = mapped_column(String(16), default="GALLERY")
    cover_key: Mapped[str] = mapped_column(String(255), default="")
    media: Mapped[dict] = mapped_column(JsonDict, default=list)
    status: Mapped[str] = mapped_column(String(20), default="PENDING_REVIEW", index=True)
    stats: Mapped[dict] = mapped_column(JsonDict, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LifeComment(Base):
    __tablename__ = "life_comments"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("life_posts.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PUBLISHED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemComment(Base):
    """物品留言（M05-01/BR-14）：公开可见，需过内容安全审核（A-09）；
    卖家可删除恶意留言并举报。"""

    __tablename__ = "item_comments"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("items.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    # PUBLISHED / HIDDEN / DELETED（内容安全审核联动）
    status: Mapped[str] = mapped_column(String(16), default="PUBLISHED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HelpRequest(Entity):
    """邻里互助/服务（求助/提供两种形态，与移动端 ServicePost 对齐）。
    同时只有一个匹配中的响应（后台详设 5.6.1）。"""

    __tablename__ = "help_requests"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    requester_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    # HELP（求助）/ OFFER（提供）
    kind: Mapped[str] = mapped_column(String(16), default="HELP", index=True)
    category: Mapped[str] = mapped_column(String(32), default="邻里帮忙")
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    expected_time: Mapped[str] = mapped_column(String(64), default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    reward: Mapped[str] = mapped_column(String(64), default="")
    # GALLERY / VIDEO；media 存对象键，展示时签发 URL（与生活动态一致）。
    media: Mapped[dict] = mapped_column(JsonDict, default=list)
    cover_key: Mapped[str] = mapped_column(String(255), default="")
    media_type: Mapped[str] = mapped_column(String(16), default="GALLERY")
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    matched_helper_id: Mapped[int | None] = mapped_column(BigInteger)
    closed_reason: Mapped[str] = mapped_column(String(255), default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HelpResponse(Base):
    """互助响应（含撮合履约记录，W 后台人工撮合的依据）。"""

    __tablename__ = "help_responses"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("help_requests.id"), index=True)
    responder_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    # PENDING / ACCEPTED / REJECTED / CANCELLED
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Report(Base):
    """举报（W03-04/W05-03）：对象类型/ID、原因、证据、处理记录。
    覆盖物品/用户/会话/留言/私信/生活内容。"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    reporter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    # ITEM / USER / CONVERSATION / COMMENT / MESSAGE / LIFE_POST
    target_type: Mapped[str] = mapped_column(String(24), index=True)
    target_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JsonDict, default=list)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    handler_id: Mapped[int | None] = mapped_column(BigInteger)
    result: Mapped[str] = mapped_column(String(500), default="")
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
