"""资金服务层（W06/BR-11/NF-13）：钱包、复式账本、Mock 支付渠道、提现打款。

红线：
- 金额一律整数分；余额只能通过 LedgerEntry 记账联动，禁止直接 UPDATE 余额；
- 托管资金（PLATFORM_ESCROW 户）与平台收入（PLATFORM_REVENUE 户）分户隔离（SRS 11.1）；
- 生产接入持牌支付机构：prepay/callback/payout 走渠道适配器，回调验签（本文件 Mock 已实现验签形态）。
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.responses import ERR_BIZ_RULE, ERR_CONFLICT, ERR_NOT_FOUND, ERR_PARAM, ApiError
from src.db.models import (
    LedgerEntry,
    Order,
    PaymentTransaction,
    WalletAccount,
    Withdrawal,
)
from src.db.models.common import utcnow

CHANNEL_WECHAT = "WECHAT"
PLATFORM_ESCROW = "PLATFORM_ESCROW"
PLATFORM_REVENUE = "PLATFORM_REVENUE"


def user_account_key(user_id: int) -> str:
    return f"USER:{user_id}"


def channel_account_key(channel: str) -> str:
    return f"CHANNEL:{channel}"


def channel_sign(order_no: str, amount_cents: int) -> str:
    """渠道回调验签（NF-13）。Mock 与生产同形态：HMAC-SHA256(密钥, 报文)。"""
    message = f"{order_no}:{amount_cents}"
    return hmac.new(settings.secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()


async def get_or_create_wallet(db: AsyncSession, user_id: int) -> WalletAccount:
    wallet = await db.scalar(select(WalletAccount).where(WalletAccount.user_id == user_id))
    if wallet:
        return wallet
    wallet = WalletAccount(user_id=user_id, balance_cents=0, escrow_cents=0, withdrawable_cents=0)
    db.add(wallet)
    await db.flush()
    return wallet


async def _account_balance(db: AsyncSession, account: str) -> int:
    credits = int((await db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
        .where(LedgerEntry.account == account, LedgerEntry.direction == "CREDIT"))) or 0)
    debits = int((await db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
        .where(LedgerEntry.account == account, LedgerEntry.direction == "DEBIT"))) or 0)
    return credits - debits


async def post_entry(
    db: AsyncSession,
    *,
    account: str,
    entry_type: str,
    direction: str,
    amount_cents: int,
    order_id: int | None = None,
    txn_id: int | None = None,
    note: str = "",
    idempotency_key: str = "",
) -> LedgerEntry:
    """单边记账（由 post_pair 双边调用）。balance_after 由账本推导，不信任传入值。"""
    balance = await _account_balance(db, account)
    balance_after = balance + amount_cents if direction == "CREDIT" else balance - amount_cents
    entry = LedgerEntry(
        entry_no=f"LE{uuid.uuid4().hex[:16]}",
        account=account,
        order_id=order_id,
        txn_id=txn_id,
        type=entry_type,
        direction=direction,
        amount_cents=amount_cents,
        balance_after=balance_after,
        note=note,
        idempotency_key=idempotency_key or f"{account}:{entry_type}:{uuid.uuid4().hex[:8]}",
    )
    db.add(entry)
    await db.flush()
    return entry


async def post_pair(
    db: AsyncSession,
    *,
    entry_type: str,
    amount_cents: int,
    debit_account: str,
    credit_account: str,
    order_id: int | None = None,
    txn_id: int | None = None,
    note: str = "",
    idempotency_key: str = "",
) -> None:
    """复式记账：借（DEBIT）出、贷（CREDIT）入，成对写入。"""
    key = idempotency_key or f"{entry_type}:{order_id or 0}:{uuid.uuid4().hex[:8]}"
    await post_entry(db, account=debit_account, entry_type=entry_type, direction="DEBIT",
                     amount_cents=amount_cents, order_id=order_id, txn_id=txn_id,
                     note=note, idempotency_key=f"{key}:d")
    await post_entry(db, account=credit_account, entry_type=entry_type, direction="CREDIT",
                     amount_cents=amount_cents, order_id=order_id, txn_id=txn_id,
                     note=note, idempotency_key=f"{key}:c")


# ---------------------------------------------------------------- 支付渠道（Mock）

async def create_payment_intent(db: AsyncSession, order: Order, channel: str = CHANNEL_WECHAT):
    """统一下单（幂等）：同一订单重复拉起返回已有支付意图（防重复支付，NF-13）。"""
    existing = await db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.order_id == order.id,
            PaymentTransaction.type == "ESCROW",
        ).order_by(PaymentTransaction.id.desc()).limit(1))
    if existing and existing.status == "SUCCESS":
        raise ApiError(ERR_CONFLICT, "订单已支付，请勿重复支付", 409)
    if existing and existing.status == "PROCESSING":
        txn = existing
    else:
        txn = PaymentTransaction(
            txn_no=f"TX{uuid.uuid4().hex[:20]}",
            order_id=order.id,
            user_id=order.buyer_id,
            type="ESCROW",
            amount_cents=order.amount_cents,
            channel=channel,
            status="PROCESSING",
            idempotency_key=f"prepay:{order.order_no}",
        )
        db.add(txn)
        await db.flush()
    return txn


def build_pay_params(txn: PaymentTransaction) -> dict:
    """拉起支付参数（端侧仅持有拉起参数与订单号，移动端详设 9.2.1）。"""
    return {
        "channel": txn.channel,
        "mockPayUrl": f"https://pay.mock.neighinn.local/pay/{txn.txn_no}",
        "sign": channel_sign(txn.txn_no, txn.amount_cents),
    }


async def settle_payment_success(db: AsyncSession, txn_no: str, sign: str) -> PaymentTransaction:
    """支付成功确认（回调验签 → 幂等 → 托管记账 → 事件）。
    重复回调幂等返回（渠道会重试，防重复入账）。"""
    txn = await db.scalar(select(PaymentTransaction).where(PaymentTransaction.txn_no == txn_no))
    if not txn:
        raise ApiError(ERR_NOT_FOUND, "支付单不存在", 404)
    if sign != channel_sign(txn.txn_no, txn.amount_cents):
        raise ApiError(ERR_PARAM, "回调验签失败", 400)
    if txn.status == "SUCCESS":
        return txn  # 幂等：重复回调直接返回成功
    if txn.status != "PROCESSING":
        raise ApiError(ERR_BIZ_RULE, f"支付单状态不可确认：{txn.status}", 422)

    txn.status = "SUCCESS"
    txn.channel_txn_no = f"CH{uuid.uuid4().hex[:18]}"

    order = await db.get(Order, txn.order_id)
    if not order:
        raise ApiError(ERR_NOT_FOUND, "关联订单不存在", 404)

    # 托管记账：渠道清算户 → 平台托管户；买家钱包登记托管金额
    await post_pair(db, entry_type="ESCROW", amount_cents=txn.amount_cents,
                    debit_account=channel_account_key(txn.channel),
                    credit_account=PLATFORM_ESCROW, order_id=order.id, txn_id=txn.id,
                    note=f"订单托管 {order.order_no}",
                    idempotency_key=f"escrow:{txn.txn_no}")
    wallet = await get_or_create_wallet(db, order.buyer_id)
    wallet.escrow_cents += txn.amount_cents
    return txn


async def release_to_seller(db: AsyncSession, order: Order, reason: str = "验货成交放款") -> None:
    """放款（BR-11）：托管户 → 卖家钱包（余额与可提现）。"""
    amount = order.amount_cents
    await post_pair(db, entry_type="RELEASE", amount_cents=amount,
                    debit_account=PLATFORM_ESCROW,
                    credit_account=user_account_key(order.seller_id),
                    order_id=order.id, note=f"{reason} {order.order_no}",
                    idempotency_key=f"release:{order.order_no}")
    buyer_wallet = await get_or_create_wallet(db, order.buyer_id)
    buyer_wallet.escrow_cents = max(0, buyer_wallet.escrow_cents - amount)
    seller_wallet = await get_or_create_wallet(db, order.seller_id)
    seller_wallet.balance_cents += amount
    seller_wallet.withdrawable_cents += amount


async def refund_to_buyer(db: AsyncSession, order: Order, reason: str = "验货不满意退款") -> None:
    """退款（BR-11/M06-06）：托管户 → 原路退回（渠道清算户）。"""
    amount = order.amount_cents
    await post_pair(db, entry_type="REFUND", amount_cents=amount,
                    debit_account=PLATFORM_ESCROW,
                    credit_account=channel_account_key(CHANNEL_WECHAT),
                    order_id=order.id, note=f"{reason} {order.order_no}",
                    idempotency_key=f"refund:{order.order_no}")
    buyer_wallet = await get_or_create_wallet(db, order.buyer_id)
    buyer_wallet.escrow_cents = max(0, buyer_wallet.escrow_cents - amount)


# ---------------------------------------------------------------- 提现（W06-03）

def withdrawal_fee(amount_cents: int) -> int:
    """手续费（M06-05：规则可配置，当前按参数费率）。"""
    rate = float(settings_dict("finance.withdrawal.fee_rate", 0.001))
    return round(amount_cents * rate)


def settings_dict(key: str, default):
    """参数读取占位：Phase 3 接 parameter_items 后替换为带缓存的参数服务。"""
    defaults = {
        "finance.withdrawal.fee_rate": 0.001,
        "finance.withdrawal.review_threshold_cents": settings.withdrawal_dual_review_threshold_cents,
    }
    return defaults.get(key, default)


def withdrawal_needs_dual_review(amount_cents: int, risk_hit: bool) -> bool:
    threshold = int(settings_dict("finance.withdrawal.review_threshold_cents",
                                  settings.withdrawal_dual_review_threshold_cents))
    return risk_hit or amount_cents >= threshold


def assess_withdrawal_risk(amount_cents: int) -> tuple[str, bool]:
    """提现风控（NF-13：限额/频次/异常拦截）。Mock 基线：大额命中转人工。"""
    if amount_cents > 1_000_000:
        return "命中：单笔金额过大，转人工复核", True
    return "通过", False


async def execute_payout(db: AsyncSession, withdrawal: Withdrawal) -> None:
    """渠道打款（Mock）：成功扣减托管冻结并记账；失败置 FAILED 允许重试（不得改金额）。"""
    account_masked = withdrawal.account_masked or ""
    wallet = await get_or_create_wallet(db, withdrawal.user_id)
    if "FAIL" in account_masked.upper():
        withdrawal.status = "FAILED"
        withdrawal.fail_reason = "渠道返回：收款账户校验失败"
        return
    await post_pair(db, entry_type="WITHDRAW", amount_cents=withdrawal.amount_cents,
                    debit_account=user_account_key(withdrawal.user_id),
                    credit_account=channel_account_key(CHANNEL_WECHAT),
                    note=f"提现打款 {withdrawal.withdrawal_no}",
                    idempotency_key=f"withdraw:{withdrawal.withdrawal_no}")
    wallet.escrow_cents = max(0, wallet.escrow_cents - withdrawal.amount_cents)
    wallet.balance_cents = max(0, wallet.balance_cents - withdrawal.amount_cents)
    withdrawal.status = "PAID"
    withdrawal.paid_at = utcnow()
