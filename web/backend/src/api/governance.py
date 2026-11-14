from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import get_or_404, paginate
from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ok, paginated
from src.db.models import Dispute, Feedback, RepairOrder

router = APIRouter(tags=["governance"])


class RepairIn(BaseModel):
    communityId: int = 1
    title: str
    reporter: str = ""
    location: str = ""
    assignee: str = "待指派"
    priority: str = "普通"
    description: str = ""


def serialize_repair(row: RepairOrder) -> dict:
    return {
        "id": str(row.id), "orderNo": row.order_no, "title": row.title, "reporter": row.reporter,
        "location": row.location, "assignee": row.assignee, "status": row.status,
        "priority": row.priority, "sla": row.sla_label, "updatedAt": row.sla_label,
        "communityId": str(row.community_id),
    }


def serialize_feedback(row: Feedback) -> dict:
    return {
        "id": str(row.id), "content": row.content, "submitter": row.submitter,
        "category": row.category, "assignee": row.assignee, "status": row.status,
        "createdAt": row.created_label, "reply": row.reply, "communityId": str(row.community_id),
    }


def serialize_dispute(row: Dispute) -> dict:
    return {
        "id": str(row.id), "disputeNo": row.dispute_no, "orderNo": row.order_no,
        "initiator": row.initiator, "respondent": row.respondent,
        "amount": f"¥{row.amount_cents / 100:g}", "amountCents": row.amount_cents,
        "status": row.status, "statement": row.statement, "conclusion": row.conclusion,
        "mediator": row.mediator, "createdAt": row.created_label,
        "communityId": str(row.community_id),
    }


@router.get("/repair-orders")
async def list_repairs(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, communityId: int | None = None,
    page: int = 1, pageSize: int = 20,
):
    stmt = select(RepairOrder)
    if communityId:
        stmt = stmt.where(RepairOrder.community_id == communityId)
    if status:
        stmt = stmt.where(RepairOrder.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(RepairOrder.order_no.ilike(like), RepairOrder.title.ilike(like),
                              RepairOrder.reporter.ilike(like), RepairOrder.location.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(RepairOrder.id), page, pageSize)
    return paginated([serialize_repair(row) for row in rows], page, pageSize, total)


@router.post("/repair-orders")
async def create_repair(payload: RepairIn, db: DbSession, admin: CurrentAdmin):
    row = RepairOrder(
        community_id=payload.communityId, order_no=f"BX{int(datetime.now().timestamp() * 1000)}",
        title=payload.title, reporter=payload.reporter, location=payload.location,
        assignee=payload.assignee, status="待派单", priority=payload.priority, sla_label="已等待 0m",
        description=payload.description,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_repair(row), "工单已创建")


@router.post("/repair-orders/{order_id}/assign")
async def assign_repair(order_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, RepairOrder, order_id)
    row.assignee = payload.get("assignee", "工程部 · 徐工")
    row.status = "处理中"
    row.sla_label = "剩余 2h"
    await db.commit()
    return ok(serialize_repair(row), "工单已派发")


@router.post("/repair-orders/{order_id}/process")
async def process_repair(order_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, RepairOrder, order_id)
    row.status = "处理中"
    await db.commit()
    return ok(serialize_repair(row), "工单处理中")


@router.post("/repair-orders/{order_id}/accept")
async def accept_repair(order_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, RepairOrder, order_id)
    row.status = "待验收"
    await db.commit()
    return ok(serialize_repair(row), "工单待验收")


@router.post("/repair-orders/{order_id}/close")
async def close_repair(order_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, RepairOrder, order_id)
    row.status = "已完成"
    row.sla_label = "已完成"
    await db.commit()
    return ok(serialize_repair(row), "工单已完成")


@router.get("/feedbacks")
async def list_feedback(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(Feedback)
    if status:
        stmt = stmt.where(Feedback.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Feedback.content.ilike(like), Feedback.submitter.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(Feedback.id), page, pageSize)
    return paginated([serialize_feedback(row) for row in rows], page, pageSize, total)


@router.post("/feedbacks/{feedback_id}/reply")
async def reply_feedback(feedback_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Feedback, feedback_id)
    row.reply = payload.get("reply", "")
    row.status = "已回复"
    await db.commit()
    return ok(serialize_feedback(row), "反馈已回复")


@router.post("/feedbacks/{feedback_id}/assign")
async def assign_feedback(feedback_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Feedback, feedback_id)
    row.assignee = payload.get("assignee", "物业客服")
    row.status = "处理中"
    await db.commit()
    return ok(serialize_feedback(row), "反馈已指派")


@router.post("/feedbacks/{feedback_id}/close")
async def close_feedback(feedback_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Feedback, feedback_id)
    row.status = "已关闭"
    await db.commit()
    return ok(serialize_feedback(row), "反馈已关闭")


@router.get("/disputes")
async def list_disputes(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(Dispute)
    if status:
        stmt = stmt.where(Dispute.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Dispute.dispute_no.ilike(like), Dispute.order_no.ilike(like),
                              Dispute.initiator.ilike(like), Dispute.respondent.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(Dispute.id), page, pageSize)
    return paginated([serialize_dispute(row) for row in rows], page, pageSize, total)


@router.get("/disputes/{dispute_id}")
async def dispute_detail(dispute_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Dispute, dispute_id)
    return ok(serialize_dispute(row))


@router.post("/disputes/{dispute_id}/mediate")
async def mediate_dispute(dispute_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Dispute, dispute_id)
    row.status = "调解中"
    row.mediator = admin.real_name
    row.statement = f"{row.statement}\n[调解记录] {payload.get('note', '')}".strip()
    await db.commit()
    return ok(serialize_dispute(row), "调解记录已保存")


@router.post("/disputes/{dispute_id}/resolve")
async def resolve_dispute(dispute_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Dispute, dispute_id)
    row.status = "已解决"
    row.conclusion = payload.get("conclusion", "")
    row.mediator = admin.real_name
    await db.commit()
    return ok(serialize_dispute(row), "纠纷已解决")


@router.post("/disputes/{dispute_id}/freeze")
async def freeze_dispute(dispute_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Dispute, dispute_id)
    row.status = "调解中"
    row.statement = f"{row.statement}\n[资金冻结申请] {payload.get('reason', '')}".strip()
    await db.commit()
    return ok(serialize_dispute(row), "资金冻结申请已记录")
