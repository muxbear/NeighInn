from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


admin_user_roles = Table(
    "admin_user_roles",
    Base.metadata,
    Column("admin_user_id", BigInteger, ForeignKey("admin_users.id"), primary_key=True),
    Column("role_id", BigInteger, ForeignKey("roles.id"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", BigInteger, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", BigInteger, ForeignKey("permissions.id"), primary_key=True),
)

admin_user_communities = Table(
    "admin_user_communities",
    Base.metadata,
    Column("admin_user_id", BigInteger, ForeignKey("admin_users.id"), primary_key=True),
    Column("community_id", BigInteger, ForeignKey("communities.id"), primary_key=True),
)


class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    real_name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    avatar_text: Mapped[str] = mapped_column(String(8), default="夏")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_secret: Mapped[str | None] = mapped_column(String(64))
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=0)


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    data_scope: Mapped[str] = mapped_column(String(24), default="OWN_COMMUNITY")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    members: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("permissions.id"))
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(16), default="BUTTON")
    route: Mapped[str | None] = mapped_column(String(255))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("regions.id"), index=True)
    level: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Community(TimestampMixin, Base):
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("regions.id"), index=True)
    street_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("regions.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(32), default="商品房社区")
    address: Mapped[str] = mapped_column(String(255), default="")
    longitude: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[str | None] = mapped_column(String(32))
    property_contact: Mapped[str | None] = mapped_column(String(64))
    households: Mapped[int] = mapped_column(Integer, default=0)
    population: Mapped[int] = mapped_column(Integer, default=0)
    manager_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="OPERATING")
    opened_at: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=0)


class Resident(TimestampMixin, Base):
    __tablename__ = "residents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(64), index=True)
    gender: Mapped[str] = mapped_column(String(8), default="女")
    phone: Mapped[str] = mapped_column(String(32), default="")
    identity_type: Mapped[str] = mapped_column(String(16), default="业主", index=True)
    building: Mapped[str] = mapped_column(String(128), default="")
    relationship: Mapped[str] = mapped_column(String(64), default="")
    certification_status: Mapped[str] = mapped_column(String(16), default="已认证", index=True)
    certification_no: Mapped[str] = mapped_column(String(32), default="—")
    level: Mapped[str] = mapped_column(String(24), default="普通用户")
    status: Mapped[str] = mapped_column(String(16), default="正常")
    joined_at: Mapped[str] = mapped_column(String(16), default="")
    version: Mapped[int] = mapped_column(Integer, default=0)


class Broadcast(TimestampMixin, Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    owner: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="邻里播报")
    performance: Mapped[str] = mapped_column(String(128), default="—")
    status: Mapped[str] = mapped_column(String(24), default="待审核", index=True)
    updated_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    content: Mapped[str] = mapped_column(Text, default="")
    media: Mapped[list] = mapped_column(JSONB, default=list)


class Item(TimestampMixin, Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    seller: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="家居日用")
    price_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    performance: Mapped[str] = mapped_column(String(128), default="—")
    status: Mapped[str] = mapped_column(String(24), default="待审核", index=True)
    updated_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    trade_type: Mapped[str] = mapped_column(String(16), default="MONETARY")
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(255), default="")
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)


class HelpRequest(TimestampMixin, Base):
    __tablename__ = "help_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    owner: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="邻里帮忙")
    performance: Mapped[str] = mapped_column(String(128), default="—")
    status: Mapped[str] = mapped_column(String(24), default="待响应", index=True)
    updated_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    description: Mapped[str] = mapped_column(Text, default="")
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)


class LifePost(TimestampMixin, Base):
    __tablename__ = "life_posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    owner: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="周末去哪")
    performance: Mapped[str] = mapped_column(String(128), default="—")
    status: Mapped[str] = mapped_column(String(24), default="草稿", index=True)
    updated_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    content: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str] = mapped_column(String(255), default="")


class Notice(TimestampMixin, Base):
    __tablename__ = "notices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(64), default="全部社区")
    publisher: Mapped[str] = mapped_column(String(64), default="运营中心")
    read_progress: Mapped[str] = mapped_column(String(32), default="—")
    status: Mapped[str] = mapped_column(String(24), default="已发布", index=True)
    published_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    content: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)


class NotificationTask(TimestampMixin, Base):
    __tablename__ = "notification_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    channels: Mapped[str] = mapped_column(String(64), default="站内信")
    target: Mapped[str] = mapped_column(String(128), default="全部用户")
    delivery: Mapped[str] = mapped_column(String(48), default="—")
    status: Mapped[str] = mapped_column(String(24), default="草稿", index=True)
    sent_label: Mapped[str] = mapped_column(String(32), default="未发送")
    template: Mapped[str] = mapped_column(Text, default="")


class RepairOrder(TimestampMixin, Base):
    __tablename__ = "repair_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    reporter: Mapped[str] = mapped_column(String(64), default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    assignee: Mapped[str] = mapped_column(String(64), default="待指派")
    status: Mapped[str] = mapped_column(String(24), default="待派单", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="普通")
    sla_label: Mapped[str] = mapped_column(String(32), default="—")
    description: Mapped[str] = mapped_column(Text, default="")


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    content: Mapped[str] = mapped_column(String(255))
    submitter: Mapped[str] = mapped_column(String(64), default="匿名用户")
    category: Mapped[str] = mapped_column(String(32), default="社区建议")
    assignee: Mapped[str] = mapped_column(String(64), default="待指派")
    status: Mapped[str] = mapped_column(String(24), default="待回复", index=True)
    created_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    reply: Mapped[str] = mapped_column(Text, default="")


class SysPage(TimestampMixin, Base):
    __tablename__ = "sys_pages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    route: Mapped[str] = mapped_column(String(255))
    region: Mapped[str] = mapped_column(String(64), default="系统主导航")
    icon: Mapped[str] = mapped_column(String(32), default="AppWindow")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="启用")
    sort: Mapped[int] = mapped_column(Integer, default=0)


class PageResource(TimestampMixin, Base):
    __tablename__ = "page_resources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sys_pages.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16), default="按钮")
    code: Mapped[str] = mapped_column(String(128), unique=True)
    permission_code: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="启用")


class ParameterKey(Base):
    __tablename__ = "parameter_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("parameter_keys.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(8), default="KEY")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="启用")
    parent: Mapped[ParameterKey | None] = relationship(
        "ParameterKey", remote_side=[id], back_populates="children"
    )
    children: Mapped[list[ParameterKey]] = relationship(
        "ParameterKey", back_populates="parent", cascade="all, delete-orphan"
    )


class ParameterItem(TimestampMixin, Base):
    __tablename__ = "parameter_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parameter_key_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("parameter_keys.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="启用")
    updated_label: Mapped[str] = mapped_column(String(32), default="刚刚")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    actor_name: Mapped[str] = mapped_column(String(64), default="系统")
    action: Mapped[str] = mapped_column(String(128))
    resource_type: Mapped[str] = mapped_column(String(64), default="")
    resource_id: Mapped[str] = mapped_column(String(64), default="")
    before_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    after_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str] = mapped_column(String(64), default="")
    trace_id: Mapped[str] = mapped_column(String(32), default="")
    result: Mapped[str] = mapped_column(String(16), default="SUCCESS")
    created_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformUser(TimestampMixin, Base):
    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_type: Mapped[str] = mapped_column(String(16), default="社区居民")
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32), default="")
    identity: Mapped[str] = mapped_column(String(64), default="")
    community_name: Mapped[str] = mapped_column(String(64), default="")
    role_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="正常")
    last_active_label: Mapped[str] = mapped_column(String(32), default="刚刚")


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    txn_no: Mapped[str] = mapped_column(String(32), unique=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True)
    user_name: Mapped[str] = mapped_column(String(64), default="")
    type: Mapped[str] = mapped_column(String(24), default="支付托管")
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    channel: Mapped[str] = mapped_column(String(24), default="微信支付")
    status: Mapped[str] = mapped_column(String(24), default="成功")
    channel_txn_no: Mapped[str] = mapped_column(String(64), default="")
    created_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Withdrawal(TimestampMixin, Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    withdrawal_no: Mapped[str] = mapped_column(String(32), unique=True)
    user_name: Mapped[str] = mapped_column(String(64))
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    fee_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    account_masked: Mapped[str] = mapped_column(String(64), default="")
    risk_result: Mapped[str] = mapped_column(String(32), default="通过")
    status: Mapped[str] = mapped_column(String(24), default="待审核", index=True)
    created_label: Mapped[str] = mapped_column(String(32), default="刚刚")
    reviewer: Mapped[str] = mapped_column(String(64), default="")
    review_note: Mapped[str] = mapped_column(String(255), default="")


class Reconciliation(Base):
    __tablename__ = "reconciliations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(24))
    bill_date: Mapped[str] = mapped_column(String(16))
    channel_amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    platform_amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    diff_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    diff_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="一致")
    created_label: Mapped[str] = mapped_column(String(32), default="刚刚")


class OrderRecord(Base):
    __tablename__ = "order_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True)
    item_title: Mapped[str] = mapped_column(String(120))
    buyer: Mapped[str] = mapped_column(String(64), default="")
    seller: Mapped[str] = mapped_column(String(64), default="")
    trade_type: Mapped[str] = mapped_column(String(16), default="货币")
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(24), default="已完成")
    escrow_status: Mapped[str] = mapped_column(String(24), default="已放款")
    created_label: Mapped[str] = mapped_column(String(32), default="刚刚")


class Dispute(TimestampMixin, Base):
    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dispute_no: Mapped[str] = mapped_column(String(32), unique=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    initiator: Mapped[str] = mapped_column(String(64), default="")
    respondent: Mapped[str] = mapped_column(String(64), default="")
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(24), default="待受理", index=True)
    statement: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    mediator: Mapped[str] = mapped_column(String(64), default="")
    created_label: Mapped[str] = mapped_column(String(32), default="刚刚")


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    trend: Mapped[dict] = mapped_column(JSONB, default=dict)
    distribution: Mapped[dict] = mapped_column(JSONB, default=dict)
    activities: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileObject(Base):
    __tablename__ = "file_objects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
