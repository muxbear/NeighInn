from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.api.utils import paginate
from src.core.audit import write_audit, write_outbox
from src.core.deps import CurrentAdmin, DbSession
from src.core.idempotency import complete_idempotency, guard_idempotency
from src.core.permissions import require_permission
from src.core.responses import (
    ERR_DUAL_REVIEW,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.core.security import decrypt_field, mask_phone
from src.db.models import (
    FinanceAdjustment,
    Item,
    LedgerEntry,
    Order,
    PaymentTransaction,
    User,
    WalletAccount,
    Withdrawal,
)
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import adjustment_sm, order_sm, withdrawal_sm
from src.services import order_service as order_svc
from src.services import pay_service
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:finance"])

WithdrawalReviewPerm = Depends(require_permission("finance:withdrawal:review"))
AdjustmentReviewPerm = Depends(require_permission("finance:adjustment:review"))


# ---------------------------------------------------------------- 看板（W06-01）

@router.get("/finance/overview")
async def finance_overview(admin: CurrentAdmin, db: DbSession):
    escrow_total = await pay_service._account_balance(db, pay_service.PLATFORM_ESCROW)
    pending_release = int((await db.scalar(
        select(func.coalesce(func.sum(Order.amount_cents), 0)).where(
            Order.status == E.OrderStatus.PENDING_RELEASE))) or 0)
    pending_release_count = int((await db.scalar(
        select(func.count()).select_from(Order).where(
            Order.status == E.OrderStatus.PENDING_RELEASE))) or 0)
    pending_refund = int((await db.scalar(
        select(func.coalesce(func.sum(Order.amount_cents), 0)).where(
            Order.status == E.OrderStatus.REFUNDING))) or 0)
    pending_withdrawals = int((await db.scalar(
        select(func.count()).select_from(Withdrawal).where(
            Withdrawal.status == E.WithdrawalStatus.PENDING))) or 0)
    revenue_total = await pay_service._account_balance(db, pay_service.PLATFORM_REVENUE)
    return ok({
        "metrics": [
            {"label": "在途托管总额", "value": f"¥{escrow_total / 100:,.2f}",
             "detail": "平台托管账户", "tone": "violet"},
            {"label": "待放款订单", "value": f"¥{pending_release / 100:,.2f}",
             "detail": f"{pending_release_count} 笔，超 72h 自动放款", "tone": "blue"},
            {"label": "退款处理中", "value": f"¥{pending_refund / 100:,.2f}",
             "detail": "验货不满意/纠纷", "tone": "orange"},
            {"label": "待审核提现", "value": str(pending_withdrawals),
             "detail": "大额双人复核", "tone": "green"},
        ],
        "structure": {
            "escrow": escrow_total,
            "pendingRelease": pending_release,
            "pendingRefund": pending_refund,
            "revenue": revenue_total,
        },
    })


# ---------------------------------------------------------------- 流水（W06-02）

async def _txn_row(db: DbSession, txn: PaymentTransaction) -> dict:
    user = await db.get(User, txn.user_id)
    phone = decrypt_field(user.phone_enc) if user else ""
    return {
        "id": str(txn.id),
        "txnNo": txn.txn_no,
        "orderId": str(txn.order_id) if txn.order_id else "",
        "user": user.nickname if user else "",
        "userPhone": mask_phone(phone),
        "type": txn.type,
        "amountCents": txn.amount_cents,
        "amount": f"¥{txn.amount_cents / 100:,.2f}",
        "channel": txn.channel,
        "channelTxnNo": txn.channel_txn_no,
        "status": txn.status,
        "reconStatus": txn.recon_status,
        "idempotencyKey": txn.idempotency_key,
        "createdAt": int(txn.created_at.timestamp() * 1000) if txn.created_at else 0,
    }


@router.get("/finance/transactions")
async def list_transactions(
    admin: CurrentAdmin, db: DbSession,
    keyword: str | None = Query(default=None),
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(PaymentTransaction)
    if type:
        stmt = stmt.where(PaymentTransaction.type == type)
    if status:
        stmt = stmt.where(PaymentTransaction.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(PaymentTransaction.txn_no.ilike(like),
                              PaymentTransaction.channel_txn_no.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(PaymentTransaction.id.desc()),
                                 page, pageSize)
    return paginated([await _txn_row(db, txn) for txn in rows], page, pageSize, total)


@router.get("/finance/transactions/{txn_id}")
async def transaction_detail(txn_id: int, admin: CurrentAdmin, db: DbSession):
    """详情：关联订单快照、幂等键、对账状态、账本分录。只读，不提供删除。"""
    txn = await db.get(PaymentTransaction, txn_id)
    if not txn:
        raise ApiError(ERR_NOT_FOUND, "流水不存在", 404)
    row = await _txn_row(db, txn)
    entries = list((await db.execute(
        select(LedgerEntry).where(LedgerEntry.txn_id == txn.id)
        .order_by(LedgerEntry.id))).scalars().all())
    row["ledgerEntries"] = [
        {"account": entry.account, "direction": entry.direction,
         "amount": entry.amount_cents / 100, "balanceAfter": entry.balance_after / 100,
         "type": entry.type, "note": entry.note}
        for entry in entries
    ]
    if txn.order_id:
        order = await db.get(Order, txn.order_id)
        if order:
            row["order"] = {
                "orderNo": order.order_no, "status": order.status,
                "escrowStatus": order.escrow_status,
                "amount": order.amount_cents / 100,
            }
    return ok(row)


# ---------------------------------------------------------------- 提现（W06-03/04：双人复核）

async def _withdrawal_row(db: DbSession, withdrawal: Withdrawal) -> dict:
    user = await db.get(User, withdrawal.user_id)
    wallet = await db.scalar(
        select(WalletAccount).where(WalletAccount.user_id == withdrawal.user_id))
    phone = decrypt_field(user.phone_enc) if user else ""
    return {
        "id": str(withdrawal.id),
        "withdrawalNo": withdrawal.withdrawal_no,
        "user": user.nickname if user else "",
        "userPhone": mask_phone(phone),
        "amountCents": withdrawal.amount_cents,
        "amount": f"¥{withdrawal.amount_cents / 100:,.2f}",
        "fee": f"¥{withdrawal.fee_cents / 100:,.2f}",
        "account": withdrawal.account_masked,
        "risk": withdrawal.risk_result,
        "status": withdrawal.status,
        "reviewerId": str(withdrawal.reviewer_id) if withdrawal.reviewer_id else "",
        "reviewer2Id": str(withdrawal.reviewer2_id) if withdrawal.reviewer2_id else "",
        "reviewNote": withdrawal.review_note,
        "failReason": withdrawal.fail_reason,
        "withdrawable": (wallet.withdrawable_cents or 0) / 100 if wallet else 0,
        "createdAt": int(withdrawal.created_at.timestamp() * 1000) if withdrawal.created_at else 0,
        "paidAt": int(withdrawal.paid_at.timestamp() * 1000) if withdrawal.paid_at else 0,
        "needDualReview": pay_service.withdrawal_needs_dual_review(
            withdrawal.amount_cents, "命中" in (withdrawal.risk_result or "")),
    }


@router.get("/finance/withdrawals")
async def list_withdrawals(
    admin: CurrentAdmin, db: DbSession,
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Withdrawal)
    if status:
        stmt = stmt.where(Withdrawal.status == status)
    if keyword:
        stmt = stmt.where(Withdrawal.withdrawal_no.ilike(f"%{keyword}%"))
    rows, total = await paginate(db, stmt.order_by(Withdrawal.id.desc()), page, pageSize)
    return paginated([await _withdrawal_row(db, row) for row in rows], page, pageSize, total)


@router.get("/finance/withdrawals/{withdrawal_id}")
async def withdrawal_detail(withdrawal_id: int, admin: CurrentAdmin, db: DbSession):
    withdrawal = await db.get(Withdrawal, withdrawal_id)
    if not withdrawal:
        raise ApiError(ERR_NOT_FOUND, "提现单不存在", 404)
    return ok(await _withdrawal_row(db, withdrawal))


class WithdrawalReviewIn(BaseModel):
    decision: str = "APPROVE"  # APPROVE / REJECT
    note: str = ""


@router.post("/finance/withdrawals/{withdrawal_id}/review",
             dependencies=[WithdrawalReviewPerm])
async def review_withdrawal(withdrawal_id: int, payload: WithdrawalReviewIn,
                            request: Request, admin: CurrentAdmin, db: DbSession):
    """初审/复审（W06-03/04）：
    - 单笔 ≥ 阈值或风控命中 → 需第二位管理员复核，复核人不得与初审相同（42203）；
    - 审核通过后金额、账户不可修改（状态机守卫）；驳回必填原因并解冻资金。"""
    withdrawal = await db.get(Withdrawal, withdrawal_id)
    if not withdrawal:
        raise ApiError(ERR_NOT_FOUND, "提现单不存在", 404)
    if payload.decision not in ("APPROVE", "REJECT"):
        raise ApiError(ERR_PARAM, "decision 必须为 APPROVE / REJECT", 400)

    idem = await guard_idempotency(db, request, {"id": withdrawal_id, **payload.model_dump()})
    if idem and idem.status == "COMPLETED":
        return ok(idem.response_json["data"])

    need_dual = pay_service.withdrawal_needs_dual_review(
        withdrawal.amount_cents, "命中" in (withdrawal.risk_result or ""))
    before = {"status": withdrawal.status, "reviewerId": withdrawal.reviewer_id,
              "reviewer2Id": withdrawal.reviewer2_id}
    wallet = await pay_service.get_or_create_wallet(db, withdrawal.user_id)

    if payload.decision == "REJECT":
        if len(payload.note.strip()) < 2:
            raise ApiError(ERR_PARAM, "驳回原因必填", 400)
        withdrawal.status = withdrawal_sm.fire(withdrawal.status, E.WithdrawalStatus.REJECTED)
        withdrawal.review_note = payload.note.strip()
        if withdrawal.reviewer_id is None:
            withdrawal.reviewer_id = admin.id
        # 解冻：托管冻结退回可提现
        wallet.escrow_cents = max(0, wallet.escrow_cents - withdrawal.amount_cents)
        wallet.withdrawable_cents += withdrawal.amount_cents
        await notify_user(db, withdrawal.user_id, category="TRADE", title="提现申请被驳回",
                          description=payload.note.strip(), icon="alert", tag="提现")
        message = "已驳回并退回资金"
    else:
        if withdrawal.reviewer_id is None:
            withdrawal.reviewer_id = admin.id
            if need_dual:
                withdrawal.review_note = f"初审通过：{payload.note or '资料齐全'}"
                await db.flush()
                data = await _withdrawal_row(db, withdrawal)
                await write_audit(db, request, actor=admin,
                                  action="finance.withdrawal.review.first",
                                  resource_type="withdrawal", resource_id=withdrawal.id,
                                  before=before,
                                  after={"status": withdrawal.status,
                                         "reviewerId": admin.id})
                await complete_idempotency(db, idem, data)
                await db.commit()
                return ok(data, "初审完成，等待第二位管理员复审（双人复核）")
        elif withdrawal.reviewer_id == admin.id:
            raise ApiError(ERR_DUAL_REVIEW, "复核人不得与初审为同一人", 422)
        else:
            withdrawal.reviewer2_id = admin.id

        withdrawal.status = withdrawal_sm.fire(withdrawal.status, E.WithdrawalStatus.APPROVED)
        withdrawal.reviewed_at = utcnow()
        withdrawal.status = withdrawal_sm.fire(withdrawal.status, E.WithdrawalStatus.PAYING)
        await pay_service.execute_payout(db, withdrawal)
        if withdrawal.status == E.WithdrawalStatus.PAID:
            await notify_user(db, withdrawal.user_id, category="TRADE",
                              title=f"提现 ¥{withdrawal.amount_cents / 100:,.2f} 已到账",
                              description=f"手续费 ¥{withdrawal.fee_cents / 100:,.2f}",
                              icon="wallet", tag="提现")
            message = "审核通过，已完成打款"
        else:
            await notify_user(db, withdrawal.user_id, category="TRADE",
                              title="提现打款失败，平台加急处理中",
                              description=withdrawal.fail_reason, icon="alert", tag="提现")
            message = "审核通过，但渠道打款失败（可重试）"

    await write_audit(db, request, actor=admin, action="finance.withdrawal.review",
                      resource_type="withdrawal", resource_id=withdrawal.id,
                      before=before,
                      after={"status": withdrawal.status, "decision": payload.decision,
                             "reviewerId": withdrawal.reviewer_id,
                             "reviewer2Id": withdrawal.reviewer2_id})
    await write_outbox(db, event_type="WithdrawalReviewed",
                       aggregate_type="withdrawal", aggregate_id=withdrawal.id,
                       payload={"status": withdrawal.status})
    data = await _withdrawal_row(db, withdrawal)
    await complete_idempotency(db, idem, data)
    await db.commit()
    return ok(data, message)


@router.post("/finance/withdrawals/{withdrawal_id}/retry",
             dependencies=[WithdrawalReviewPerm])
async def retry_withdrawal(withdrawal_id: int, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    """打款失败重试：只允许 FAILED → PAYING，不得修改金额（状态机守卫）。"""
    withdrawal = await db.get(Withdrawal, withdrawal_id)
    if not withdrawal:
        raise ApiError(ERR_NOT_FOUND, "提现单不存在", 404)
    before = {"status": withdrawal.status}
    withdrawal.status = withdrawal_sm.fire(withdrawal.status, E.WithdrawalStatus.PAYING)
    withdrawal.fail_reason = ""
    await pay_service.execute_payout(db, withdrawal)
    await write_audit(db, request, actor=admin, action="finance.withdrawal.retry",
                      resource_type="withdrawal", resource_id=withdrawal.id,
                      before=before, after={"status": withdrawal.status})
    await db.commit()
    return ok(await _withdrawal_row(db, withdrawal),
              "已重新打款" if withdrawal.status == "PAID" else "重试仍失败")


# ---------------------------------------------------------------- 资金处置（W06-04：强制放款/退款/划扣）

@router.post("/finance/adjustments",
             dependencies=[Depends(require_permission("finance:adjustment:create"))])
async def apply_adjustment(payload: dict, admin: CurrentAdmin, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /finance/adjustments（由纠纷结论自动生成，见 /disputes/{id}/resolve）")


@router.get("/finance/adjustments")
async def list_adjustments(admin: CurrentAdmin, db: DbSession,
                           page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(FinanceAdjustment).order_by(FinanceAdjustment.id.desc())
    rows, total = await paginate(db, stmt, page, pageSize)
    items = [{
        "id": str(row.id), "adjustmentNo": row.adjustment_no, "orderId": str(row.order_id),
        "disputeId": str(row.dispute_id) if row.dispute_id else "",
        "type": row.type, "amount": f"¥{row.amount_cents / 100:,.2f}",
        "reason": row.reason, "status": row.status,
        "applicantId": str(row.applicant_id), "reviewerId": str(row.reviewer_id) if row.reviewer_id else "",
    } for row in rows]
    return paginated(items, page, pageSize, total)


class AdjustmentReviewIn(BaseModel):
    decision: str = "APPROVE"  # APPROVE / REJECT
    note: str = ""


@router.post("/finance/adjustments/{adjustment_id}/review",
             dependencies=[AdjustmentReviewPerm])
async def review_adjustment(adjustment_id: int, payload: AdjustmentReviewIn,
                            request: Request, admin: CurrentAdmin, db: DbSession):
    """复核（申请人 ≠ 复核人，W06-04/42203）：通过后执行渠道操作，结果回调确认。"""
    adjustment = await db.get(FinanceAdjustment, adjustment_id)
    if not adjustment:
        raise ApiError(ERR_NOT_FOUND, "处置单不存在", 404)
    if adjustment.applicant_id == admin.id:
        raise ApiError(ERR_DUAL_REVIEW, "复核人不得与申请人相同", 422)
    before = {"status": adjustment.status}
    order = await db.get(Order, adjustment.order_id)

    if payload.decision == "REJECT":
        adjustment.status = adjustment_sm.fire(adjustment.status, E.AdjustmentStatus.REJECTED)
        adjustment.review_note = payload.note
        if order and order.status == E.OrderStatus.DISPUTING:
            order.status = order_sm.fire(order.status, E.OrderStatus.APPOINTMENT)
            order.escrow_status = E.EscrowStatus.ESCROWED
        message = "处置已驳回，订单恢复履约"
    else:
        adjustment.reviewer_id = admin.id
        adjustment.status = adjustment_sm.fire(adjustment.status, E.AdjustmentStatus.APPROVED)
        await _execute_adjustment(db, adjustment, order, admin, request)
        message = "处置已执行"

    await write_audit(db, request, actor=admin, action="finance.adjustment.review",
                      resource_type="finance_adjustment", resource_id=adjustment.id,
                      before=before, after={"status": adjustment.status})
    await db.commit()
    return ok({"id": str(adjustment.id), "status": adjustment.status}, message)


async def _execute_adjustment(db: DbSession, adjustment: FinanceAdjustment,
                              order: Order | None, admin: CurrentAdmin,
                              request: Request) -> None:
    """执行资金处置：强制放款/退款（含部分退款）→ 账本 → 订单状态 → 纠纷闭环。"""
    from src.db.models import Dispute

    adjustment.status = adjustment_sm.fire(adjustment.status, E.AdjustmentStatus.EXECUTED)
    adjustment.executed_at = utcnow()
    if not order:
        return
    if adjustment.type in ("FORCE_RELEASE", "DEDUCT"):
        order.status = order_sm.fire(order.status, E.OrderStatus.PENDING_RELEASE)
        order.escrow_status = E.EscrowStatus.PENDING_RELEASE
        await pay_service.release_to_seller(db, order, reason=f"纠纷强制放款（{adjustment.adjustment_no}）")
        order.escrow_status = E.EscrowStatus.RELEASED
        order.status = order_sm.fire(order.status, E.OrderStatus.COMPLETED)
        order.completed_at = utcnow()
        await order_svc.add_event(db, order, "RELEASED", note="纠纷调解强制放款")
        await order_svc.add_event(db, order, "COMPLETED", note="纠纷结案")
        await order_svc.unlock_item(db, order.item_id, final=E.ItemStatus.SOLD)
    else:  # FORCE_REFUND / PARTIAL_REFUND / CANCEL_REFUND
        amount = adjustment.amount_cents or order.amount_cents
        order.status = order_sm.fire(order.status, E.OrderStatus.REFUNDING)
        order.escrow_status = E.EscrowStatus.REFUNDING
        if amount == order.amount_cents:
            await pay_service.refund_to_buyer(db, order,
                                              reason=f"纠纷调解退款（{adjustment.adjustment_no}）")
        else:
            await pay_service.post_pair(
                db, entry_type="REFUND", amount_cents=amount,
                debit_account=pay_service.PLATFORM_ESCROW,
                credit_account=pay_service.channel_account_key("WECHAT"),
                order_id=order.id, note=f"纠纷部分退款（{adjustment.adjustment_no}）",
                idempotency_key=f"refund:{adjustment.adjustment_no}")
            wallet = await pay_service.get_or_create_wallet(db, order.buyer_id)
            wallet.escrow_cents = max(0, wallet.escrow_cents - amount)
        order.escrow_status = E.EscrowStatus.REFUNDED
        order.status = order_sm.fire(order.status, E.OrderStatus.REFUNDED)
        await order_svc.add_event(db, order, "REFUNDED", note="纠纷调解退款")
        await order_svc.unlock_item(db, order.item_id)

    dispute = await db.get(Dispute, adjustment.dispute_id) if adjustment.dispute_id else None
    if dispute:
        dispute.status = E.DisputeStatus.RESOLVED
        dispute.conclusion = dispute.conclusion or adjustment.reason
        await notify_user(db, dispute.initiator_id, category="TRADE",
                          title="纠纷已结案", description=dispute.conclusion[:120],
                          icon="gavel", tag="纠纷", route={"type": "order", "id": str(order.id)})
        await notify_user(db, dispute.respondent_id, category="TRADE",
                          title="纠纷已结案", description=dispute.conclusion[:120],
                          icon="gavel", tag="纠纷", route={"type": "order", "id": str(order.id)})


# ---------------------------------------------------------------- 订单查询（W05-01：只读）

@router.get("/finance/orders")
async def list_orders(
    admin: CurrentAdmin, db: DbSession,
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Order)
    if status:
        stmt = stmt.where(Order.status == status)
    if keyword:
        stmt = stmt.where(Order.order_no.ilike(f"%{keyword}%"))
    rows, total = await paginate(db, stmt.order_by(Order.id.desc()), page, pageSize)
    items = []
    for order in rows:
        item = await db.get(Item, order.item_id)
        buyer = await db.get(User, order.buyer_id)
        seller = await db.get(User, order.seller_id)
        items.append({
            "id": str(order.id), "orderNo": order.order_no,
            "itemTitle": item.title if item else "",
            "buyer": buyer.nickname if buyer else "",
            "seller": seller.nickname if seller else "",
            "tradeType": order.trade_type,
            "amountCents": order.amount_cents,
            "amount": f"¥{order.amount_cents / 100:,.2f}",
            "status": order.status, "escrowStatus": order.escrow_status,
            "createdAt": int(order.created_at.timestamp() * 1000) if order.created_at else 0,
        })
    return paginated(items, page, pageSize, total)


@router.get("/finance/orders/{order_id}")
async def order_detail(order_id: int, admin: CurrentAdmin, db: DbSession):
    """成交快照（W05-01/M06-12）：物品、双方、金额、支付与放款记录、
    预约与验货确认、评价、纠纷入口。只读，禁止任何 C 端操作。"""
    order = await db.get(Order, order_id)
    if not order:
        raise ApiError(ERR_NOT_FOUND, "订单不存在", 404)
    item = await db.get(Item, order.item_id)
    buyer = await db.get(User, order.buyer_id)
    seller = await db.get(User, order.seller_id)
    events = await order_svc.events_of(db, order.id)
    txns = list((await db.execute(
        select(PaymentTransaction).where(PaymentTransaction.order_id == order.id)
        .order_by(PaymentTransaction.id))).scalars().all())
    return ok({
        "id": str(order.id), "orderNo": order.order_no,
        "status": order.status, "escrowStatus": order.escrow_status,
        "tradeType": order.trade_type, "amount": order.amount_cents / 100,
        "item": {"id": str(order.item_id), "title": item.title if item else "",
                 "condition": item.condition if item else "",
                 "image": ""},
        "offeredItems": order.offered_items or [],
        "buyer": {"id": str(order.buyer_id), "name": buyer.nickname if buyer else ""},
        "seller": {"id": str(order.seller_id), "name": seller.nickname if seller else ""},
        "appointment": {
            "at": order.appointment_at.isoformat() if order.appointment_at else "",
            "place": order.appointment_place, "note": order.appointment_note,
            "status": order.appointment_status,
        },
        "payments": [await _txn_row(db, txn) for txn in txns],
        "events": [{"event": event.event, "actorType": event.actor_type, "note": event.note,
                    "time": int(event.created_at.timestamp() * 1000) if event.created_at else 0}
                   for event in events],
        "createdAt": int(order.created_at.timestamp() * 1000) if order.created_at else 0,
        "completedAt": int(order.completed_at.timestamp() * 1000) if order.completed_at else 0,
    })


# ---------------------------------------------------------------- 对账（W06-05，Phase 2 渠道接入）

@router.get("/finance/reconciliations")
async def list_reconciliations(admin: CurrentAdmin, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("GET /finance/reconciliations（对账自动化，Phase 2 渠道接入）")


@router.get("/finance/reconciliations/{recon_id}")
async def reconciliation_detail(recon_id: int, admin: CurrentAdmin, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("GET /finance/reconciliations/{id}（Phase 2）")


@router.post("/finance/reconciliations/{recon_id}/recheck")
async def recheck_reconciliation(recon_id: int, admin: CurrentAdmin, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /finance/reconciliations/{id}/recheck（Phase 2）")


@router.post("/finance/reconciliations/{recon_id}/resolve")
async def resolve_reconciliation(recon_id: int, admin: CurrentAdmin, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /finance/reconciliations/{id}/resolve（Phase 2）")
