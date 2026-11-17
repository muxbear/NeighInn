from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select

from src.api.utils import epoch_ms, paginate
from src.core.audit import write_audit, write_outbox
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_any_permission, require_permission
from src.core.responses import (
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.core.storage import public_media_url
from src.db.models import (
    Broadcast,
    Community,
    Favorite,
    HelpRequest,
    HelpResponse,
    Item,
    ItemComment,
    LifeComment,
    LifePost,
    User,
)
from src.db.models.common import ensure_utc, utcnow
from src.domain import enums as E
from src.domain.state import content_sm, help_sm
from src.services.broadcast_service import (
    TYPE_LABELS,
    is_visible,
    resolve_window,
    to_epoch_ms,
)
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:content"])

"""内容域管理（社区喇叭/邻里互助/社区生活/评论治理）。
物品复核见 operations.py（W03）；本文件承载其余内容模块（详设 4.7.3 共享模板）。"""


class ReviewIn(BaseModel):
    decision: str = "APPROVE"
    reason: str = ""
    recommend: bool = False


# ---------------------------------------------------------------- 社区喇叭

class BroadcastIn(BaseModel):
    communityId: int
    title: str
    subtitle: str = ""
    type: str = "NEW_ITEM"  # URGENT_HELP / FREE_NEW / REWARD / NEW_ITEM
    content: str = ""
    media: list[str] = []
    important: bool = False
    # 即时生效（IMMEDIATE）或指定时间段（SCHEDULED）；留空时按 startAt 自动判定。
    effectiveMode: str = ""
    startAt: int | str | None = None
    endAt: int | str | None = None
    # 兼容旧字段与外部调用方。
    scheduledAt: int | str | None = None
    expiresAt: int | str | None = None
    durationHours: int | None = None


class BroadcastBatchIn(BaseModel):
    ids: list[int] = []


TONE_BY_TYPE = {
    "URGENT_HELP": "urgent",
    "FREE_NEW": "free",
    "REWARD": "reward",
    "NEW_ITEM": "new",
}


async def _broadcast_row(db: DbSession, broadcast: Broadcast) -> dict:
    community = await db.get(Community, broadcast.community_id)
    author = await db.get(User, broadcast.author_id) if broadcast.author_id else None
    now = utcnow()
    scheduled_at = ensure_utc(broadcast.scheduled_at)
    expires_at = ensure_utc(broadcast.expires_at)
    published_at = ensure_utc(broadcast.published_at)
    updated_at = ensure_utc(broadcast.updated_at)
    effective_status = broadcast.status
    if broadcast.status == E.ContentStatus.PUBLISHED and not is_visible(broadcast, now):
        effective_status = "EXPIRED"
    elif (broadcast.status == E.ContentStatus.SCHEDULED and scheduled_at
          and scheduled_at <= now):
        effective_status = E.ContentStatus.PUBLISHED
    type_label = TYPE_LABELS.get(broadcast.type, broadcast.type)
    return {
        "id": str(broadcast.id), "code": f"LB-{broadcast.id:05d}",
        "title": broadcast.title, "subtitle": broadcast.subtitle,
        "type": broadcast.type, "typeLabel": type_label, "category": type_label,
        "status": broadcast.status, "effectiveStatus": effective_status,
        "important": broadcast.important,
        "owner": author.nickname if author else "社区运营",
        "performance": f"{broadcast.response_count} 次互动",
        "content": broadcast.content, "media": broadcast.media or [],
        "responseCount": broadcast.response_count,
        "communityId": str(broadcast.community_id),
        "communityName": community.name if community else "",
        "scheduledAt": to_epoch_ms(scheduled_at),
        "expiresAt": to_epoch_ms(expires_at),
        "publishedAt": to_epoch_ms(published_at),
        "updatedAt": to_epoch_ms(updated_at),
    }


@router.get("/broadcasts")
async def list_broadcasts(admin: CurrentAdmin, db: DbSession,
                          communityId: int | None = Query(default=None),
                          status: str | None = Query(default=None),
                          keyword: str | None = Query(default=None),
                          page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(Broadcast)
    if communityId:
        stmt = stmt.where(Broadcast.community_id == communityId)
    if status:
        stmt = stmt.where(Broadcast.status == status)
    if keyword:
        stmt = stmt.where(Broadcast.title.ilike(f"%{keyword}%"))
    rows, total = await paginate(db, stmt.order_by(Broadcast.id.desc()), page, pageSize)
    return paginated([await _broadcast_row(db, row) for row in rows], page, pageSize, total)


@router.post("/broadcasts",
             dependencies=[Depends(require_permission("community:broadcast:create"))])
async def create_broadcast(payload: BroadcastIn, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    """发布喇叭：后台直接发布生效，无需审核；支持即时或指定时间段生效。"""
    community = await db.get(Community, payload.communityId)
    if not community:
        raise ApiError(ERR_PARAM, "社区不存在", 400)
    if len(payload.title.strip()) < 2:
        raise ApiError(ERR_PARAM, "标题必填", 400)
    try:
        start_at, expires_at, status = resolve_window(
            effective_mode=payload.effectiveMode,
            start_at=payload.startAt,
            end_at=payload.endAt,
            scheduled_at=payload.scheduledAt,
            expires_at=payload.expiresAt,
            duration_hours=payload.durationHours,
        )
    except ValueError as exc:
        raise ApiError(ERR_PARAM, str(exc), 400) from exc
    broadcast = Broadcast(
        community_id=payload.communityId, author_id=admin.id,
        type=payload.type, title=payload.title.strip()[:120],
        subtitle=payload.subtitle[:255], content=payload.content,
        media=payload.media[:9], important=payload.important,
        tone=TONE_BY_TYPE.get(payload.type, "new"),
        status=status, scheduled_at=start_at, expires_at=expires_at,
        published_at=start_at if status == E.ContentStatus.PUBLISHED else None,
    )
    db.add(broadcast)
    await db.flush()
    await write_audit(db, request, actor=admin, action="broadcast.create",
                      resource_type="broadcast", resource_id=broadcast.id,
                      before=None, after={"title": broadcast.title, "status": broadcast.status,
                                          "scheduledAt": payload.startAt,
                                          "expiresAt": payload.endAt})
    if status == E.ContentStatus.PUBLISHED:
        await write_outbox(db, event_type="BroadcastPublished", aggregate_type="broadcast",
                           aggregate_id=broadcast.id, payload={"status": broadcast.status})
    await db.commit()
    message = ("喇叭已发布并生效" if status == E.ContentStatus.PUBLISHED
               else "喇叭已发布，将在设定时间自动生效")
    return ok(await _broadcast_row(db, broadcast), message)


@router.get("/broadcasts/{broadcast_id}")
async def broadcast_detail(broadcast_id: int, admin: CurrentAdmin, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    return ok(await _broadcast_row(db, broadcast))


@router.put("/broadcasts/{broadcast_id}",
            dependencies=[Depends(require_any_permission(
                "community:broadcast:update", "community:broadcast:create"))])
async def update_broadcast(broadcast_id: int, payload: BroadcastIn,
                           request: Request, admin: CurrentAdmin, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    if len(payload.title.strip()) < 2:
        raise ApiError(ERR_PARAM, "标题必填", 400)
    before = {"title": broadcast.title, "status": broadcast.status}
    broadcast.title = payload.title.strip()[:120]
    broadcast.subtitle = payload.subtitle[:255]
    broadcast.content = payload.content
    broadcast.media = payload.media[:9]
    broadcast.important = payload.important
    broadcast.type = payload.type
    broadcast.tone = TONE_BY_TYPE.get(payload.type, broadcast.tone or "new")
    schedule_fields = {"effectiveMode", "startAt", "endAt", "scheduledAt",
                       "expiresAt", "durationHours"}
    if schedule_fields & payload.model_fields_set:
        try:
            start_at, expires_at, status = resolve_window(
                effective_mode=payload.effectiveMode,
                start_at=payload.startAt,
                end_at=payload.endAt,
                scheduled_at=payload.scheduledAt,
                expires_at=payload.expiresAt,
                duration_hours=payload.durationHours,
            )
        except ValueError as exc:
            raise ApiError(ERR_PARAM, str(exc), 400) from exc
        broadcast.scheduled_at = start_at
        broadcast.expires_at = expires_at
        broadcast.status = status
        broadcast.published_at = start_at if status == E.ContentStatus.PUBLISHED else None
    await write_audit(db, request, actor=admin, action="broadcast.update",
                      resource_type="broadcast", resource_id=broadcast.id,
                      before=before, after={"title": broadcast.title,
                                            "status": broadcast.status})
    await db.commit()
    return ok(await _broadcast_row(db, broadcast), "已保存")


async def _delete_broadcast_row(db: DbSession, request: Request,
                                admin: CurrentAdmin, broadcast: Broadcast) -> None:
    before = await _broadcast_row(db, broadcast)
    await db.execute(delete(Favorite).where(Favorite.target_type == "BROADCAST",
                                            Favorite.target_id == broadcast.id))
    await db.delete(broadcast)
    await write_audit(db, request, actor=admin, action="broadcast.delete",
                      resource_type="broadcast", resource_id=broadcast.id,
                      before=before, after=None)


@router.delete("/broadcasts/{broadcast_id}",
               dependencies=[Depends(require_any_permission(
                   "community:broadcast:delete", "community:broadcast:offline"))])
async def delete_broadcast(broadcast_id: int, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    await _delete_broadcast_row(db, request, admin, broadcast)
    await db.commit()
    return ok({"id": str(broadcast_id)}, "喇叭已删除")


@router.post("/broadcasts/batch-delete",
             dependencies=[Depends(require_any_permission(
                 "community:broadcast:delete", "community:broadcast:offline"))])
async def batch_delete_broadcasts(payload: BroadcastBatchIn, request: Request,
                                  admin: CurrentAdmin, db: DbSession):
    if not payload.ids:
        raise ApiError(ERR_PARAM, "请选择要删除的喇叭", 400)
    deleted: list[str] = []
    failed: list[dict] = []
    for broadcast_id in dict.fromkeys(payload.ids):
        broadcast = await db.get(Broadcast, broadcast_id)
        if not broadcast:
            failed.append({"id": str(broadcast_id), "reason": "喇叭不存在"})
            continue
        await _delete_broadcast_row(db, request, admin, broadcast)
        deleted.append(str(broadcast_id))
    await db.commit()
    return ok({"deleted": deleted, "failed": failed},
              f"已删除 {len(deleted)} 条喇叭")


@router.post("/broadcasts/{broadcast_id}/review",
             dependencies=[Depends(require_permission("community:broadcast:review"))])
async def review_broadcast(broadcast_id: int, payload: ReviewIn,
                           request: Request, admin: CurrentAdmin, db: DbSession):
    """存量待审核内容兼容接口；新喇叭发布后已直接生效。"""
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    before = {"status": broadcast.status}
    if payload.decision == "APPROVE":
        if broadcast.status != E.ContentStatus.PUBLISHED:
            broadcast.status = content_sm.fire(broadcast.status, E.ContentStatus.PUBLISHED)
        broadcast.published_at = broadcast.published_at or utcnow()
    else:
        if len(payload.reason.strip()) < 5:
            raise ApiError(ERR_PARAM, "驳回原因必填（不少于 5 个字）", 400)
        broadcast.status = content_sm.fire(broadcast.status, E.ContentStatus.REJECTED)
    await write_audit(db, request, actor=admin, action="broadcast.review",
                      resource_type="broadcast", resource_id=broadcast.id,
                      before=before, after={"status": broadcast.status,
                                            "reason": payload.reason})
    await write_outbox(db, event_type="BroadcastPublished" if payload.decision == "APPROVE"
                       else "BroadcastRejected", aggregate_type="broadcast",
                       aggregate_id=broadcast.id, payload={"status": broadcast.status})
    await db.commit()
    return ok(await _broadcast_row(db, broadcast), "审核完成")


@router.post("/broadcasts/{broadcast_id}/offline",
             dependencies=[Depends(require_permission("community:broadcast:offline"))])
async def offline_broadcast(broadcast_id: int, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    before = {"status": broadcast.status}
    broadcast.status = content_sm.fire(broadcast.status, E.ContentStatus.OFFLINE)
    await write_audit(db, request, actor=admin, action="broadcast.offline",
                      resource_type="broadcast", resource_id=broadcast.id,
                      before=before, after={"status": broadcast.status})
    await db.commit()
    return ok(await _broadcast_row(db, broadcast), "已下架")


# ---------------------------------------------------------------- 邻里互助

async def _help_row(db: DbSession, row: HelpRequest) -> dict:
    community = await db.get(Community, row.community_id)
    requester = await db.get(User, row.requester_id)
    helper = await db.get(User, row.matched_helper_id) if row.matched_helper_id else None
    responses = int((await db.scalar(
        select(func.count()).select_from(HelpResponse)
        .where(HelpResponse.request_id == row.id))) or 0)
    media_keys = [str(key) for key in (row.media or []) if key]
    media = [public_media_url(key) for key in media_keys]
    cover_key = row.cover_key or (media_keys[0] if media_keys else "")
    kind_label = "邻里求助" if row.kind == "HELP" else "邻里服务"
    time_label = row.expected_time or "时间待定"
    return {
        "id": str(row.id), "code": f"HZ-{row.id:05d}", "title": row.title,
        "kind": row.kind, "kindCode": row.kind, "kindLabel": kind_label,
        "subtitle": f"{kind_label} · {time_label} · {len(media_keys)} 个媒体",
        "category": row.category,
        "status": row.status, "urgent": row.urgent, "location": row.location,
        "reward": row.reward, "description": row.description,
        "expectedTime": row.expected_time,
        "media": media, "mediaKeys": media_keys, "mediaType": row.media_type,
        "cover": public_media_url(cover_key), "coverKey": cover_key,
        "requester": requester.nickname if requester else "",
        "matchedHelper": helper.nickname if helper else "",
        "responses": responses, "closedReason": row.closed_reason,
        "performance": f"{responses} 人响应" if row.kind == "HELP" else "服务信息",
        "communityId": str(row.community_id),
        "communityName": community.name if community else "",
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
        "updatedAt": int(row.updated_at.timestamp() * 1000) if row.updated_at else 0,
    }


@router.get("/help-requests")
async def list_help_requests(admin: CurrentAdmin, db: DbSession,
                             communityId: int | None = Query(default=None),
                             kind: str | None = Query(default=None),
                             status: str | None = Query(default=None),
                             keyword: str | None = Query(default=None),
                             page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(HelpRequest)
    if communityId:
        stmt = stmt.where(HelpRequest.community_id == communityId)
    if kind:
        code = {"求助": "HELP", "提供": "OFFER", "服务": "OFFER"}.get(kind, kind.upper())
        stmt = stmt.where(HelpRequest.kind == code)
    if status:
        stmt = stmt.where(HelpRequest.status == status)
    if keyword:
        stmt = stmt.where(or_(HelpRequest.title.ilike(f"%{keyword}%"),
                              HelpRequest.description.ilike(f"%{keyword}%")))
    rows, total = await paginate(db, stmt.order_by(HelpRequest.id.desc()), page, pageSize)
    return paginated([await _help_row(db, row) for row in rows], page, pageSize, total)


@router.get("/help-requests/{help_id}")
async def help_detail(help_id: int, admin: CurrentAdmin, db: DbSession):
    row = await db.get(HelpRequest, help_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "互助不存在", 404)
    return ok(await _help_row(db, row))


class HelpUpdateIn(BaseModel):
    """后台编辑互助/服务：仅传需要变更的字段，未传字段保持原值。"""

    kind: str | None = None
    category: str | None = None
    title: str | None = None
    description: str | None = None
    expectedTime: str | None = None
    location: str | None = None
    reward: str | None = None
    urgent: bool | None = None
    media: list[str] | None = None
    mediaType: str | None = None
    coverKey: str | None = None


def _is_video_key(key: str) -> bool:
    return key.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".m4v"))


@router.put("/help-requests/{help_id}",
            dependencies=[Depends(require_permission("community:help:update"))])
async def update_help(help_id: int, payload: HelpUpdateIn, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    """后台编辑互助/服务全字段，媒体以对象键增删替换。"""
    row = await db.get(HelpRequest, help_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "互助不存在", 404)

    kind = payload.kind.upper() if payload.kind is not None else row.kind
    if kind not in ("HELP", "OFFER"):
        raise ApiError(ERR_PARAM, "互助类型不合法", 400)

    title = payload.title.strip() if payload.title is not None else row.title
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)

    category = payload.category.strip() if payload.category is not None else row.category
    if len(category) > 32:
        raise ApiError(ERR_PARAM, "分类最多 32 个字", 400)

    description = (payload.description.strip() if payload.description is not None
                   else row.description)
    if len(description) > 500:
        raise ApiError(ERR_PARAM, "详细说明最多 500 个字", 400)

    expected_time = (payload.expectedTime.strip() if payload.expectedTime is not None
                     else row.expected_time)
    location = payload.location.strip() if payload.location is not None else row.location
    reward = payload.reward.strip() if payload.reward is not None else row.reward
    if len(expected_time) > 64 or len(location) > 64 or len(reward) > 32:
        raise ApiError(ERR_PARAM, "时间/地点/酬谢说明超出长度限制", 400)

    media_keys = [str(key) for key in (row.media or []) if key]
    if payload.media is not None:
        media_keys = []
        for raw_key in payload.media:
            key = str(raw_key).strip()
            if key and key not in media_keys:
                media_keys.append(key)
    if len(media_keys) > 12:
        raise ApiError(ERR_PARAM, "图片/视频最多 12 个", 400)

    media_type = payload.mediaType or row.media_type
    if payload.media is not None and payload.mediaType is None:
        media_type = ("VIDEO" if len(media_keys) == 1 and _is_video_key(media_keys[0])
                      else "GALLERY")
    if media_type not in ("VIDEO", "GALLERY"):
        raise ApiError(ERR_PARAM, "媒体类型不合法", 400)
    has_video = any(_is_video_key(key) for key in media_keys)
    if media_type == "VIDEO" and (len(media_keys) != 1 or not has_video):
        raise ApiError(ERR_PARAM, "短视频互助只能包含一个视频", 400)
    if media_type == "GALLERY" and has_video:
        raise ApiError(ERR_PARAM, "图片与短视频不能混排", 400)

    cover_key = row.cover_key
    if payload.coverKey is not None:
        cover_key = payload.coverKey.strip()
        if cover_key and cover_key not in media_keys:
            raise ApiError(ERR_PARAM, "封面必须使用当前互助的媒体文件", 400)
    if not cover_key or cover_key not in media_keys:
        cover_key = media_keys[0] if media_keys else ""

    before = {
        "kind": row.kind, "title": row.title, "category": row.category,
        "description": row.description, "expectedTime": row.expected_time,
        "location": row.location, "reward": row.reward, "urgent": row.urgent,
        "media": list(row.media or []), "coverKey": row.cover_key,
        "mediaType": row.media_type,
    }
    row.kind = kind
    row.title = title
    row.category = category
    row.description = description
    row.expected_time = expected_time
    row.location = location
    row.reward = reward
    if payload.urgent is not None:
        row.urgent = payload.urgent
    row.media = media_keys
    row.cover_key = cover_key
    row.media_type = media_type
    await write_audit(db, request, actor=admin, action="help.update",
                      resource_type="help_request", resource_id=row.id,
                      before=before, after={
                          "kind": kind, "title": title, "category": category,
                          "expectedTime": expected_time, "location": location,
                          "reward": reward, "urgent": row.urgent,
                          "media": media_keys, "coverKey": cover_key,
                          "mediaType": media_type,
                      })
    await db.commit()
    return ok(await _help_row(db, row), "互助信息已更新")


@router.post("/help-requests/{help_id}/review",
             dependencies=[Depends(require_permission("community:help:review"))])
async def review_help(help_id: int, payload: ReviewIn, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    """审核邻里服务：通过后进入待响应；驳回必须填写原因并通知发布人。"""
    row = await db.get(HelpRequest, help_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "互助不存在", 404)
    if row.kind != "OFFER":
        raise ApiError(ERR_PARAM, "邻里求助默认直接发布，无需审核", 400)
    before = {"status": row.status}
    if payload.decision == "APPROVE":
        row.status = help_sm.fire(row.status, E.HelpStatus.OPEN)
        await notify_user(db, row.requester_id, category="COMMUNITY",
                          title="邻里服务已通过审核",
                          description=f"「{row.title}」已展示在邻里服务",
                          icon="hand-heart", tag="审核",
                          route={"type": "service", "id": str(row.id), "kind": "OFFER"})
    else:
        reason = payload.reason.strip()
        if len(reason) < 5:
            raise ApiError(ERR_PARAM, "驳回原因必填（不少于 5 个字）", 400)
        row.status = help_sm.fire(row.status, E.HelpStatus.REJECTED)
        row.closed_reason = reason
        await notify_user(db, row.requester_id, category="COMMUNITY",
                          title="邻里服务未通过审核", description=reason,
                          icon="alert", tag="审核",
                          route={"type": "service", "id": str(row.id), "kind": "OFFER"})
    await write_audit(db, request, actor=admin, action="help.review",
                      resource_type="help_request", resource_id=row.id,
                      before=before,
                      after={"status": row.status, "reason": payload.reason})
    await db.commit()
    return ok(await _help_row(db, row), "审核完成")


async def _delete_help_row(db: DbSession, request: Request, admin: CurrentAdmin,
                           row: HelpRequest) -> dict:
    before = await _help_row(db, row)
    requester_id, title = row.requester_id, row.title
    await db.execute(delete(HelpResponse).where(HelpResponse.request_id == row.id))
    await db.delete(row)
    await notify_user(db, requester_id, category="COMMUNITY", title="互助信息已删除",
                      description=f"「{title}」已被平台删除",
                      icon="alert", tag="审核")
    await write_audit(db, request, actor=admin, action="help.delete",
                      resource_type="help_request", resource_id=before["id"],
                      before=before, after=None)
    return before


@router.delete("/help-requests/{help_id}",
               dependencies=[Depends(require_permission("community:help:delete"))])
async def delete_help(help_id: int, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    row = await db.get(HelpRequest, help_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "互助不存在", 404)
    await _delete_help_row(db, request, admin, row)
    await db.commit()
    return ok({"id": str(help_id)}, "互助信息已删除")


class BatchIdsIn(BaseModel):
    ids: list[int] = []


@router.post("/help-requests/batch-delete",
             dependencies=[Depends(require_permission("community:help:delete"))])
async def batch_delete_help(payload: BatchIdsIn, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    """批量删除互助/服务：逐条写审计并返回成功/失败明细。"""
    if not payload.ids:
        raise ApiError(ERR_PARAM, "请选择要删除的互助信息", 400)
    deleted: list[str] = []
    failed: list[dict] = []
    for help_id in dict.fromkeys(payload.ids):
        row = await db.get(HelpRequest, help_id)
        if not row:
            failed.append({"id": str(help_id), "reason": "互助不存在"})
            continue
        await _delete_help_row(db, request, admin, row)
        deleted.append(str(help_id))
    await db.commit()
    return ok({"deleted": deleted, "failed": failed},
              f"已删除 {len(deleted)} 条互助信息")


@router.get("/help-requests/{help_id}/responses")
async def help_responses(help_id: int, admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(HelpResponse).where(HelpResponse.request_id == help_id)
        .order_by(HelpResponse.id))).scalars().all())
    result = []
    for row in rows:
        responder = await db.get(User, row.responder_id)
        result.append({"id": str(row.id), "responder": responder.nickname if responder else "",
                       "responderId": str(row.responder_id),
                       "message": row.message, "status": row.status,
                       "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0})
    return ok(result)


@router.post("/help-requests/{help_id}/match",
             dependencies=[Depends(require_permission("community:help:match"))])
async def match_help(help_id: int, payload: dict, request: Request,
                     admin: CurrentAdmin, db: DbSession):
    """人工撮合：指定响应者成交（同时只有一个匹配中的响应，详设 5.6.1）。"""
    row = await db.get(HelpRequest, help_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "互助不存在", 404)
    responder_id = int(payload.get("responderId", 0))
    response = await db.scalar(
        select(HelpResponse).where(HelpResponse.request_id == help_id,
                                   HelpResponse.responder_id == responder_id,
                                   HelpResponse.status == "PENDING"))
    if not response:
        raise ApiError(ERR_PARAM, "该响应者不存在或已被处理", 400)
    row.status = help_sm.fire(row.status, E.HelpStatus.IN_PROGRESS)
    row.matched_helper_id = responder_id
    response.status = "ACCEPTED"
    others = list((await db.execute(
        select(HelpResponse).where(HelpResponse.request_id == help_id,
                                   HelpResponse.id != response.id,
                                   HelpResponse.status == "PENDING"))).scalars().all())
    for other in others:
        other.status = "REJECTED"
    await notify_user(db, responder_id, category="INTERACTION", title="互助撮合成功",
                      description=f"「{row.title}」已匹配你为帮手", icon="hand-heart", tag="互助")
    await notify_user(db, row.requester_id, category="INTERACTION", title="互助已匹配",
                      description=f"「{row.title}」已匹配帮手", icon="hand-heart", tag="互助")
    await write_audit(db, request, actor=admin, action="help.match",
                      resource_type="help_request", resource_id=row.id,
                      before={"status": "OPEN"},
                      after={"status": row.status, "helper": responder_id})
    await db.commit()
    return ok(await _help_row(db, row), "撮合成功")


@router.post("/help-requests/{help_id}/close",
             dependencies=[Depends(require_permission("community:help:close"))])
async def close_help(help_id: int, payload: dict, request: Request,
                     admin: CurrentAdmin, db: DbSession):
    row = await db.get(HelpRequest, help_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "互助不存在", 404)
    reason = str(payload.get("reason", "")).strip()
    target = E.HelpStatus.COMPLETED if payload.get("completed") else E.HelpStatus.CLOSED
    row.status = help_sm.fire(row.status, target)
    row.closed_reason = reason
    row.closed_at = utcnow()
    await write_audit(db, request, actor=admin, action="help.close",
                      resource_type="help_request", resource_id=row.id,
                      before=None, after={"status": row.status, "reason": reason})
    await db.commit()
    return ok(await _help_row(db, row), "互助已关闭")


# ---------------------------------------------------------------- 社区生活

class LifePostUpdateIn(BaseModel):
    """后台编辑生活内容：仅传需要变更的字段，未传字段保持原值。"""

    title: str | None = None
    category: str | None = None
    description: str | None = None
    media: list[str] | None = None
    coverKey: str | None = None
    mediaType: str | None = None


async def _life_row(db: DbSession, post: LifePost) -> dict:
    community = await db.get(Community, post.community_id)
    author = await db.get(User, post.author_id)
    media_keys = [str(key) for key in (post.media or []) if key]
    media = [public_media_url(key) for key in media_keys]
    cover_key = post.cover_key or (media_keys[0] if media_keys else "")
    media_label = "短视频" if post.media_type == "VIDEO" else "照片集"
    return {
        "id": str(post.id), "code": f"LIFE-{post.id:04d}",
        "title": post.title, "category": post.category,
        "subtitle": f"{media_label} · {len(media_keys)} 个媒体",
        "status": post.status, "author": author.nickname if author else "",
        "authorId": str(post.author_id),
        "media": media, "mediaKeys": media_keys, "mediaType": post.media_type,
        "cover": public_media_url(cover_key), "coverKey": cover_key,
        "description": post.description,
        "stats": post.stats or {},
        "communityId": str(post.community_id),
        "communityName": community.name if community else "",
        "createdAt": epoch_ms(post.created_at),
        "updatedAt": epoch_ms(post.updated_at),
        "publishedAt": epoch_ms(post.published_at),
    }


@router.get("/life-posts")
async def list_life_posts(admin: CurrentAdmin, db: DbSession,
                          communityId: int | None = Query(default=None),
                          status: str | None = Query(default=None),
                          keyword: str | None = Query(default=None),
                          page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(LifePost)
    if communityId:
        stmt = stmt.where(LifePost.community_id == communityId)
    if status:
        stmt = stmt.where(LifePost.status == status)
    if keyword:
        stmt = stmt.where(LifePost.title.ilike(f"%{keyword}%"))
    rows, total = await paginate(db, stmt.order_by(LifePost.id.desc()), page, pageSize)
    return paginated([await _life_row(db, row) for row in rows], page, pageSize, total)


@router.get("/life-posts/{post_id}")
async def life_post_detail(post_id: int, admin: CurrentAdmin, db: DbSession):
    post = await db.get(LifePost, post_id)
    if not post:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)
    return ok(await _life_row(db, post))


@router.put("/life-posts/{post_id}",
            dependencies=[Depends(require_permission("community:life:update"))])
async def update_life_post(post_id: int, payload: LifePostUpdateIn, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    """后台编辑生活内容（详设 7.5.7）：正文元数据可改，媒体文件与作者保持不变。"""
    post = await db.get(LifePost, post_id)
    if not post:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)

    title = payload.title.strip() if payload.title is not None else post.title
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)

    category = payload.category.strip() if payload.category is not None else post.category
    if not (1 <= len(category) <= 32):
        raise ApiError(ERR_PARAM, "分类需 1–32 个字", 400)

    description = (payload.description.strip() if payload.description is not None
                   else post.description)
    if len(description) > 500:
        raise ApiError(ERR_PARAM, "正文最多 500 个字", 400)

    media_keys = [str(key) for key in (post.media or []) if key]
    if payload.media is not None:
        media_keys = []
        for raw_key in payload.media:
            key = str(raw_key).strip()
            if key and key not in media_keys:
                media_keys.append(key)
        if not media_keys:
            raise ApiError(ERR_PARAM, "请至少保留一张图片或一个视频", 400)

    media_type = payload.mediaType or post.media_type
    if payload.media is not None and payload.mediaType is None:
        # 未显式指定媒体类型时按原类型与媒体数量推断。
        media_type = ("VIDEO" if post.media_type == "VIDEO" and len(media_keys) == 1
                      else "GALLERY")
    if media_type not in ("VIDEO", "GALLERY"):
        raise ApiError(ERR_PARAM, "媒体类型不合法", 400)
    if media_type == "VIDEO" and len(media_keys) != 1:
        raise ApiError(ERR_PARAM, "短视频动态只能包含一个视频", 400)
    if media_type == "GALLERY" and len(media_keys) > 12:
        raise ApiError(ERR_PARAM, "图文动态最多保留 12 个媒体", 400)

    cover_key = post.cover_key
    if payload.coverKey is not None:
        cover_key = payload.coverKey.strip()
        if cover_key and cover_key not in media_keys:
            raise ApiError(ERR_PARAM, "封面必须使用当前内容的媒体文件", 400)
    if not cover_key or cover_key not in media_keys:
        cover_key = media_keys[0] if media_keys else ""

    before = {"title": post.title, "category": post.category,
              "description": post.description, "coverKey": post.cover_key,
              "media": list(post.media or []), "mediaType": post.media_type}
    post.title = title
    post.category = category
    post.description = description
    post.media = media_keys
    post.cover_key = cover_key
    post.media_type = media_type
    await write_audit(db, request, actor=admin, action="life.update",
                      resource_type="life_post", resource_id=post.id,
                      before=before, after={"title": title, "category": category,
                                            "coverKey": cover_key, "media": media_keys,
                                            "mediaType": media_type})
    await db.commit()
    return ok(await _life_row(db, post), "内容已更新")


@router.post("/life-posts/{post_id}/review",
             dependencies=[Depends(require_permission("community:life:review"))])
async def review_life_post(post_id: int, payload: ReviewIn,
                           request: Request, admin: CurrentAdmin, db: DbSession):
    post = await db.get(LifePost, post_id)
    if not post:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)
    before = {"status": post.status}
    if payload.decision == "APPROVE":
        post.status = content_sm.fire(post.status, E.ContentStatus.PUBLISHED)
        post.published_at = utcnow()
        await notify_user(db, post.author_id, category="COMMUNITY",
                          title="生活动态已发布", description=f"「{post.title}」已通过审核",
                          icon="coffee", tag="审核", route={"type": "life", "id": str(post.id)})
    else:
        if len(payload.reason.strip()) < 5:
            raise ApiError(ERR_PARAM, "驳回原因必填（不少于 5 个字）", 400)
        post.status = content_sm.fire(post.status, E.ContentStatus.REJECTED)
        await notify_user(db, post.author_id, category="COMMUNITY",
                          title="生活动态未通过审核", description=payload.reason.strip(),
                          icon="alert", tag="审核", route={"type": "life", "id": str(post.id)})
    await write_audit(db, request, actor=admin, action="life.review",
                      resource_type="life_post", resource_id=post.id,
                      before=before, after={"status": post.status, "reason": payload.reason})
    await db.commit()
    return ok(await _life_row(db, post), "审核完成")


@router.post("/life-posts/{post_id}/offline",
             dependencies=[Depends(require_permission("community:life:offline"))])
async def offline_life_post(post_id: int, payload: dict, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    post = await db.get(LifePost, post_id)
    if not post:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)
    before = {"status": post.status}
    post.status = content_sm.fire(post.status, E.ContentStatus.OFFLINE)
    reason = str(payload.get("reason", "")).strip()
    await notify_user(db, post.author_id, category="COMMUNITY",
                      title="生活动态已被下线", description=reason or "内容违规",
                      icon="alert", tag="审核", route={"type": "life", "id": str(post.id)})
    await write_audit(db, request, actor=admin, action="life.offline",
                      resource_type="life_post", resource_id=post.id,
                      before=before, after={"status": post.status, "reason": reason})
    await db.commit()
    return ok(await _life_row(db, post), "内容已下线")


@router.delete("/life-posts/{post_id}",
               dependencies=[Depends(require_permission("community:life:delete"))])
async def delete_life_post(post_id: int, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    """删除生活内容：评论与收藏一并清理，审计日志保留删除前快照。"""
    post = await db.get(LifePost, post_id)
    if not post:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)
    before = await _life_row(db, post)
    author_id, title = post.author_id, post.title
    await db.execute(delete(LifeComment).where(LifeComment.post_id == post.id))
    await db.execute(delete(Favorite).where(Favorite.target_type == "LIFE",
                                            Favorite.target_id == post.id))
    await db.delete(post)
    await notify_user(db, author_id, category="COMMUNITY", title="生活动态已被删除",
                      description=f"「{title}」已被平台删除", icon="alert", tag="审核")
    await write_audit(db, request, actor=admin, action="life.delete",
                      resource_type="life_post", resource_id=post_id,
                      before=before, after=None)
    await db.commit()
    return ok({"id": str(post_id)}, "内容已删除")


# ---------------------------------------------------------------- 评论治理（W05-03 关联）

@router.get("/comments")
async def list_comments(admin: CurrentAdmin, db: DbSession,
                        status: str | None = Query(default=None),
                        keyword: str | None = Query(default=None),
                        page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(ItemComment)
    if status:
        stmt = stmt.where(ItemComment.status == status)
    if keyword:
        stmt = stmt.where(ItemComment.content.ilike(f"%{keyword}%"))
    rows, total = await paginate(db, stmt.order_by(ItemComment.id.desc()), page, pageSize)
    result = []
    for row in rows:
        author = await db.get(User, row.user_id)
        item = await db.get(Item, row.item_id)
        result.append({"id": str(row.id), "content": row.content, "status": row.status,
                       "author": author.nickname if author else "",
                       "itemTitle": item.title if item else "", "itemId": str(row.item_id),
                       "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0})
    return paginated(result, page, pageSize, total)


@router.post("/comments/{comment_id}/hide",
             dependencies=[Depends(require_permission("community:item:review"))])
async def hide_comment(comment_id: int, payload: dict, request: Request,
                       admin: CurrentAdmin, db: DbSession):
    comment = await db.get(ItemComment, comment_id)
    if not comment:
        raise ApiError(ERR_NOT_FOUND, "留言不存在", 404)
    before = {"status": comment.status}
    comment.status = "HIDDEN"
    await write_audit(db, request, actor=admin, action="comment.hide",
                      resource_type="item_comment", resource_id=comment.id,
                      before=before, after={"status": "HIDDEN",
                                            "reason": payload.get("reason", "")})
    await db.commit()
    return ok({"id": str(comment.id), "status": "HIDDEN"}, "留言已隐藏")
