from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.api.utils import paginate
from src.core.audit import write_audit, write_outbox
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import (
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.db.models import (
    Broadcast,
    Community,
    HelpRequest,
    HelpResponse,
    Item,
    ItemComment,
    LifePost,
    User,
)
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import content_sm, help_sm
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


async def _broadcast_row(db: DbSession, broadcast: Broadcast) -> dict:
    community = await db.get(Community, broadcast.community_id)
    return {
        "id": str(broadcast.id), "title": broadcast.title, "subtitle": broadcast.subtitle,
        "type": broadcast.type, "status": broadcast.status, "important": broadcast.important,
        "content": broadcast.content, "media": broadcast.media or [],
        "responseCount": broadcast.response_count,
        "communityId": str(broadcast.community_id),
        "communityName": community.name if community else "",
        "publishedAt": int(broadcast.published_at.timestamp() * 1000) if broadcast.published_at else 0,
        "updatedAt": int(broadcast.updated_at.timestamp() * 1000) if broadcast.updated_at else 0,
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
    """发布喇叭：创建即进入待审核（内容状态机 PENDING_REVIEW）。"""
    community = await db.get(Community, payload.communityId)
    if not community:
        raise ApiError(ERR_PARAM, "社区不存在", 400)
    if len(payload.title.strip()) < 2:
        raise ApiError(ERR_PARAM, "标题必填", 400)
    broadcast = Broadcast(
        community_id=payload.communityId, author_id=admin.id,
        type=payload.type, title=payload.title.strip()[:120],
        subtitle=payload.subtitle[:255], content=payload.content,
        media=payload.media[:9], important=payload.important,
        status=E.ContentStatus.PENDING_REVIEW,
    )
    db.add(broadcast)
    await db.flush()
    await write_audit(db, request, actor=admin, action="broadcast.create",
                      resource_type="broadcast", resource_id=broadcast.id,
                      before=None, after={"title": broadcast.title})
    await db.commit()
    return ok(await _broadcast_row(db, broadcast), "喇叭已提交审核")


@router.get("/broadcasts/{broadcast_id}")
async def broadcast_detail(broadcast_id: int, admin: CurrentAdmin, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    return ok(await _broadcast_row(db, broadcast))


@router.put("/broadcasts/{broadcast_id}",
            dependencies=[Depends(require_permission("community:broadcast:create"))])
async def update_broadcast(broadcast_id: int, payload: BroadcastIn,
                           request: Request, admin: CurrentAdmin, db: DbSession):
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    if broadcast.status not in (E.ContentStatus.DRAFT, E.ContentStatus.REJECTED,
                                E.ContentStatus.PENDING_REVIEW):
        raise ApiError(ERR_PARAM, "已发布内容需先下架再编辑", 400)
    before = {"title": broadcast.title}
    broadcast.title = payload.title.strip()[:120]
    broadcast.subtitle = payload.subtitle[:255]
    broadcast.content = payload.content
    broadcast.media = payload.media[:9]
    broadcast.important = payload.important
    broadcast.type = payload.type
    await write_audit(db, request, actor=admin, action="broadcast.update",
                      resource_type="broadcast", resource_id=broadcast.id,
                      before=before, after={"title": broadcast.title})
    await db.commit()
    return ok(await _broadcast_row(db, broadcast), "已保存")


@router.post("/broadcasts/{broadcast_id}/review",
             dependencies=[Depends(require_permission("community:broadcast:review"))])
async def review_broadcast(broadcast_id: int, payload: ReviewIn,
                           request: Request, admin: CurrentAdmin, db: DbSession):
    """审核：通过 → 已发布（移动端喇叭站立即可见）；驳回 → 必填原因。"""
    broadcast = await db.get(Broadcast, broadcast_id)
    if not broadcast:
        raise ApiError(ERR_NOT_FOUND, "喇叭不存在", 404)
    before = {"status": broadcast.status}
    if payload.decision == "APPROVE":
        broadcast.status = content_sm.fire(broadcast.status, E.ContentStatus.PUBLISHED)
        broadcast.published_at = utcnow()
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
    return {
        "id": str(row.id), "title": row.title, "kind": row.kind, "category": row.category,
        "status": row.status, "urgent": row.urgent, "location": row.location,
        "reward": row.reward, "description": row.description,
        "requester": requester.nickname if requester else "",
        "matchedHelper": helper.nickname if helper else "",
        "responses": responses, "closedReason": row.closed_reason,
        "communityId": str(row.community_id),
        "communityName": community.name if community else "",
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
    }


@router.get("/help-requests")
async def list_help_requests(admin: CurrentAdmin, db: DbSession,
                             communityId: int | None = Query(default=None),
                             status: str | None = Query(default=None),
                             keyword: str | None = Query(default=None),
                             page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(HelpRequest)
    if communityId:
        stmt = stmt.where(HelpRequest.community_id == communityId)
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


@router.get("/help-requests/{help_id}/responses")
async def help_responses(help_id: int, admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(HelpResponse).where(HelpResponse.request_id == help_id)
        .order_by(HelpResponse.id))).scalars().all())
    result = []
    for row in rows:
        responder = await db.get(User, row.responder_id)
        result.append({"id": str(row.id), "responder": responder.nickname if responder else "",
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

async def _life_row(db: DbSession, post: LifePost) -> dict:
    community = await db.get(Community, post.community_id)
    author = await db.get(User, post.author_id)
    return {
        "id": str(post.id), "title": post.title, "category": post.category,
        "status": post.status, "author": author.nickname if author else "",
        "authorId": str(post.author_id), "media": post.media or [],
        "cover": post.cover_key, "description": post.description,
        "stats": post.stats or {},
        "communityId": str(post.community_id),
        "communityName": community.name if community else "",
        "publishedAt": int(post.published_at.timestamp() * 1000) if post.published_at else 0,
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
