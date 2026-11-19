from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, TimestampMixin, utcnow

admin_user_roles = Table(
    "admin_user_roles",
    Base.metadata,
    Column("admin_user_id", BigInteger, ForeignKey("admin_users.id"), primary_key=True),
    Column("role_id", BigInteger, ForeignKey("roles.id"), primary_key=True, index=True),
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
    Column("community_id", BigInteger, ForeignKey("communities.id"), primary_key=True, index=True),
)


class AdminUser(TimestampMixin, Base):
    """后台管理员（独立账号体系，D-05）。强制 2FA（W01-01）；
    登录失败 5 次锁定 15 分钟；超级管理员不可删除/停用，至少保留 1 个。"""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    # 关联平台 C 端账号（platform_users.id，移动端身份）。一个平台账号最多一个后台身份。
    platform_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("platform_users.id"), unique=True, index=True
    )
    # 关联住户档案：住户授权来源或用户管理手工绑定。
    resident_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("residents.id"), index=True
    )
    # MANUAL（用户管理创建）/ RESIDENT（社区业主授权）
    source: Mapped[str] = mapped_column(String(16), default="MANUAL", index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    real_name: Mapped[str] = mapped_column(String(64))
    phone_enc: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    avatar_text: Mapped[str] = mapped_column(String(8), default="")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_secret_enc: Mapped[str] = mapped_column(String(128), default="")
    # 恢复码（哈希存储，一次性使用）；登录时可用恢复码代替 TOTP
    recovery_codes_hash: Mapped[dict] = mapped_column(JsonDict, default=list)
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=0)
    # 首登/重置后强制改密；改密、撤销、停用、重置密码时自增会话版本使旧会话立即失效。
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=0)


class Role(TimestampMixin, Base):
    """角色（W01-02）。data_scope：ALL / COMMUNITY_SET / OWN_COMMUNITY / SELF；
    多角色取并集，ALL 优先；内置角色不可删除。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    data_scope: Mapped[str] = mapped_column(String(24), default="OWN_COMMUNITY")
    # 是否允许在「社区业主」页授予住户；仅 OWN_COMMUNITY 角色可开启。
    assignable_to_resident: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, default=0)


class Permission(TimestampMixin, Base):
    """权限/菜单/资源。权限码唯一，格式 {domain}:{resource}:{action}。
    运行时鉴权只读本表与 role_permissions，不直接查页面资源表。"""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("permissions.id"))
    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # DIR / MENU / BUTTON / API / FIELD
    type: Mapped[str] = mapped_column(String(16), default="BUTTON")
    route: Mapped[str] = mapped_column(String(255), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class AuditLog(Base):
    """操作审计（W01-03）：操作人、动作、对象、前后快照、IP、UA、traceId、结果。
    只追加不可改删；留存 ≥3 年；资金/权限类必须同步写成功（NF-11）。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    actor_name: Mapped[str] = mapped_column(String(64), default="系统")
    actor_role: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), default="", index=True)
    resource_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    before_snapshot: Mapped[dict | None] = mapped_column(JsonDict)
    after_snapshot: Mapped[dict | None] = mapped_column(JsonDict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    result: Mapped[str] = mapped_column(String(16), default="SUCCESS", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class IdempotencyKey(Base):
    """写接口幂等（SRS 8.3、后台详设 5.8.3）。
    同一 key 不同请求体 → 40902；处理中重复请求 → 40901。"""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # PROCESSING / COMPLETED
    status: Mapped[str] = mapped_column(String(16), default="PROCESSING")
    response_json: Mapped[dict | None] = mapped_column(JsonDict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxEvent(Base):
    """事务性发件箱（后台详设 5.8.2）：业务事务内写入，Relay 投递到 RabbitMQ；
    失败指数退避，超 5 次进死信并告警。"""

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), default="")
    aggregate_id: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JsonDict, default=dict)
    # PENDING / PUBLISHED / DEAD
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """消费幂等：同一事件同一消费者只处理一次。"""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParameterKey(Base):
    """参数键树（W04-05）。发布后生效；高危参数修改需二次确认 + 原因 + 审计。"""

    __tablename__ = "parameter_keys"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("parameter_keys.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # GROUP / KEY
    kind: Mapped[str] = mapped_column(String(8), default="KEY")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="启用")


class ParameterItem(Entity):
    """参数项。移动端 AppConfig（照片上下限/有效期/超时/邻近半径等）由此下发；
    保存 + 发布两阶段生效（后台详设 4.7.11）。"""

    __tablename__ = "parameter_items"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    parameter_key_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("parameter_keys.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="启用")
    updated_by: Mapped[int | None] = mapped_column(BigInteger)


class Dictionary(Base):
    __tablename__ = "dictionaries"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="启用")


class DictionaryItem(Base):
    __tablename__ = "dictionary_items"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    dictionary_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dictionaries.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(64))
    tone: Mapped[str] = mapped_column(String(16), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="启用")


class FileObject(Base):
    """文件元数据。认证材料/纠纷证据/报修照片存私有桶（ni-private），
    签名 URL 10 分钟短时效访问（SRS 9.2、D-08）。"""

    __tablename__ = "file_objects"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    # public / private / system
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExportJob(Base):
    """报表导出任务（W08-03）：默认脱敏、文件 7 天过期、下载写审计；
    明文导出需双人审批 + 动态水印 + 24 小时过期（后台详设 6.6）。"""

    __tablename__ = "export_jobs"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    params: Mapped[dict] = mapped_column(JsonDict, default=dict)
    # QUEUED / GENERATING / COMPLETED / FAILED / EXPIRED
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    file_object_id: Mapped[int | None] = mapped_column(BigInteger)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, index=True)
    error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
