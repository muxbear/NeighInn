from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from src.api.utils import paginate
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_BIZ_RULE, ERR_CONFLICT, ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.db.models import HelpRequest, HelpResponse, User
from src.domain import enums as E
from src.domain.state import help_sm
from src.services import ai_audit_service as ai
from src.services import item_service as item_svc
from src.services.auth_service import bound_resident
from src.services.notify_service import notify_user

router = APIRouter(tags=["c:services"])


class CreateServiceIn(BaseModel):
    kind: str = "HELP"  # HELP（求助）/ OFFER（提供）
    category: str = "邻里帮忙"
    title: str
    description: str = ""
    expectedTime: str = ""
    location: str = ""
    reward: str = ""
    priceCents: int = 0


async def _row(db: DbSession, row: HelpRequest, viewer=None) -> dict:
    author = await db.get(User, row.requester_id)
    responses = int((await db.scalar(
        select(func.count()).select_from(HelpResponse)
        .where(HelpResponse.request_id == row.id))) or 0)
    return {
        "id": str(row.id),
        "kind": "求助" if row.kind == "HELP" else "提供",
        "kindCode": row.kind,
        "icon": "hand-help" if row.kind == "HELP" else "hand-heart",
        "category": row.category,
        "title": row.title,
        "description": row.description,
        "time": item_svc._time_ago(row.created_at),
        "place": row.location,
        "distance": "",
        "reward": row.reward,
        "author": author.nickname if author else "",
        "avatar": (author.avatar_key if author else "") or "avatar-person-1",
        "avatarClass": "person",
        "responses": responses,
        "price": row.reward or "",
        "credit": "信用极好" if (author and author.credit_score >= 90) else "信用良好",
        "status": row.status,
        "urgent": row.urgent,
    }


@router.get("/services")
async def list_services(user: CurrentUser, db: DbSession,
                        kind: str | None = Query(default=None),
                        category: str | None = Query(default=None),
                        page: int = Query(default=1), pageSize: int = Query(default=20)):
    resident = await bound_resident(db, user.id)
    stmt = select(HelpRequest).where(HelpRequest.status.in_(
        [E.HelpStatus.OPEN, E.HelpStatus.MATCHING, E.HelpStatus.IN_PROGRESS]))
    if resident:
        stmt = stmt.where(HelpRequest.community_id == resident.community_id)
    if kind:
        code = {"求助": "HELP", "提供": "OFFER"}.get(kind, kind.upper())
        stmt = stmt.where(HelpRequest.kind == code)
    if category:
        stmt = stmt.where(HelpRequest.category == category)
    rows, total = await paginate(db, stmt.order_by(HelpRequest.urgent.desc(),
                                                   HelpRequest.id.desc()), page, pageSize)
    return paginated([await _row(db, row, user) for row in rows], page, pageSize, total)


@router.post("/services")
async def create_service(payload: CreateServiceIn, user: CurrentUser, db: DbSession):
    """发布互助/服务：内容安全审核后上线（A-09）。"""
    resident = await bound_resident(db, user.id)
    if not resident:
        raise ApiError(ERR_BIZ_RULE, "请先完成小区认证后再发布互助", 422)
    title = payload.title.strip()
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)
    hit = next((kw for kw in ai.BANNED_KEYWORDS
                if kw in title or kw in payload.description), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"内容包含违禁信息（{hit}），已被拦截", 422)
    row = HelpRequest(
        community_id=resident.community_id,
        requester_id=user.id,
        kind="OFFER" if payload.kind in ("提供", "OFFER") else "HELP",
        category=payload.category,
        title=title,
        description=payload.description[:500],
        expected_time=payload.expectedTime,
        location=payload.location[:64],
        reward=payload.reward[:32],
        status=E.HelpStatus.OPEN,
    )
    db.add(row)
    await db.commit()
    return ok(await _row(db, row, user), "互助已发布")


@router.post("/services/{service_id}/respond")
async def respond_service(service_id: int, user: CurrentUser, db: DbSession):
    """响应互助（去重：同一用户仅一条有效响应）。"""
    row = await db.get(HelpRequest, service_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "互助不存在", 404)
    if row.requester_id == user.id:
        raise ApiError(ERR_BIZ_RULE, "不能响应自己发布的互助", 422)
    existing = await db.scalar(
        select(HelpResponse).where(HelpResponse.request_id == row.id,
                                   HelpResponse.responder_id == user.id,
                                   HelpResponse.status == "PENDING"))
    if existing:
        raise ApiError(ERR_CONFLICT, "你已响应过该互助", 409)
    if row.status not in (E.HelpStatus.OPEN, E.HelpStatus.MATCHING):
        raise ApiError(ERR_BIZ_RULE, "该互助已匹配或关闭", 422)
    db.add(HelpResponse(request_id=row.id, responder_id=user.id, status="PENDING"))
    if row.status == E.HelpStatus.OPEN:
        row.status = help_sm.fire(row.status, E.HelpStatus.MATCHING)
    await notify_user(db, row.requester_id, category="INTERACTION",
                      title="有人响应了你的互助",
                      description=f"「{row.title}」有了新响应",
                      icon="hand-heart", tag="互助")
    await db.commit()
    responses = int((await db.scalar(
        select(func.count()).select_from(HelpResponse)
        .where(HelpResponse.request_id == row.id))) or 0)
    return ok({"success": True, "responses": responses})
