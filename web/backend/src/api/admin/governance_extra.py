"""治理域其余模块：报事报修（占位）、投诉建议、举报工作台。
纠纷调解见 governance.py。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, not_implemented, ok, paginated
from src.db.models import Community, Feedback, Item, ItemComment, LifePost, Report, User
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import item_sm
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:governance:extra"])

HandlePerm = Depends(require_permission("governance:report:handle"))


# ---------------------------------------------------------------- 投诉建议

async def _feedback_row(db: DbSession, row: Feedback) -> dict:
    community = await db.get(Community, row.community_id) if row.community_id else None
    submitter = await db.get(User, row.submitter_id) if row.submitter_id else None
    return {
        "id": str(row.id), "content": row.content, "category": row.category,
        "submitter": submitter.nickname if submitter else "匿名用户",
        "status": row.status, "reply": row.reply,
        "satisfaction": row.satisfaction,
        "communityId": str(row.community_id) if row.community_id else "",
        "communityName": community.name if community else "",
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
        "repliedAt": int(row.replied_at.timestamp() * 1000) if row.replied_at else 0,
    }


@router.get("/feedbacks")
async def list_feedbacks(admin: CurrentAdmin, db: DbSession,
                         status: str | None = Query(default=None),
                         keyword: str | None = Query(default=None),
                         page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(Feedback)
    if status:
        stmt = stmt.where(Feedback.status == status)
    if keyword:
        stmt = stmt.where(or_(Feedback.content.ilike(f"%{keyword}%"),
                              Feedback.category.ilike(f"%{keyword}%")))
    rows, total = await paginate(db, stmt.order_by(Feedback.id.desc()), page, pageSize)
    return paginated([await _feedback_row(db, row) for row in rows], page, pageSize, total)


class ReplyIn(BaseModel):
    reply: str


@router.post("/feedbacks/{feedback_id}/reply",
             dependencies=[Depends(require_permission("governance:feedback:reply"))])
async def reply_feedback(feedback_id: int, payload: ReplyIn, request: Request,
                         admin: CurrentAdmin, db: DbSession):
    """回复需过内容安全审核（A-09）；回复后通知提交人。"""
    row = await db.get(Feedback, feedback_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "反馈不存在", 404)
    reply = payload.reply.strip()
    if len(reply) < 2:
        raise ApiError(ERR_PARAM, "回复内容不能为空", 400)
    from src.services import ai_audit_service as ai

    hit = next((kw for kw in ai.BANNED_KEYWORDS if kw in reply), None)
    if hit:
        raise ApiError(ERR_PARAM, f"回复包含违禁内容（{hit}），已被拦截", 400)
    before = {"status": row.status}
    row.reply = reply
    row.status = "REPLIED"
    row.replied_at = utcnow()
    if row.submitter_id:
        await notify_user(db, row.submitter_id, category="COMMUNITY",
                          title="你的反馈有了新回复", description=reply[:120],
                          icon="message", tag="反馈")
    await write_audit(db, request, actor=admin, action="feedback.reply",
                      resource_type="feedback", resource_id=row.id,
                      before=before, after={"status": "REPLIED"})
    await db.commit()
    return ok(await _feedback_row(db, row), "反馈已回复")


@router.post("/feedbacks/{feedback_id}/assign",
             dependencies=[Depends(require_permission("governance:feedback:assign"))])
async def assign_feedback(feedback_id: int, payload: dict, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    row = await db.get(Feedback, feedback_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "反馈不存在", 404)
    row.assignee_id = int(payload.get("assigneeId", admin.id))
    row.status = "PROCESSING"
    await write_audit(db, request, actor=admin, action="feedback.assign",
                      resource_type="feedback", resource_id=row.id,
                      before=None, after={"assigneeId": row.assignee_id})
    await db.commit()
    return ok(await _feedback_row(db, row), "反馈已指派")


@router.post("/feedbacks/{feedback_id}/close",
             dependencies=[Depends(require_permission("governance:feedback:close"))])
async def close_feedback(feedback_id: int, request: Request,
                         admin: CurrentAdmin, db: DbSession):
    row = await db.get(Feedback, feedback_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "反馈不存在", 404)
    row.status = "CLOSED"
    await write_audit(db, request, actor=admin, action="feedback.close",
                      resource_type="feedback", resource_id=row.id,
                      before=None, after={"status": "CLOSED"})
    await db.commit()
    return ok(await _feedback_row(db, row), "反馈已关闭")


# ---------------------------------------------------------------- 举报处理（W05-03/W03-04）

async def _report_row(db: DbSession, row: Report) -> dict:
    reporter = await db.get(User, row.reporter_id)
    community = await db.get(Community, row.community_id) if row.community_id else None
    target_title = ""
    if row.target_type == "ITEM":
        item = await db.get(Item, row.target_id)
        target_title = item.title if item else ""
    elif row.target_type == "USER":
        target = await db.get(User, row.target_id)
        target_title = target.nickname if target else ""
    elif row.target_type == "LIFE_POST":
        post = await db.get(LifePost, row.target_id)
        target_title = post.title if post else ""
    elif row.target_type == "COMMENT":
        comment = await db.get(ItemComment, row.target_id)
        target_title = (comment.content[:30] if comment else "")
    return {
        "id": str(row.id), "targetType": row.target_type, "targetId": str(row.target_id),
        "targetTitle": target_title, "reason": row.reason, "detail": row.detail,
        "evidence": row.evidence or [], "status": row.status, "result": row.result,
        "reporter": reporter.nickname if reporter else "",
        "handlerId": str(row.handler_id) if row.handler_id else "",
        "communityId": str(row.community_id) if row.community_id else "",
        "communityName": community.name if community else "",
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
    }


@router.get("/reports")
async def list_reports(admin: CurrentAdmin, db: DbSession,
                       status: str | None = Query(default=None),
                       targetType: str | None = Query(default=None),
                       keyword: str | None = Query(default=None),
                       page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(Report)
    if status:
        stmt = stmt.where(Report.status == status)
    if targetType:
        stmt = stmt.where(Report.target_type == targetType)
    if keyword:
        stmt = stmt.where(or_(Report.reason.ilike(f"%{keyword}%"),
                              Report.detail.ilike(f"%{keyword}%")))
    rows, total = await paginate(db, stmt.order_by(Report.id.desc()), page, pageSize)
    return paginated([await _report_row(db, row) for row in rows], page, pageSize, total)


@router.get("/reports/{report_id}")
async def report_detail(report_id: int, admin: CurrentAdmin, db: DbSession):
    report = await db.get(Report, report_id)
    if not report:
        raise ApiError(ERR_NOT_FOUND, "举报不存在", 404)
    return ok(await _report_row(db, report))


class HandleReportIn(BaseModel):
    action: str  # DISMISS / OFFLINE_CONTENT / MUTE_USER / BAN_USER / DELETE_COMMENT
    note: str = ""


@router.post("/reports/{report_id}/handle", dependencies=[HandlePerm])
async def handle_report(report_id: int, payload: HandleReportIn,
                        request: Request, admin: CurrentAdmin, db: DbSession):
    """处理举报：驳回 / 下架内容 / 隐藏评论 / 禁言 / 封禁；处置写审计并通知举报人。"""
    report = await db.get(Report, report_id)
    if not report:
        raise ApiError(ERR_NOT_FOUND, "举报不存在", 404)
    if report.status in (E.ReportStatus.RESOLVED, E.ReportStatus.DISMISSED):
        raise ApiError(ERR_PARAM, "举报已处理", 400)
    before = {"status": report.status}
    action = payload.action
    result_note = payload.note.strip()

    if action == "DISMISS":
        report.status = E.ReportStatus.DISMISSED
        result_note = result_note or "经核实举报不成立"
    elif action == "OFFLINE_CONTENT":
        if report.target_type == "ITEM":
            item = await db.get(Item, report.target_id)
            if item:
                item.status = item_sm.fire(item.status, E.ItemStatus.OFF_SHELF)
                item.reject_reason = f"举报处理：{report.reason}"
        elif report.target_type == "LIFE_POST":
            post = await db.get(LifePost, report.target_id)
            if post:
                post.status = "OFFLINE"
        report.status = E.ReportStatus.RESOLVED
        result_note = result_note or "已下架违规内容"
    elif action == "DELETE_COMMENT":
        comment = await db.get(ItemComment, report.target_id)
        if comment:
            comment.status = "DELETED"
        report.status = E.ReportStatus.RESOLVED
        result_note = result_note or "已删除违规留言"
    elif action in ("MUTE_USER", "BAN_USER"):
        from src.db.models import UserPenalty

        penalty_type = E.PenaltyType.MUTE if action == "MUTE_USER" else E.PenaltyType.BAN
        target_user_id = report.target_id if report.target_type == "USER" else None
        if not target_user_id:
            raise ApiError(ERR_PARAM, "该举报对象不是用户，无法处置账号", 400)
        db.add(UserPenalty(user_id=target_user_id, type=penalty_type,
                           reason=f"举报处理：{report.reason}。{result_note}",
                           operator_id=admin.id, status="ACTIVE"))
        if action == "BAN_USER":
            target_user = await db.get(User, target_user_id)
            if target_user:
                target_user.status = "FROZEN"
        report.status = E.ReportStatus.RESOLVED
        result_note = result_note or ("已禁言" if action == "MUTE_USER" else "已封禁账号")
    else:
        raise ApiError(ERR_PARAM, "处理方式不合法", 400)

    report.handler_id = admin.id
    report.result = result_note
    report.handled_at = utcnow()
    await notify_user(db, report.reporter_id, category="COMMUNITY",
                      title="你的举报已处理", description=result_note,
                      icon="shield", tag="举报")
    await write_audit(db, request, actor=admin, action="report.handle",
                      resource_type="report", resource_id=report.id,
                      before=before, after={"status": report.status, "action": action})
    await db.commit()
    return ok(await _report_row(db, report), "举报已处理")


# ---------------------------------------------------------------- 报事报修（占位：移动端无入口，二期决策）

@router.get("/repair-orders")
async def list_repairs(admin: CurrentAdmin, db: DbSession):
    raise not_implemented("GET /repair-orders（移动端无入口，二期决策）")


@router.post("/repair-orders")
async def create_repair(admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /repair-orders（二期）")


@router.get("/repair-orders/{order_id}")
async def repair_detail(order_id: int, admin: CurrentAdmin, db: DbSession):
    raise not_implemented("GET /repair-orders/{id}（二期）")


@router.post("/repair-orders/{order_id}/assign")
async def assign_repair(order_id: int, admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /repair-orders/{id}/assign（二期）")


@router.post("/repair-orders/{order_id}/process")
async def process_repair(order_id: int, admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /repair-orders/{id}/process（二期）")


@router.post("/repair-orders/{order_id}/accept")
async def accept_repair(order_id: int, admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /repair-orders/{id}/accept（二期）")


@router.post("/repair-orders/{order_id}/close")
async def close_repair(order_id: int, admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /repair-orders/{id}/close（二期）")
