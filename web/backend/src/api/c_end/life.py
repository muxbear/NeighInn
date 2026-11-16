from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.api.utils import paginate
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_BIZ_RULE, ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.db.models import Favorite, LifeComment, LifePost, User
from src.services import ai_audit_service as ai
from src.services import item_service as item_svc
from src.services.auth_service import bound_resident

router = APIRouter(tags=["c:life"])


class PublishLifeIn(BaseModel):
    mediaType: str = "gallery"  # video / gallery
    media: list[str] = []
    title: str
    description: str = ""
    category: str = "邻里日常"  # 小区风景/邻里日常/个人风采/萌宠生活


class LifeCommentIn(BaseModel):
    content: str


async def _row(db: DbSession, post: LifePost, viewer=None) -> dict:
    author = await db.get(User, post.author_id)
    liked = False
    if viewer:
        liked = bool(await db.scalar(
            select(Favorite.id).where(Favorite.user_id == viewer.id,
                                      Favorite.target_type == "LIFE",
                                      Favorite.target_id == post.id).limit(1)))
    stats = post.stats or {}
    media = post.media or []
    return {
        "id": str(post.id),
        "type": "video" if post.media_type == "VIDEO" else "gallery",
        "category": post.category,
        "title": post.title,
        "description": post.description,
        "images": media,
        "cover": post.cover_key or (media[0] if media else ""),
        "author": author.nickname if author else "",
        "avatar": (author.avatar_key if author else "") or "avatar-person-1",
        "avatarClass": "nature",
        "area": "",
        "time": item_svc._time_ago(post.published_at or post.created_at),
        "views": stats.get("views", 0),
        "likes": stats.get("likes", 0),
        "comments": stats.get("comments", 0),
        "liked": liked,
        "following": False,
    }


@router.get("/life/posts")
async def life_posts(user: CurrentUser, db: DbSession,
                     category: str | None = Query(default=None),
                     page: int = Query(default=1), pageSize: int = Query(default=20)):
    """小区生活：仅已发布内容对本小区可见。"""
    resident = await bound_resident(db, user.id)
    stmt = select(LifePost).where(LifePost.status == "PUBLISHED")
    if resident:
        stmt = stmt.where(LifePost.community_id == resident.community_id)
    if category:
        stmt = stmt.where(LifePost.category == category)
    rows, total = await paginate(db, stmt.order_by(LifePost.published_at.desc().nullslast(),
                                                   LifePost.id.desc()), page, pageSize)
    return paginated([await _row(db, post, user) for post in rows], page, pageSize, total)


@router.post("/life/posts")
async def publish_life(payload: PublishLifeIn, user: CurrentUser, db: DbSession):
    """发布生活动态：进入待审核（内容状态机 PENDING_REVIEW），复核通过后发布。"""
    resident = await bound_resident(db, user.id)
    if not resident:
        raise ApiError(ERR_BIZ_RULE, "请先完成小区认证后再发布生活动态", 422)
    title = payload.title.strip()
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)
    if not payload.media:
        raise ApiError(ERR_PARAM, "请至少上传一张图片或一个视频", 400)
    hit = next((kw for kw in ai.BANNED_KEYWORDS
                if kw in title or kw in payload.description), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"内容包含违禁信息（{hit}），已被拦截", 422)

    post = LifePost(
        community_id=resident.community_id,
        author_id=user.id,
        title=title,
        description=payload.description[:500],
        category=payload.category,
        media_type="VIDEO" if payload.mediaType == "video" else "GALLERY",
        cover_key=payload.media[0],
        media=payload.media[:9],
        status="PENDING_REVIEW",
        stats={"views": 0, "likes": 0, "comments": 0},
    )
    db.add(post)
    await db.commit()
    return ok(await _row(db, post, user), "已提交审核，通过后将在小区生活展示")


@router.get("/life/posts/{post_id}")
async def life_post_detail(post_id: int, user: CurrentUser, db: DbSession):
    post = await db.get(LifePost, post_id)
    visible = bool(post) and (post.status == "PUBLISHED" or post.author_id == user.id)
    if not visible:
        raise ApiError(ERR_NOT_FOUND, "内容不存在或未发布", 404)
    stats = dict(post.stats or {})
    stats["views"] = stats.get("views", 0) + 1
    post.stats = stats
    await db.commit()
    return ok(await _row(db, post, user))


@router.post("/life/posts/{post_id}/like")
async def like_life_post(post_id: int, user: CurrentUser, db: DbSession):
    post = await db.get(LifePost, post_id)
    if not post:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)
    existing = await db.scalar(
        select(Favorite).where(Favorite.user_id == user.id,
                               Favorite.target_type == "LIFE",
                               Favorite.target_id == post.id))
    stats = dict(post.stats or {})
    if existing:
        await db.delete(existing)
        stats["likes"] = max(0, stats.get("likes", 0) - 1)
        liked = False
    else:
        db.add(Favorite(user_id=user.id, target_type="LIFE", target_id=post.id))
        stats["likes"] = stats.get("likes", 0) + 1
        liked = True
    post.stats = stats
    await db.commit()
    return ok({"liked": liked, "likes": stats["likes"]})


@router.get("/life/posts/{post_id}/comments")
async def life_comments(post_id: int, user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(LifeComment).where(LifeComment.post_id == post_id,
                                  LifeComment.status == "PUBLISHED")
        .order_by(LifeComment.id.desc()).limit(100))).scalars().all())
    result = []
    for row in rows:
        author = await db.get(User, row.user_id)
        result.append({
            "id": str(row.id),
            "author": author.nickname if author else "",
            "avatar": (author.avatar_key if author else "") or "avatar-person-1",
            "content": row.content,
            "time": item_svc._time_ago(row.created_at),
            "verified": bool(author and author.realname_status == "VERIFIED"),
        })
    return ok(result)


@router.post("/life/posts/{post_id}/comments")
async def add_life_comment(post_id: int, payload: LifeCommentIn,
                           user: CurrentUser, db: DbSession):
    post = await db.get(LifePost, post_id)
    if not post:
        raise ApiError(ERR_NOT_FOUND, "内容不存在", 404)
    content = payload.content.strip()
    if not (1 <= len(content) <= 200):
        raise ApiError(ERR_PARAM, "评论需 1–200 个字", 400)
    hit = next((kw for kw in ai.BANNED_KEYWORDS if kw in content), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"评论包含违禁内容（{hit}），已被拦截", 422)
    comment = LifeComment(post_id=post.id, user_id=user.id, content=content)
    db.add(comment)
    stats = dict(post.stats or {})
    stats["comments"] = stats.get("comments", 0) + 1
    post.stats = stats
    await db.commit()
    return ok({"id": str(comment.id), "content": content, "time": "刚刚"})
