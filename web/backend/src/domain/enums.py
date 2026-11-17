from __future__ import annotations

from src.core.config import settings

# 业务规则常量（对应 mobile/models 与 SRS 4.3 状态机）。
# 所有状态迁移必须经 src/domain/state.py 的 StateMachine，禁止直接 UPDATE status。


class TradeType:
    MONETARY = "MONETARY"
    FREE_GIFT = "FREE_GIFT"
    BARTER = "BARTER"

    ALL = (MONETARY, FREE_GIFT, BARTER)


class ItemStatus:
    DRAFT = "DRAFT"
    AUDITING = "AUDITING"  # AI 质检中（BR-04：未通过不得进入人工复核与上架）
    AI_REJECTED = "AI_REJECTED"  # AI 驳回（可改后重提）
    PENDING_REVIEW = "PENDING_REVIEW"  # 待人工复核
    REJECTED = "REJECTED"  # 复核驳回（可改）
    ON_SALE = "ON_SALE"
    RESERVED = "RESERVED"  # 已预约（BR-08：一物同时仅一个有效订单）
    SOLD = "SOLD"
    GIFTED = "GIFTED"
    OFF_SHELF = "OFF_SHELF"
    EXPIRED = "EXPIRED"  # 30 天到期（BR-07，天数可配置）

    TERMINAL = (SOLD, GIFTED, OFF_SHELF)


class AiDecision:
    PASS = "PASS"
    FAIL = "FAIL"
    NEED_HUMAN_REVIEW = "NEED_HUMAN_REVIEW"


class OrderStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"  # 已创建待付款（30min 未付自动取消，M06-03）
    ESCROWED = "ESCROWED"  # 已托管待验货（BR-11）
    APPLIED = "APPLIED"  # 赠与/互换已申请
    PENDING_CONFIRM = "PENDING_CONFIRM"  # 待对方确认（48h 未响应自动取消，M06-02）
    CONFIRMED = "CONFIRMED"
    APPOINTMENT = "APPOINTMENT"  # 已预约
    INSPECTING = "INSPECTING"  # 验货中
    PENDING_RELEASE = "PENDING_RELEASE"  # 已成交待放款（72h 未操作自动放款，BR-11）
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"
    DISPUTING = "DISPUTING"

    TERMINAL = (COMPLETED, CANCELLED, REFUNDED)


class EscrowStatus:
    UNPAID = "UNPAID"
    ESCROWED = "ESCROWED"
    PENDING_RELEASE = "PENDING_RELEASE"
    RELEASED = "RELEASED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"
    FROZEN = "FROZEN"  # 纠纷冻结（M06-11/W05-02）


class CertificationStatus:
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"  # 可重提，累计 3 次转人工（M01-05）
    SUPPLEMENT = "SUPPLEMENT"  # 要求补充材料
    FROZEN = "FROZEN"  # 冻结后所有在售物品自动下架（W02-04）
    REVOKED = "REVOKED"


class WithdrawalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAYING = "PAYING"
    PAID = "PAID"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class AdjustmentStatus:
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class DisputeStatus:
    OPEN = "OPEN"
    MEDIATING = "MEDIATING"
    PENDING_REVIEW = "PENDING_REVIEW"
    RESOLVED = "RESOLVED"  # 已解决不可重开
    CLOSED = "CLOSED"


class ConclusionType:
    CONTINUE = "CONTINUE"
    CANCEL_REFUND = "CANCEL_REFUND"
    FORCE_RELEASE = "FORCE_RELEASE"
    PARTIAL_REFUND = "PARTIAL_REFUND"
    CREDIT = "CREDIT"
    ACCOUNT_FREEZE = "ACCOUNT_FREEZE"

    # 资金类结论必须走 finance_adjustments 双人复核（W06-04/NF-13）
    FUND_TYPES = (FORCE_RELEASE, PARTIAL_REFUND, CANCEL_REFUND)


class ContentStatus:
    """喇叭/动态/生活共用骨架（后台详设 5.6.3）。"""

    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    OFFLINE = "OFFLINE"


class HelpStatus:
    OPEN = "OPEN"  # 待响应
    MATCHING = "MATCHING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    # 邻里服务需平台审核；求助默认直接发布。
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"


class ReportStatus:
    OPEN = "OPEN"
    PROCESSING = "PROCESSING"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class FriendRequestStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DataScope:
    ALL = "ALL"
    COMMUNITY_SET = "COMMUNITY_SET"
    OWN_COMMUNITY = "OWN_COMMUNITY"
    SELF = "SELF"


class PenaltyType:
    WARNING = "WARNING"
    MUTE = "MUTE"  # 禁言（留言/私信/IM）
    PUBLISH_LIMIT = "PUBLISH_LIMIT"
    TRADE_LIMIT = "TRADE_LIMIT"
    BAN = "BAN"


# ---- 业务规则默认值（均可由参数配置覆盖，W04-05；参数变更留痕生效） ----
RULE_DEFAULTS = {
    "item.photos.min": settings.min_item_images,
    "item.photos.max": settings.max_item_images,
    "item.expire.days": settings.item_expire_days,
    "order.pay.timeout_minutes": settings.pay_timeout_minutes,
    "order.auto_release.hours": settings.auto_release_hours,
    "order.confirm.timeout_hours": settings.confirm_timeout_hours,
    "community.nearby.radius_km": settings.nearby_radius_km,
    "community.nearby.max_count": settings.nearby_max_count,
    "finance.withdrawal.review_threshold_cents": settings.withdrawal_dual_review_threshold_cents,
    "ai.review.fast_track_confidence": settings.ai_fast_track_confidence,
    "friend.max_count": settings.friend_max_count,
}
