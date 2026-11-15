from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.common import BigIntPk, Entity, JsonDict, utcnow


class WalletAccount(Entity):
    """用户钱包账户（M07-05/BR-11）。余额只信任服务端账本，禁止直接 UPDATE 余额，
    只能通过 LedgerEntry 复式记账联动。"""

    __tablename__ = "wallet_accounts"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), unique=True, index=True)
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    escrow_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    withdrawable_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class LedgerEntry(Base):
    """资金账本（只追加不可改）。用户余额、平台托管、平台收入、渠道清算分户记账，
    每笔资金变动双边成对（借/贷），支持日终对账（NF-13）。"""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    entry_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    # 账户主体：USER:{user_id} / PLATFORM_ESCROW / PLATFORM_REVENUE / CHANNEL:{channel}
    account: Mapped[str] = mapped_column(String(64), index=True)
    order_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    txn_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # ESCROW / RELEASE / REFUND / WITHDRAW / FEE / ADJUSTMENT
    type: Mapped[str] = mapped_column(String(24), index=True)
    # DEBIT / CREDIT
    direction: Mapped[str] = mapped_column(String(8))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger, default=0)
    note: Mapped[str] = mapped_column(String(255), default="")
    idempotency_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentTransaction(Base):
    """资金流水（W06-02）：支付托管/放款/退款/提现/调账，全部留痕。"""

    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    txn_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    # ESCROW / RELEASE / REFUND / WITHDRAW / ADJUSTMENT
    type: Mapped[str] = mapped_column(String(24), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(String(24), default="")
    channel_txn_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    # PROCESSING / SUCCESS / FAILED / REFUNDING / REFUNDED
    status: Mapped[str] = mapped_column(String(24), default="PROCESSING", index=True)
    # PENDING / MATCHED / DIFF
    recon_status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Withdrawal(Entity):
    """提现单（W06-03）。双人复核：reviewer_id ≠ reviewer2_id（SRS W06-04/NF-13）。

    PENDING → APPROVED → PAYING → PAID
           ↘ REJECTED            ↘ FAILED → PAYING（重试）/ CLOSED
    审核通过后金额、账户不可修改；失败只能重试或关闭，不得改单。"""

    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    withdrawal_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    fee_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    account_ref_enc: Mapped[str] = mapped_column(Text, default="")
    account_masked: Mapped[str] = mapped_column(String(64), default="")
    risk_result: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    reviewer2_id: Mapped[int | None] = mapped_column(BigInteger)
    review_note: Mapped[str] = mapped_column(String(255), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fail_reason: Mapped[str] = mapped_column(String(255), default="")


class FinanceAdjustment(Entity):
    """异常资金处置（W06-04）：强制放款/退款/部分退款/划扣。
    必须关联订单与依据；申请人 ≠ 复核人；执行结果由渠道回调确认。"""

    __tablename__ = "finance_adjustments"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    adjustment_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), index=True)
    dispute_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # FORCE_RELEASE / FORCE_REFUND / PARTIAL_REFUND / DEDUCT
    type: Mapped[str] = mapped_column(String(24), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JsonDict, default=list)
    applicant_id: Mapped[int] = mapped_column(BigInteger)
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    review_note: Mapped[str] = mapped_column(String(255), default="")
    # DRAFT → PENDING_REVIEW → APPROVED → EXECUTED / REJECTED；EXECUTED → FAILED（人工跟进）
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reconciliation(Base):
    """渠道日对账（W06-05）：差异未处理禁止关闭（错误码 42204）。"""

    __tablename__ = "reconciliations"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(24), index=True)
    bill_date: Mapped[str] = mapped_column(String(16), index=True)
    channel_amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    platform_amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    diff_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    diff_count: Mapped[int] = mapped_column(Integer, default=0)
    # PENDING / MATCHED / DIFF_OPEN / RESOLVED
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    detail: Mapped[dict] = mapped_column(JsonDict, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
