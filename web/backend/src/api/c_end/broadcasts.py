from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_NOT_FOUND, ApiError, ok
from src.db.models import Broadcast, Favorite
from src.services import item_service as item_svc
from src.services.auth_service import bound_resident

router = APIRouter(tags=["c:broadcasts"])

TYPE_LABEL = {"URGENT_HELP": "紧急求助", "FREE_NEW": "免费上新",
              "REWARD": "悬赏服务", "NEW_ITEM": "新上架"}
TYPE_ICON = {"URGENT_HELP": "megaphone-urgent", "FREE_NEW": "gift",
             "REWARD": "coin", "NEW_ITEM": "sparkle"}


async def _row(db: DbSession, broadcast: Broadcast, viewer=None) -> dict:
    favorited = False
    if viewer:
        favorited = bool(await db.scalar(
            select(Favorite.id).where(Favorite.user_id == viewer.id,
                                      Favorite.target_type == "BROADCAST",
                                      Favorite.target_id == broadcast.id).limit(1)))
    return {
        "id": str(broadcast.id),
        "type": TYPE_LABEL.get(broadcast.type, "新上架"),
        "icon": TYPE_ICON.get(broadcast.type, "sparkle"),
        "title": broadcast.title,
        "detail": broadcast.subtitle or broadcast.content[:60],
        "meta": item_svc._time_ago(broadcast.published_at or broadcast.created_at),
        "action": "查看详情",
        "tone": broadcast.tone,
        "facts": broadcast.facts or [],
        "description": broadcast.content,
        "responseCount": broadcast.response_count,
        "responderAvatars": [],
        "favorited": favorited,
        "important": broadcast.important,
    }


@router.get("/broadcasts")
async def list_broadcasts(user: CurrentUser, db: DbSession):
    """喇叭站事件流：仅已发布内容，紧急置顶。"""
    resident = await bound_resident(db, user.id)
    stmt = select(Broadcast).where(Broadcast.status == "PUBLISHED")
    if resident:
        stmt = stmt.where(Broadcast.community_id == resident.community_id)
    rows = list((await db.execute(
        stmt.order_by(Broadcast.important.desc(), Broadcast.published_at.desc().nullslast())
        .limit(50))).scalars().all())
    return ok([await _row(db, row, user) for row in rows])


@router.get("/broadcasts/{broadcast_id}")
async def broadcast_detail(broadcast_id: int, user: CurrentUser, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast or broadcast.status != "PUBLISHED":
        raise ApiError(ERR_NOT_FOUND, "内容不存在或未发布", 404)
    return ok(await _row(db, broadcast, user))


@router.post("/broadcasts/{broadcast_id}/favorite")
async def favorite_broadcast(broadcast_id: int, user: CurrentUser, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)
    existing = await db.scalar(
        select(Favorite).where(Favorite.user_id == user.id,
                               Favorite.target_type == "BROADCAST",
                               Favorite.target_id == broadcast.id))
    if existing:
        await db.delete(existing)
        favorited = False
    else:
        db.add(Favorite(user_id=user.id, target_type="BROADCAST", target_id=broadcast.id))
        favorited = True
    await db.commit()
    return ok({"favorited": favorited})


@router.post("/broadcasts/{broadcast_id}/respond")
async def respond_broadcast(broadcast_id: int, user: CurrentUser, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast or broadcast.status != "PUBLISHED":
        raise ApiError(ERR_NOT_FOUND, "内容不存在或未发布", 404)
    broadcast.response_count += 1
    await db.commit()
    return ok({"success": True, "responseCount": broadcast.response_count})
