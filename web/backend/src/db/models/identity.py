from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


class PlatformUser(Entity):
    """平台级 C 端账号（表 platform_users，SRS 9.1 User）。
    手机号 SM4/AES-256 加密存储 + HMAC 哈希查重；全链路脱敏展示（SRS 9.2）。"""

    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    phone_enc: Mapped[str] = mapped_column(Text, default="")
    phone_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    avatar_key: Mapped[str] = mapped_column(String(255), default="")
    # 资料补充：邮箱与个人描述（移动端 UserProfile M07；后台业主档案独立列展示）。
    email: Mapped[str] = mapped_column(String(128), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    gender: Mapped[str] = mapped_column(String(8), default="")
    # ACTIVE / FROZEN / CANCELLED（注销后匿名化，BR-10）
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    # NOT_LOGIN 以外的端侧状态由 certifications + residents 推导
    realname_status: Mapped[str] = mapped_column(String(16), default="UNVERIFIED", index=True)
    # 注册引导：NEW（刚建号）/ PROFILE_COMPLETED（资料已完善或跳过）/ COMPLETED（引导完成）。
    # 存量用户迁移时回填 COMPLETED，避免升级后被强制拉去注册。
    # 注意：PROFILE_COMPLETED 长 17，列宽必须 ≥17（PostgreSQL 会严格校验 varchar 长度）。
    onboarding_status: Mapped[str] = mapped_column(String(32), default="COMPLETED", index=True)
    # 注册时选择的入住小区（必填）：用于内容推荐/住户认证预选，并同步建立
    # certification_status=UNVERIFIED 的 Resident 档案；认证通过后升级为已认证档案。
    intent_community_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("communities.id"), index=True
    )
    # sms / wechat / one_click
    registration_channel: Mapped[str] = mapped_column(String(16), default="sms")
    # 协议同意留痕（P0 存用户主表；P1 可迁移到 user_agreements 明细表）。
    agreement_version: Mapped[str] = mapped_column(String(32), default="")
    privacy_version: Mapped[str] = mapped_column(String(32), default="")
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credit_score: Mapped[int] = mapped_column(default=100)
    credit_level: Mapped[str] = mapped_column(String(16), default="良好")
    # 端侧设置（通知开关/隐私等，M07-06）：{"pushEnabled": true, ...}
    settings_json: Mapped[dict] = mapped_column(JsonDict, default=dict)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# 兼容性别名：业务层仍有大量 ``User`` 引用，先保留别名避免一次性大范围改名；
# 新代码请优先使用 ``PlatformUser``。后续可单独提交清理该别名。
User = PlatformUser


class Certification(Entity):
    """实名/业主证明审核单（SRS W02、M01-03）。每次提交生成一张审核单进入后台队列；
    驳回必须给出原因（M01-04），累计驳回 3 次转人工专线（M01-05）。"""

    __tablename__ = "certifications"
    # 同一用户同一认证类型只能有一条待审/待补充单，避免并发提交产生重复待办。
    __table_args__ = (
        Index(
            "uq_certifications_pending_user_type",
            "user_id", "type",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'SUPPLEMENT')"),
            sqlite_where=text("status IN ('PENDING', 'SUPPLEMENT')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    resident_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("residents.id"), index=True)
    community_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    # REALNAME / OWNER_PROOF（业主/租户/家属）
    type: Mapped[str] = mapped_column(String(24), index=True)
    identity: Mapped[str] = mapped_column(String(16), default="owner")
    # 材料对象键列表（私有桶，签名 URL 10 分钟，禁止下载原图）
    materials: Mapped[dict] = mapped_column(JsonDict, default=list)
    # 第三方自动核验结论（OCR/人脸比对），人工仅处理异常（W02-01）
    auto_result: Mapped[dict] = mapped_column(JsonDict, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    review_note: Mapped[str] = mapped_column(String(500), default="")
    reject_reason: Mapped[str] = mapped_column(String(500), default="")
    reject_count: Mapped[int] = mapped_column(default=0)
    trace_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Resident(Entity):
    """社区人员档案。一个用户在一个社区仅一条有效档案（后台详设 5.6.1）；
    业主证明通过后账号与小区强绑定（BR-02、W02-02）。"""

    __tablename__ = "residents"
    # 同一社区同一平台账号仅一条有效档案；NULL 用户可有多条（物业代建档）。
    # 组合索引覆盖后台住户列表的常用过滤条件。
    __table_args__ = (
        Index(
            "uq_residents_community_user",
            "community_id", "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
        Index("ix_residents_community_identity", "community_id", "identity_type"),
        Index("ix_residents_community_cert", "community_id", "certification_status"),
        Index("ix_residents_community_status", "community_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    community_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("communities.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    gender: Mapped[str] = mapped_column(String(8), default="")
    phone_enc: Mapped[str] = mapped_column(Text, default="")
    phone_hash: Mapped[str] = mapped_column(String(128), default="", index=True)
    # 业主 / 租户 / 家属 / 商务人员
    identity_type: Mapped[str] = mapped_column(String(16), default="业主", index=True)
    building: Mapped[str] = mapped_column(String(128), default="")
    relationship: Mapped[str] = mapped_column(String(64), default="")
    certification_status: Mapped[str] = mapped_column(String(16), default="UNVERIFIED", index=True)
    certification_no: Mapped[str] = mapped_column(String(32), default="")
    level: Mapped[str] = mapped_column(String(24), default="普通用户")
    # ACTIVE / FROZEN / LEFT
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserPenalty(Entity):
    """用户处置记录（W07-02）：警告/禁言/限制发布/限制交易/封禁。
    处置必须填写原因并留痕。"""

    __tablename__ = "user_penalties"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    type: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)


class CreditLog(Base):
    """信用流水（SRS 9.1 CreditLog、M07-08）。分数可由流水重算，禁止直接改分。"""

    __tablename__ = "credit_logs"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("platform_users.id"), index=True)
    delta: Mapped[int] = mapped_column()
    # TRADE_FULFILL / ON_TIME_INSPECT / REVIEW / VIOLATION / DISPUTE_PENALTY
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    ref_type: Mapped[str] = mapped_column(String(24), default="")
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(default=0)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
