from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


class AppNotification(Base):
    """C 端站内通知（M07-03）：交易/互动/社区分类，未读数与已读回执。
    route 为前端路由描述（item/life/broadcast/zone/messages/order）。"""

    __tablename__ = "app_notifications"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    # TRADE / INTERACTION / COMMUNITY
    category: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    icon: Mapped[str] = mapped_column(String(32), default="")
    tag: Mapped[str] = mapped_column(String(32), default="")
    route: Mapped[dict] = mapped_column(JsonDict, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notice(Entity):
    """公告（后台公告管理 → 移动端社区通知）。发布前必须预览移动端效果；
    覆盖范围支持全部/指定社区；附件私有桶。"""

    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    community_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(64), default="全部社区")
    publisher_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    attachments: Mapped[dict] = mapped_column(JsonDict, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoticeRead(Base):
    """公告阅读记录（阅读进度统计，W04-04）。"""

    __tablename__ = "notice_reads"
    __table_args__ = (UniqueConstraint("notice_id", "user_id", name="uq_notice_read"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    notice_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("notices.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationTemplate(Entity):
    """通知模板（站内信/短信/Push/服务通知）。"""

    __tablename__ = "notification_templates"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, default="")
    channels: Mapped[str] = mapped_column(String(64), default="IN_APP")
    status: Mapped[str] = mapped_column(String(16), default="启用")


class NotificationTask(Entity):
    """通知任务（后台触达中心）。发送前必须审核模板；
    目标人群排除黑名单与退订用户；同类事件 5 分钟聚合去重（移动端详设 11.5）。"""

    __tablename__ = "notification_tasks"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notification_templates.id"))
    channels: Mapped[str] = mapped_column(String(64), default="IN_APP")
    # ALL / COMMUNITY / ROLE / TAG / IMPORTED
    target_type: Mapped[str] = mapped_column(String(16), default="ALL")
    target_filter: Mapped[dict] = mapped_column(JsonDict, default=dict)
    # DRAFT → PENDING_APPROVAL → SCHEDULED → SENDING → COMPLETED | PARTIAL_FAILED / CANCELLED
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JsonDict, default=dict)
    created_by: Mapped[int | None] = mapped_column(BigInteger)


class NotificationRecord(Base):
    """投递明细（送达/阅读/失败重试，W 通知任务页「送达/阅读」数据来源）。"""

    __tablename__ = "notification_records"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notification_tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    # IN_APP / SMS / PUSH / SERVICE
    channel: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    content: Mapped[str] = mapped_column(String(500), default="")
    # PENDING / SENT / DELIVERED / READ / FAILED
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    error: Mapped[str] = mapped_column(String(255), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
