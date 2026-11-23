from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from src.api.utils import paginate
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_BIZ_RULE, ERR_CONFLICT, ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.core.storage import public_media_url
from src.db.models import HelpRequest, HelpResponse, User
from src.domain import enums as E
from src.domain.state import help_sm
from src.services import ai_audit_service as ai
from src.services import item_service as item_svc
from src.services.auth_service import browse_resident, browse_community_id
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
    media: list[str] = []
    mediaType: str = "GALLERY"
    coverKey: str = ""


def _is_video_key(key: str) -> bool:
    return key.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".m4v"))


async def _row(db: DbSession, row: HelpRequest, viewer=None) -> dict:
    author = await db.get(User, row.requester_id)
    responses = int((await db.scalar(
        select(func.count()).select_from(HelpResponse)
        .where(HelpResponse.request_id == row.id))) or 0)
    media_keys = [str(key) for key in (row.media or []) if key]
    media = [public_media_url(key) for key in media_keys]
    cover_key = row.cover_key or (media_keys[0] if media_keys else "")
    return {
        "id": str(row.id),
        "kind": "求助" if row.kind == "HELP" else "提供",
        "kindCode": row.kind,
        "icon": "hand-help" if row.kind == "HELP" else "hand-heart",
        "category": row.category,
        "title": row.title,
        "description": row.description,
        "expectedTime": row.expected_time,
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
        "media": media,
        "mediaKeys": media_keys,
        "mediaType": row.media_type,
        "cover": public_media_url(cover_key),
        "coverKey": cover_key,
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
    }


@router.get("/services")
async def list_services(user: CurrentUser, db: DbSession,
                        kind: str | None = Query(default=None),
                        category: str | None = Query(default=None),
                        page: int = Query(default=1), pageSize: int = Query(default=20)):
    community_id = await browse_community_id(db, user)
    if not community_id:
        return paginated([], page, pageSize, 0)
    stmt = select(HelpRequest).where(
        HelpRequest.community_id == community_id,
        HelpRequest.status.in_(
            [E.HelpStatus.OPEN, E.HelpStatus.MATCHING, E.HelpStatus.IN_PROGRESS]))
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
    """发布互助/服务：求助直接上线；邻里服务需后台审核通过后上线。"""
    resident = await browse_resident(db, user)
    if not resident:
        raise ApiError(ERR_BIZ_RULE, "请先完善入住小区信息后再发布互助", 422)
    title = payload.title.strip()
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)
    hit = next((kw for kw in ai.BANNED_KEYWORDS
                if kw in title or kw in payload.description), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"内容包含违禁信息（{hit}），已被拦截", 422)
    media_keys: list[str] = []
    for raw_key in payload.media:
        key = str(raw_key).strip()
        if key and key not in media_keys:
            media_keys.append(key)
    if len(media_keys) > 12:
        raise ApiError(ERR_PARAM, "互助图片/视频最多 12 个", 400)
    media_type = payload.mediaType if payload.mediaType in ("GALLERY", "VIDEO") else "GALLERY"
    has_video = any(_is_video_key(key) for key in media_keys)
    if media_type == "VIDEO" and (len(media_keys) != 1 or not has_video):
        raise ApiError(ERR_PARAM, "短视频互助只能包含一个视频", 400)
    if media_type == "GALLERY" and has_video:
        raise ApiError(ERR_PARAM, "图片与短视频不能混排", 400)
    if media_type == "GALLERY" and len(media_keys) > 12:
        raise ApiError(ERR_PARAM, "图片最多 12 张", 400)
    cover_key = payload.coverKey.strip()
    if cover_key and cover_key not in media_keys:
        raise ApiError(ERR_PARAM, "封面必须使用已上传的媒体文件", 400)
    if not cover_key:
        cover_key = media_keys[0] if media_keys else ""

    is_offer = payload.kind in ("提供", "OFFER")
    row = HelpRequest(
        community_id=resident.community_id,
        requester_id=user.id,
        kind="OFFER" if is_offer else "HELP",
        category=payload.category,
        title=title,
        description=payload.description[:500],
        expected_time=payload.expectedTime,
        location=payload.location[:64],
        reward=payload.reward[:32],
        media=media_keys,
        cover_key=cover_key,
        media_type=media_type,
        status=E.HelpStatus.PENDING_REVIEW if is_offer else E.HelpStatus.OPEN,
    )
    db.add(row)
    await db.commit()
    message = "邻里服务已提交审核，审核通过后展示" if is_offer else "邻里求助已发布"
    return ok(await _row(db, row, user), message)


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
