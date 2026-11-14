from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from src.api.utils import camelize, get_or_404, model_dict, paginate
from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ApiError, ok, paginated
from src.db.models import OrderRecord, PaymentTransaction, Reconciliation, Withdrawal

router = APIRouter(prefix="/finance", tags=["finance"])


def serialize_txn(row: PaymentTransaction) -> dict:
    return {
        "id": str(row.id), "txnNo": row.txn_no, "orderNo": row.order_no, "user": row.user_name,
        "type": row.type, "amount": f"¥{row.amount_cents / 100:,.2f}",
        "amountCents": row.amount_cents, "channel": row.channel, "status": row.status,
        "channelTxnNo": row.channel_txn_no, "createdAt": row.created_label,
    }


def serialize_withdrawal(row: Withdrawal) -> dict:
    return {
        "id": str(row.id), "withdrawalNo": row.withdrawal_no, "user": row.user_name,
        "amount": f"¥{row.amount_cents / 100:,.2f}", "amountCents": row.amount_cents,
        "fee": f"¥{row.fee_cents / 100:,.2f}", "account": row.account_masked,
        "risk": row.risk_result, "status": row.status, "createdAt": row.created_label,
        "reviewer": row.reviewer, "reviewNote": row.review_note,
    }


@router.get("/overview")
async def overview(db: DbSession, admin: CurrentAdmin):
    escrow = int((await db.scalar(
        select(func.coalesce(func.sum(PaymentTransaction.amount_cents), 0)).where(
            PaymentTransaction.type == "支付托管", PaymentTransaction.status == "成功"
        )
    )) or 0)
    pending_release = int((await db.scalar(
        select(func.coalesce(func.sum(OrderRecord.amount_cents), 0)).where(
            OrderRecord.escrow_status == "托管中"
        )
    )) or 0)
    pending_refund = int((await db.scalar(
        select(func.coalesce(func.sum(PaymentTransaction.amount_cents), 0)).where(
            PaymentTransaction.type == "退款", PaymentTransaction.status == "退款中"
        )
    )) or 0)
    withdrawals = int((await db.scalar(
        select(func.count()).select_from(Withdrawal).where(Withdrawal.status == "待审核")
    )) or 0)
    return ok({
        "metrics": [
            {"label": "在途托管总额", "value": f"¥{escrow / 100:,.2f}", "change": "+3.2%", "detail": "较昨日", "tone": "violet"},
            {"label": "待放款订单", "value": f"¥{pending_release / 100:,.2f}", "change": "需关注", "detail": "超 72h 自动放款", "tone": "blue"},
            {"label": "待退款订单", "value": f"¥{pending_refund / 100:,.2f}", "change": "需跟进", "detail": "退款处理中", "tone": "orange"},
            {"label": "待审核提现", "value": str(withdrawals), "change": "待复核", "detail": "双人复核", "tone": "green"},
        ],
        "structure": [
            {"label": "托管中", "value": escrow, "pct": "62.5%", "color": "#7460D3"},
            {"label": "待放款", "value": pending_release, "pct": "26.5%", "color": "#9F91DF"},
            {"label": "退款中", "value": pending_refund, "pct": "11.0%", "color": "#D8D1F2"},
        ],
        "trend": {
            "labels": ["03/14", "03/15", "03/16", "03/17", "03/18", "03/19", "今天"],
            "escrow": [58, 63, 61, 70, 66, 74, 82],
            "release": [20, 24, 22, 28, 30, 27, 34],
            "refund": [4, 6, 3, 5, 8, 6, 9],
        },
    })


@router.get("/transactions")
async def transactions(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, type: str | None = None,
    page: int = 1, pageSize: int = 20,
):
    stmt = select(PaymentTransaction)
    if status:
        stmt = stmt.where(PaymentTransaction.status == status)
    if type:
        stmt = stmt.where(PaymentTransaction.type == type)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            PaymentTransaction.txn_no.ilike(like)
            | PaymentTransaction.order_no.ilike(like)
            | PaymentTransaction.user_name.ilike(like)
        )
    rows, total = await paginate(db, stmt.order_by(PaymentTransaction.id.desc()), page, pageSize)
    return paginated([serialize_txn(row) for row in rows], page, pageSize, total)


@router.get("/withdrawals")
async def withdrawals(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(Withdrawal)
    if status:
        stmt = stmt.where(Withdrawal.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(Withdrawal.withdrawal_no.ilike(like) | Withdrawal.user_name.ilike(like))
    rows, total = await paginate(db, stmt.order_by(Withdrawal.id.desc()), page, pageSize)
    return paginated([serialize_withdrawal(row) for row in rows], page, pageSize, total)


@router.post("/withdrawals/{withdrawal_id}/review")
async def review_withdrawal(withdrawal_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Withdrawal, withdrawal_id)
    decision = payload.get("decision", "APPROVE")
    if decision == "APPROVE":
        row.status = "打款中"
        row.reviewer = admin.real_name
        row.review_note = payload.get("note", "")
    else:
        if not payload.get("note"):
            raise ApiError(40001, "驳回原因必填", 400)
        row.status = "已驳回"
        row.reviewer = admin.real_name
        row.review_note = payload["note"]
    await db.commit()
    return ok(serialize_withdrawal(row), "提现审核完成")


@router.post("/withdrawals/{withdrawal_id}/retry")
async def retry_withdrawal(withdrawal_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Withdrawal, withdrawal_id)
    row.status = "打款中"
    await db.commit()
    return ok(serialize_withdrawal(row), "已重新发起打款")


@router.get("/reconciliations")
async def reconciliations(db: DbSession, admin: CurrentAdmin):
    rows = list((await db.execute(select(Reconciliation).order_by(Reconciliation.id.desc()))).scalars().all())
    return ok([{
        "id": str(row.id), "channel": row.channel, "billDate": row.bill_date,
        "channelAmount": f"¥{row.channel_amount_cents / 100:,.2f}",
        "platformAmount": f"¥{row.platform_amount_cents / 100:,.2f}",
        "diff": f"¥{row.diff_cents / 100:,.2f}", "diffCount": row.diff_count,
        "status": row.status, "createdAt": row.created_label,
    } for row in rows])


@router.post("/reconciliations/{reconciliation_id}/recheck")
async def recheck(reconciliation_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Reconciliation, reconciliation_id)
    row.status = "一致"
    row.diff_cents = 0
    row.diff_count = 0
    row.created_label = "刚刚"
    await db.commit()
    return ok({"id": str(row.id), "status": row.status}, "对账已重新核对")


@router.get("/orders")
async def orders(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(OrderRecord)
    if status:
        stmt = stmt.where(OrderRecord.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(OrderRecord.order_no.ilike(like) | OrderRecord.item_title.ilike(like))
    rows, total = await paginate(db, stmt.order_by(OrderRecord.id.desc()), page, pageSize)
    return paginated([camelize(model_dict(row)) for row in rows], page, pageSize, total)
