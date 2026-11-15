"""状态机单测（后台详设 5.6.6：每条合法迁移成功、每条非法迁移抛 InvalidTransition）。"""

import pytest

from src.core.responses import ApiError
from src.domain import enums as E
from src.domain.state import (
    InvalidTransition,
    adjustment_sm,
    certification_sm,
    dispute_sm,
    item_sm,
    order_sm,
    withdrawal_sm,
)


class TestItemStateMachine:
    def test_happy_path_to_sale(self):
        s = item_sm.fire(E.ItemStatus.DRAFT, E.ItemStatus.AUDITING)
        s = item_sm.fire(s, E.ItemStatus.PENDING_REVIEW)
        s = item_sm.fire(s, E.ItemStatus.ON_SALE)
        s = item_sm.fire(s, E.ItemStatus.RESERVED)
        assert item_sm.fire(s, E.ItemStatus.SOLD) == E.ItemStatus.SOLD

    def test_ai_reject_allows_edit_and_resubmit(self):
        s = item_sm.fire(E.ItemStatus.DRAFT, E.ItemStatus.AUDITING)
        s = item_sm.fire(s, E.ItemStatus.AI_REJECTED)
        s = item_sm.fire(s, E.ItemStatus.DRAFT)
        assert item_sm.fire(s, E.ItemStatus.AUDITING) == E.ItemStatus.AUDITING

    def test_cannot_skip_audit(self):
        """BR-04：草稿不得直接上架（必须 AI 质检 + 人工复核）。"""
        with pytest.raises(InvalidTransition):
            item_sm.fire(E.ItemStatus.DRAFT, E.ItemStatus.ON_SALE)

    def test_terminal_states_are_final(self):
        for terminal in (E.ItemStatus.SOLD, E.ItemStatus.GIFTED, E.ItemStatus.OFF_SHELF):
            with pytest.raises(ApiError):
                item_sm.fire(terminal, E.ItemStatus.ON_SALE)

    def test_reserved_unlocks_on_cancel(self):
        s = item_sm.fire(E.ItemStatus.ON_SALE, E.ItemStatus.RESERVED)
        assert item_sm.fire(s, E.ItemStatus.ON_SALE) == E.ItemStatus.ON_SALE


class TestOrderStateMachine:
    def test_monetary_full_flow(self):
        s = order_sm.fire(E.OrderStatus.PENDING_PAYMENT, E.OrderStatus.ESCROWED)
        s = order_sm.fire(s, E.OrderStatus.APPOINTMENT)
        s = order_sm.fire(s, E.OrderStatus.INSPECTING)
        s = order_sm.fire(s, E.OrderStatus.PENDING_RELEASE)
        assert order_sm.fire(s, E.OrderStatus.COMPLETED) == E.OrderStatus.COMPLETED

    def test_gift_flow(self):
        s = order_sm.fire(E.OrderStatus.APPLIED, E.OrderStatus.PENDING_CONFIRM)
        s = order_sm.fire(s, E.OrderStatus.CONFIRMED)
        s = order_sm.fire(s, E.OrderStatus.APPOINTMENT)
        s = order_sm.fire(s, E.OrderStatus.INSPECTING)
        assert order_sm.fire(s, E.OrderStatus.COMPLETED) == E.OrderStatus.COMPLETED

    def test_refund_path(self):
        s = order_sm.fire(E.OrderStatus.INSPECTING, E.OrderStatus.REFUNDING)
        assert order_sm.fire(s, E.OrderStatus.REFUNDED) == E.OrderStatus.REFUNDED

    def test_dispute_resolution_paths(self):
        s = order_sm.fire(E.OrderStatus.INSPECTING, E.OrderStatus.DISPUTING)
        assert order_sm.can_fire(s, E.OrderStatus.PENDING_RELEASE)  # 强制放款
        assert order_sm.can_fire(s, E.OrderStatus.REFUNDING)        # 退款
        assert order_sm.can_fire(s, E.OrderStatus.APPOINTMENT)      # 继续履约
        assert order_sm.can_fire(s, E.OrderStatus.CANCELLED)

    def test_completed_is_terminal(self):
        with pytest.raises(InvalidTransition):
            order_sm.fire(E.OrderStatus.COMPLETED, E.OrderStatus.REFUNDING)


class TestWithdrawalStateMachine:
    def test_happy_path(self):
        s = withdrawal_sm.fire(E.WithdrawalStatus.PENDING, E.WithdrawalStatus.APPROVED)
        s = withdrawal_sm.fire(s, E.WithdrawalStatus.PAYING)
        assert withdrawal_sm.fire(s, E.WithdrawalStatus.PAID) == E.WithdrawalStatus.PAID

    def test_failed_can_only_retry_or_close(self):
        s = withdrawal_sm.fire(E.WithdrawalStatus.PAYING, E.WithdrawalStatus.FAILED)
        assert withdrawal_sm.can_fire(s, E.WithdrawalStatus.PAYING)
        assert withdrawal_sm.can_fire(s, E.WithdrawalStatus.CLOSED)
        assert not withdrawal_sm.can_fire(s, E.WithdrawalStatus.APPROVED)


class TestAdjustmentStateMachine:
    def test_requires_review_before_execute(self):
        with pytest.raises(InvalidTransition):
            adjustment_sm.fire(E.AdjustmentStatus.DRAFT, E.AdjustmentStatus.EXECUTED)
        s = adjustment_sm.fire(E.AdjustmentStatus.DRAFT, E.AdjustmentStatus.PENDING_REVIEW)
        s = adjustment_sm.fire(s, E.AdjustmentStatus.APPROVED)
        assert adjustment_sm.fire(s, E.AdjustmentStatus.EXECUTED) == E.AdjustmentStatus.EXECUTED


class TestDisputeStateMachine:
    def test_resolved_cannot_reopen(self):
        s = dispute_sm.fire(E.DisputeStatus.OPEN, E.DisputeStatus.MEDIATING)
        s = dispute_sm.fire(s, E.DisputeStatus.PENDING_REVIEW)
        s = dispute_sm.fire(s, E.DisputeStatus.RESOLVED)
        with pytest.raises(InvalidTransition):
            dispute_sm.fire(s, E.DisputeStatus.MEDIATING)


class TestCertificationStateMachine:
    def test_reject_allows_resubmit(self):
        s = certification_sm.fire(E.CertificationStatus.PENDING, E.CertificationStatus.REJECTED)
        assert certification_sm.fire(s, E.CertificationStatus.PENDING) == E.CertificationStatus.PENDING

    def test_freeze_unfreeze(self):
        s = certification_sm.fire(E.CertificationStatus.VERIFIED, E.CertificationStatus.FROZEN)
        assert certification_sm.fire(s, E.CertificationStatus.VERIFIED) == E.CertificationStatus.VERIFIED
