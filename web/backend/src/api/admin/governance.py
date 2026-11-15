from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.core.storage import presign_download
from src.db.models import (
    Dispute,
    DisputeEvidence,
    DisputeMessage,
    FinanceAdjustment,
    Order,
    User,
)
from src.domain import enums as E
from src.domain.state import dispute_sm, order_sm
from src.services import order_service as order_svc
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:governance"])

MediatePerm = Depends(require_permission("governance:dispute:mediate"))
ResolvePerm = Depends(require_permission("governance:dispute:resolve"))
FreezePerm = Depends(require_permission("governance:dispute:freeze"))


async def _row(db: DbSession, dispute: Dispute) -> dict:
    initiator = await db.get(User, dispute.initiator_id)
    respondent = await db.get(User, dispute.respondent_id)
    return {
        "id": str(dispute.id),
        "disputeNo": dispute.dispute_no,
        "orderId": str(dispute.order_id),
        "initiator": initiator.nickname if initiator else "",
        "respondent": respondent.nickname if respondent else "",
        "amountCents": dispute.amount_cents,
        "amount": f"¥{dispute.amount_cents / 100:,.2f}",
        "status": dispute.status,
        "statement": dispute.statement,
        "conclusion": dispute.conclusion,
        "conclusionType": dispute.conclusion_type,
        "mediatorId": str(dispute.mediator_id) if dispute.mediator_id else "",
        "createdAt": int(dispute.created_at.timestamp() * 1000) if dispute.created_at else 0,
    }


@router.get("/disputes")
async def list_disputes(
    admin: CurrentAdmin, db: DbSession,
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Dispute)
    if status:
        stmt = stmt.where(Dispute.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Dispute.dispute_no.ilike(like),
                              Dispute.statement.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(Dispute.id.desc()), page, pageSize)
    return paginated([await _row(db, row) for row in rows], page, pageSize, total)


@router.get("/disputes/{dispute_id}")
async def dispute_detail(dispute_id: int, admin: CurrentAdmin, db: DbSession):
    dispute = await db.get(Dispute, dispute_id)
    if not dispute:
        raise ApiError(ERR_NOT_FOUND, "纠纷不存在", 404)
    row = await _row(db, dispute)
    order = await db.get(Order, dispute.order_id)
    if order:
        row["order"] = {
            "orderNo": order.order_no, "status": order.status,
            "escrowStatus": order.escrow_status, "amount": order.amount_cents / 100,
        }
    messages = list((await db.execute(
        select(DisputeMessage).where(DisputeMessage.dispute_id == dispute.id)
        .order_by(DisputeMessage.id))).scalars().all())
    row["messages"] = [
        {"senderType": m.sender_type, "content": m.content,
         "time": int(m.created_at.timestamp() * 1000) if m.created_at else 0}
        for m in messages
    ]
    return ok(row)


@router.get("/disputes/{dispute_id}/evidences")
async def dispute_evidences(dispute_id: int, admin: CurrentAdmin, db: DbSession):
    """证据缩略图（私有桶签名 URL 10 分钟）；查看原图写审计。"""
    rows = list((await db.execute(
        select(DisputeEvidence).where(DisputeEvidence.dispute_id == dispute_id)
        .order_by(DisputeEvidence.id))).scalars().all())
    return ok([{
        "id": str(row.id), "objectKey": row.object_key,
        "signedUrl": presign_download(row.object_key),
        "description": row.description, "uploaderId": str(row.uploader_id),
    } for row in rows])


class MediateIn(BaseModel):
    note: str


@router.post("/disputes/{dispute_id}/mediate", dependencies=[MediatePerm])
async def mediate_dispute(dispute_id: int, payload: MediateIn,
                          request: Request, admin: CurrentAdmin, db: DbSession):
    """调解记录（内部沟通时间线，不直接发给用户）。"""
    dispute = await db.get(Dispute, dispute_id)
    if not dispute:
        raise ApiError(ERR_NOT_FOUND, "纠纷不存在", 404)
    if len(payload.note.strip()) < 2:
        raise ApiError(ERR_PARAM, "调解记录不能为空", 400)
    if dispute.status == E.DisputeStatus.OPEN:
        dispute.status = dispute_sm.fire(dispute.status, E.DisputeStatus.MEDIATING)
    dispute.mediator_id = admin.id
    db.add(DisputeMessage(dispute_id=dispute.id, sender_type="ADMIN",
                          sender_id=admin.id, content=payload.note.strip()))
    await write_audit(db, request, actor=admin, action="dispute.mediate",
                      resource_type="dispute", resource_id=dispute.id,
                      before=None, after={"note": payload.note.strip()[:120]})
    await db.commit()
    return ok(await _row(db, dispute), "调解记录已保存")


class FreezeIn(BaseModel):
    reason: str


@router.post("/disputes/{dispute_id}/freeze", dependencies=[FreezePerm])
async def freeze_dispute_funds(dispute_id: int, payload: FreezeIn,
                               request: Request, admin: CurrentAdmin, db: DbSession):
    """冻结托管资金（M06-11/W05-02）：真实冻结订单托管状态（不是文本记录）。"""
    dispute = await db.get(Dispute, dispute_id)
    if not dispute:
        raise ApiError(ERR_NOT_FOUND, "纠纷不存在", 404)
    if len(payload.reason.strip()) < 2:
        raise ApiError(ERR_PARAM, "冻结原因必填", 400)
    order = await db.get(Order, dispute.order_id)
    if order and order.trade_type == E.TradeType.MONETARY:
        order.escrow_status = E.EscrowStatus.FROZEN
        await order_svc.add_event(db, order, "DISPUTED", note=f"资金冻结：{payload.reason}")
    if dispute.status == E.DisputeStatus.OPEN:
        dispute.status = dispute_sm.fire(dispute.status, E.DisputeStatus.MEDIATING)
    dispute.mediator_id = admin.id
    db.add(DisputeMessage(dispute_id=dispute.id, sender_type="ADMIN",
                          sender_id=admin.id, content=f"[资金冻结] {payload.reason}"))
    await write_audit(db, request, actor=admin, action="dispute.freeze",
                      resource_type="dispute", resource_id=dispute.id,
                      before=None, after={"reason": payload.reason})
    await db.commit()
    return ok(await _row(db, dispute), "托管资金已冻结")


class ResolveIn(BaseModel):
    conclusionType: str  # CONTINUE / CANCEL_REFUND / FORCE_RELEASE / PARTIAL_REFUND / CREDIT / ACCOUNT_FREEZE
    conclusion: str
    amountCents: int = 0  # 部分退款金额（PARTIAL_REFUND 时必填）


@router.post("/disputes/{dispute_id}/resolve", dependencies=[ResolvePerm])
async def resolve_dispute(dispute_id: int, payload: ResolveIn,
                          request: Request, admin: CurrentAdmin, db: DbSession):
    """出具结论（W05-02）：
    - 非资金类（继续履约/信用处理/账号冻结）→ 立即结案并执行联动；
    - 资金类（取消退款/强制放款/部分退款）→ 生成 finance_adjustments 并进入
      双人复核（申请人 ≠ 复核人，复核通过才执行，W06-04）。"""
    dispute = await db.get(Dispute, dispute_id)
    if not dispute:
        raise ApiError(ERR_NOT_FOUND, "纠纷不存在", 404)
    if dispute.status in (E.DisputeStatus.RESOLVED, E.DisputeStatus.CLOSED):
        raise ApiError(ERR_BIZ_RULE, "纠纷已结案，重复争议请新建纠纷", 422)
    if payload.conclusionType not in E.ConclusionType.FUND_TYPES + (
        E.ConclusionType.CONTINUE, E.ConclusionType.CREDIT, E.ConclusionType.ACCOUNT_FREEZE):
        raise ApiError(ERR_PARAM, "结论类型不合法", 400)
    if len(payload.conclusion.strip()) < 5:
        raise ApiError(ERR_PARAM, "处理结论必填（不少于 5 个字）", 400)
    if not dispute.statement:
        raise ApiError(ERR_BIZ_RULE, "结论前必须有双方陈述与证据（详设 5.6.1）", 422)

    order = await db.get(Order, dispute.order_id)
    before = {"status": dispute.status, "orderStatus": order.status if order else ""}
    dispute.mediator_id = admin.id
    dispute.conclusion = payload.conclusion.strip()
    dispute.conclusion_type = payload.conclusionType

    if payload.conclusionType in E.ConclusionType.FUND_TYPES:
        amount = (payload.amountCents if payload.conclusionType == E.ConclusionType.PARTIAL_REFUND
                  else (order.amount_cents if order else 0))
        if payload.conclusionType == E.ConclusionType.PARTIAL_REFUND and amount <= 0:
            raise ApiError(ERR_PARAM, "部分退款必须填写退款金额", 400)
        adj_type = {
            E.ConclusionType.CANCEL_REFUND: "FORCE_REFUND",
            E.ConclusionType.PARTIAL_REFUND: "PARTIAL_REFUND",
            E.ConclusionType.FORCE_RELEASE: "FORCE_RELEASE",
        }[payload.conclusionType]
        adjustment = FinanceAdjustment(
            adjustment_no=f"FA{uuid.uuid4().hex[:14]}",
            order_id=order.id,
            dispute_id=dispute.id,
            type=adj_type,
            amount_cents=amount,
            reason=payload.conclusion.strip(),
            applicant_id=admin.id,
            status=E.AdjustmentStatus.PENDING_REVIEW,
        )
        db.add(adjustment)
        dispute.status = dispute_sm.fire(dispute.status, E.DisputeStatus.PENDING_REVIEW)
        await write_audit(db, request, actor=admin, action="dispute.resolve.apply",
                          resource_type="dispute", resource_id=dispute.id,
                          before=before,
                          after={"conclusionType": payload.conclusionType,
                                 "adjustmentNo": adjustment.adjustment_no})
        await db.commit()
        return ok({"dispute": await _row(db, dispute),
                   "adjustment": {"id": str(adjustment.id),
                                  "adjustmentNo": adjustment.adjustment_no,
                                  "status": adjustment.status}},
                  "结论已提交，资金处置进入双人复核")

    # 非资金类结论：立即结案
    dispute.status = dispute_sm.fire(dispute.status, E.DisputeStatus.RESOLVED)
    if order:
        if payload.conclusionType == E.ConclusionType.CONTINUE:
            order.status = order_sm.fire(order.status, E.OrderStatus.APPOINTMENT)
            if order.trade_type == E.TradeType.MONETARY:
                order.escrow_status = E.EscrowStatus.ESCROWED
            await order_svc.add_event(db, order, "APPOINTED", note="纠纷调解：继续履约")
        elif payload.conclusionType == E.ConclusionType.ACCOUNT_FREEZE:
            respondent = await db.get(User, dispute.respondent_id)
            if respondent:
                respondent.status = "FROZEN"
        # CREDIT：信用处理记录于结论，信用流水由评价/违规模块产生
    for uid in (dispute.initiator_id, dispute.respondent_id):
        await notify_user(db, uid, category="TRADE", title="纠纷已结案",
                          description=payload.conclusion.strip()[:120],
                          icon="gavel", tag="纠纷", route={"type": "order", "id": str(order.id) if order else ""})
    await write_audit(db, request, actor=admin, action="dispute.resolve",
                      resource_type="dispute", resource_id=dispute.id,
                      before=before, after={"status": dispute.status,
                                            "conclusionType": payload.conclusionType})
    await db.commit()
    return ok(await _row(db, dispute), "纠纷已结案")
