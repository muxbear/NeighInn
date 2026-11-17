from __future__ import annotations

from src.core.responses import ERR_INVALID_TRANSITION, ApiError
from src.domain import enums as E


class InvalidTransition(ApiError):
    def __init__(self, name: str, from_state: str, to_state: str):
        super().__init__(
            ERR_INVALID_TRANSITION,
            f"{name} 不允许从 {from_state} 迁移到 {to_state}",
            409,
        )


class StateMachine:
    """通用状态机。所有状态变更必须通过 fire()，禁止直接 UPDATE status（后台详设 5.6.6）。
    守卫失败不改变状态；非法迁移抛 40904。"""

    def __init__(self, name: str, transitions: dict[str, set[str]], terminal: set[str] | None = None):
        self.name = name
        self.transitions = transitions
        self.terminal = terminal or set()

    def can_fire(self, from_state: str, to_state: str) -> bool:
        return to_state in self.transitions.get(from_state, set())

    def fire(self, from_state: str, to_state: str) -> str:
        if from_state in self.terminal:
            raise InvalidTransition(self.name, from_state, to_state)
        if not self.can_fire(from_state, to_state):
            raise InvalidTransition(self.name, from_state, to_state)
        return to_state


# ---- 物品（SRS 4.3、BR-04/07/08） ----
item_sm = StateMachine("物品", {
    E.ItemStatus.DRAFT: {E.ItemStatus.AUDITING, E.ItemStatus.OFF_SHELF},
    E.ItemStatus.AUDITING: {
        E.ItemStatus.AI_REJECTED,
        E.ItemStatus.PENDING_REVIEW,
        E.ItemStatus.ON_SALE,  # 高置信快车道（阈值可配置，W03-01）
        E.ItemStatus.OFF_SHELF,
    },
    E.ItemStatus.AI_REJECTED: {E.ItemStatus.DRAFT, E.ItemStatus.OFF_SHELF},
    E.ItemStatus.PENDING_REVIEW: {
        E.ItemStatus.ON_SALE, E.ItemStatus.REJECTED, E.ItemStatus.OFF_SHELF,
    },
    E.ItemStatus.REJECTED: {E.ItemStatus.DRAFT, E.ItemStatus.OFF_SHELF},
    E.ItemStatus.ON_SALE: {
        E.ItemStatus.RESERVED, E.ItemStatus.OFF_SHELF, E.ItemStatus.EXPIRED,
    },
    E.ItemStatus.RESERVED: {
        E.ItemStatus.ON_SALE,  # 取消预约解锁
        E.ItemStatus.SOLD,
        E.ItemStatus.GIFTED,
        E.ItemStatus.OFF_SHELF,
    },
    E.ItemStatus.EXPIRED: {E.ItemStatus.ON_SALE, E.ItemStatus.OFF_SHELF},  # 续期回上架
    E.ItemStatus.SOLD: set(),
    E.ItemStatus.GIFTED: set(),
    E.ItemStatus.OFF_SHELF: set(),
}, terminal={E.ItemStatus.SOLD, E.ItemStatus.GIFTED, E.ItemStatus.OFF_SHELF})


# ---- 订单（SRS 4.3：货币担保支付 + 赠与/互换共用骨架） ----
order_sm = StateMachine("订单", {
    E.OrderStatus.PENDING_PAYMENT: {
        E.OrderStatus.ESCROWED, E.OrderStatus.CANCELLED, E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.ESCROWED: {
        E.OrderStatus.APPOINTMENT, E.OrderStatus.REFUNDING,
        E.OrderStatus.CANCELLED, E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.APPLIED: {
        E.OrderStatus.PENDING_CONFIRM, E.OrderStatus.CANCELLED, E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.PENDING_CONFIRM: {
        E.OrderStatus.CONFIRMED, E.OrderStatus.CANCELLED, E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.CONFIRMED: {
        E.OrderStatus.APPOINTMENT, E.OrderStatus.CANCELLED, E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.APPOINTMENT: {
        E.OrderStatus.INSPECTING, E.OrderStatus.CANCELLED, E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.INSPECTING: {
        E.OrderStatus.PENDING_RELEASE,   # 货币：双方确认成交待放款
        E.OrderStatus.COMPLETED,         # 赠与/互换：双方确认交割
        E.OrderStatus.REFUNDING,         # 验货不满意
        E.OrderStatus.CANCELLED,
        E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.PENDING_RELEASE: {
        E.OrderStatus.COMPLETED, E.OrderStatus.DISPUTING,
    },
    E.OrderStatus.REFUNDING: {E.OrderStatus.REFUNDED, E.OrderStatus.DISPUTING},
    E.OrderStatus.DISPUTING: {
        # 纠纷结论：继续履约 / 退款关闭 / 放款完成（W05-02）
        E.OrderStatus.APPOINTMENT, E.OrderStatus.REFUNDING,
        E.OrderStatus.PENDING_RELEASE, E.OrderStatus.CANCELLED,
    },
    E.OrderStatus.COMPLETED: set(),
    E.OrderStatus.CANCELLED: set(),
    E.OrderStatus.REFUNDED: set(),
}, terminal=set(E.OrderStatus.TERMINAL))


# ---- 认证（SRS 4.3、W02-04：冻结后所有在售物品自动下架） ----
certification_sm = StateMachine("认证", {
    E.CertificationStatus.UNVERIFIED: {E.CertificationStatus.PENDING},
    E.CertificationStatus.PENDING: {
        E.CertificationStatus.VERIFIED,
        E.CertificationStatus.REJECTED,
        E.CertificationStatus.SUPPLEMENT,
    },
    E.CertificationStatus.REJECTED: {E.CertificationStatus.PENDING},
    E.CertificationStatus.SUPPLEMENT: {E.CertificationStatus.PENDING},
    E.CertificationStatus.VERIFIED: {
        E.CertificationStatus.FROZEN, E.CertificationStatus.REVOKED,
    },
    E.CertificationStatus.FROZEN: {E.CertificationStatus.VERIFIED},
    E.CertificationStatus.REVOKED: set(),
}, terminal={E.CertificationStatus.REVOKED})


# ---- 提现（后台详设 5.6.5：审核通过后金额/账户不可改，失败只能重试或关闭） ----
withdrawal_sm = StateMachine("提现", {
    E.WithdrawalStatus.PENDING: {
        E.WithdrawalStatus.APPROVED, E.WithdrawalStatus.REJECTED,
    },
    E.WithdrawalStatus.APPROVED: {E.WithdrawalStatus.PAYING},
    E.WithdrawalStatus.PAYING: {
        E.WithdrawalStatus.PAID, E.WithdrawalStatus.FAILED,
    },
    E.WithdrawalStatus.FAILED: {
        E.WithdrawalStatus.PAYING, E.WithdrawalStatus.CLOSED,
    },
    E.WithdrawalStatus.PAID: set(),
    E.WithdrawalStatus.REJECTED: set(),
    E.WithdrawalStatus.CLOSED: set(),
}, terminal={
    E.WithdrawalStatus.PAID, E.WithdrawalStatus.REJECTED, E.WithdrawalStatus.CLOSED,
})


# ---- 资金调整（强制放款/退款/划扣：申请人 ≠ 复核人，W06-04） ----
adjustment_sm = StateMachine("资金调整", {
    E.AdjustmentStatus.DRAFT: {
        E.AdjustmentStatus.PENDING_REVIEW, E.AdjustmentStatus.REJECTED,
    },
    E.AdjustmentStatus.PENDING_REVIEW: {
        E.AdjustmentStatus.APPROVED, E.AdjustmentStatus.REJECTED,
    },
    E.AdjustmentStatus.APPROVED: {E.AdjustmentStatus.EXECUTED},
    E.AdjustmentStatus.EXECUTED: {E.AdjustmentStatus.FAILED},
    E.AdjustmentStatus.FAILED: {E.AdjustmentStatus.APPROVED},
    E.AdjustmentStatus.REJECTED: set(),
}, terminal={E.AdjustmentStatus.EXECUTED, E.AdjustmentStatus.REJECTED})


# ---- 纠纷（W05-02：已解决不可重开，重复争议新建纠纷） ----
dispute_sm = StateMachine("纠纷", {
    E.DisputeStatus.OPEN: {E.DisputeStatus.MEDIATING, E.DisputeStatus.CLOSED},
    E.DisputeStatus.MEDIATING: {
        E.DisputeStatus.PENDING_REVIEW, E.DisputeStatus.RESOLVED, E.DisputeStatus.CLOSED,
    },
    E.DisputeStatus.PENDING_REVIEW: {E.DisputeStatus.RESOLVED, E.DisputeStatus.CLOSED},
    E.DisputeStatus.RESOLVED: set(),
    E.DisputeStatus.CLOSED: set(),
}, terminal={E.DisputeStatus.RESOLVED, E.DisputeStatus.CLOSED})


# ---- 内容（喇叭/动态/生活共用骨架，后台详设 5.6.3） ----
content_sm = StateMachine("内容", {
    E.ContentStatus.DRAFT: {E.ContentStatus.PENDING_REVIEW, E.ContentStatus.SCHEDULED},
    E.ContentStatus.PENDING_REVIEW: {
        E.ContentStatus.PUBLISHED, E.ContentStatus.REJECTED, E.ContentStatus.SCHEDULED,
    },
    E.ContentStatus.SCHEDULED: {E.ContentStatus.PUBLISHED, E.ContentStatus.OFFLINE},
    E.ContentStatus.PUBLISHED: {E.ContentStatus.OFFLINE},
    E.ContentStatus.REJECTED: {E.ContentStatus.DRAFT},
    E.ContentStatus.OFFLINE: {E.ContentStatus.PENDING_REVIEW},
}, terminal=set())


# ---- 邻里互助 ----
help_sm = StateMachine("互助", {
    E.HelpStatus.PENDING_REVIEW: {E.HelpStatus.OPEN, E.HelpStatus.REJECTED},
    E.HelpStatus.REJECTED: set(),
    E.HelpStatus.OPEN: {E.HelpStatus.MATCHING, E.HelpStatus.CLOSED},
    E.HelpStatus.MATCHING: {E.HelpStatus.IN_PROGRESS, E.HelpStatus.OPEN, E.HelpStatus.CLOSED},
    E.HelpStatus.IN_PROGRESS: {E.HelpStatus.COMPLETED, E.HelpStatus.CLOSED},
    E.HelpStatus.COMPLETED: set(),
    E.HelpStatus.CLOSED: set(),
}, terminal={E.HelpStatus.COMPLETED, E.HelpStatus.CLOSED, E.HelpStatus.REJECTED})
