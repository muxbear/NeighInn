from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.api.utils import paginate
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_BIZ_RULE, ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.db.models import LedgerEntry, Withdrawal
from src.domain import enums as E
from src.services import pay_service

router = APIRouter(tags=["c:wallet"])

TXN_TYPE_LABEL = {
    "ESCROW": ("支付托管", "out", "lock"),
    "RELEASE": ("交易放款", "in", "wallet"),
    "REFUND": ("交易退款", "in", "refund"),
    "WITHDRAW": ("余额提现", "out", "withdraw"),
    "FEE": ("平台服务费", "out", "fee"),
    "ADJUSTMENT": ("资金处置", "out", "adjust"),
}


@router.get("/wallet")
async def wallet_summary(user: CurrentUser, db: DbSession):
    """余额 / 托管中 / 可提现（M07-05）。余额只信任服务端账本（详设 9.5）。"""
    wallet = await pay_service.get_or_create_wallet(db, user.id)
    return ok({
        "balance": wallet.balance_cents / 100,
        "escrow": wallet.escrow_cents / 100,
        "withdrawable": wallet.withdrawable_cents / 100,
    })


@router.get("/wallet/transactions")
async def wallet_transactions(user: CurrentUser, db: DbSession,
                              page: int = Query(default=1),
                              pageSize: int = Query(default=20)):
    """钱包流水（放款/退款/提现）。"""
    account = pay_service.user_account_key(user.id)
    stmt = (select(LedgerEntry).where(LedgerEntry.account == account)
            .order_by(LedgerEntry.id.desc()))
    rows, total = await paginate(db, stmt, page, pageSize)
    items = []
    for entry in rows:
        label, direction, icon = TXN_TYPE_LABEL.get(entry.type, ("资金变动", "in", "wallet"))
        items.append({
            "id": str(entry.id),
            "title": label if not entry.note else entry.note[:24],
            "amount": entry.amount_cents / 100,
            "direction": direction,
            "time": entry.created_at.strftime("%m-%d %H:%M") if entry.created_at else "",
            "icon": icon,
        })
    return paginated(items, page, pageSize, total)


class WithdrawIn(BaseModel):
    amountCents: int
    accountMasked: str = "微信零钱(****4521)"


@router.post("/wallet/withdrawals")
async def request_withdrawal(payload: WithdrawIn, user: CurrentUser, db: DbSession):
    """提现申请（M06-05/W06-03）：校验余额与限额 → 风控 → 冻结资金 → 后台审核。
    默认 T+1 到账，手续费率可配置；异常风控命中转人工。"""
    amount = payload.amountCents
    if amount < 100:
        raise ApiError(ERR_PARAM, "提现金额最少 1 元", 400)
    wallet = await pay_service.get_or_create_wallet(db, user.id)
    if amount > wallet.withdrawable_cents:
        raise ApiError(ERR_BIZ_RULE, "超出可提现余额", 422)

    fee = pay_service.withdrawal_fee(amount)
    risk_result, risk_hit = pay_service.assess_withdrawal_risk(amount)

    withdrawal = Withdrawal(
        withdrawal_no=f"WD{uuid.uuid4().hex[:14]}",
        user_id=user.id,
        amount_cents=amount,
        fee_cents=fee,
        account_masked=payload.accountMasked[:64],
        risk_result=risk_result,
        status=E.WithdrawalStatus.PENDING,
    )
    db.add(withdrawal)
    # 冻结提现金额：可提现 → 托管冻结（审核拒绝时退回）
    wallet.withdrawable_cents -= amount
    wallet.escrow_cents += amount
    await db.commit()
    return ok({
        "success": True,
        "status": withdrawal.status,
        "withdrawalNo": withdrawal.withdrawal_no,
        "fee": fee / 100,
        "needDualReview": pay_service.withdrawal_needs_dual_review(amount, risk_hit),
    }, "提现申请已提交，预计 T+1 到账")


@router.get("/wallet/withdrawals/{withdrawal_id}")
async def withdrawal_detail(withdrawal_id: int, user: CurrentUser, db: DbSession):
    withdrawal = await db.get(Withdrawal, withdrawal_id)
    if not withdrawal or withdrawal.user_id != user.id:
        raise ApiError(ERR_NOT_FOUND, "提现单不存在", 404)
    return ok({
        "id": str(withdrawal.id),
        "withdrawalNo": withdrawal.withdrawal_no,
        "amount": withdrawal.amount_cents / 100,
        "fee": withdrawal.fee_cents / 100,
        "account": withdrawal.account_masked,
        "status": withdrawal.status,
        "failReason": withdrawal.fail_reason,
        "createdAt": int(withdrawal.created_at.timestamp() * 1000) if withdrawal.created_at else 0,
        "paidAt": int(withdrawal.paid_at.timestamp() * 1000) if withdrawal.paid_at else 0,
    })
