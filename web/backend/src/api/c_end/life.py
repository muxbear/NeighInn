from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from src.api.utils import epoch_ms, paginate
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_BIZ_RULE, ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.core.storage import public_media_url
from src.db.models import Favorite, LifeComment, LifePost, User
from src.db.models.common import utcnow
from src.services import ai_audit_service as ai
from src.services import item_service as item_svc
from src.services.auth_service import browse_resident, browse_community_id

router = APIRouter(tags=["c:life"])


class PublishLifeIn(BaseModel):
    mediaType: str = "gallery"  # video / gallery
    media: list[str] = []
    title: str
    description: str = ""
    category: str = "邻里日常"  # 小区风景/邻里日常/个人风采/萌宠生活


class LifeCommentIn(BaseModel):
    content: str


LIFE_STATUS_LABELS = {
    "DRAFT": "草稿",
    "PENDING_REVIEW": "待审核",
    "PUBLISHED": "已发布",
    "REJECTED": "已驳回",
    "OFFLINE": "已下线",
}


async def _row(db: DbSession, post: LifePost, viewer=None) -> dict:
    author = await db.get(User, post.author_id)
    liked = False
    if viewer:
        liked = bool(await db.scalar(
            select(Favorite.id).where(Favorite.user_id == viewer.id,
                                      Favorite.target_type == "LIFE",
                                      Favorite.target_id == post.id).limit(1)))
    stats = post.stats or {}
    media_keys = [str(key) for key in (post.media or []) if key]
    media = [public_media_url(key) for key in media_keys]
    cover_key = post.cover_key or (media_keys[0] if media_keys else "")
    return {
        "id": str(post.id),
        "type": "video" if post.media_type == "VIDEO" else "gallery",
        "category": post.category,
        "title": post.title,
        "description": post.description,
        "images": media,
        "mediaKeys": media_keys,
        "cover": public_media_url(cover_key),
        "author": author.nickname if author else "",
        "avatar": (author.avatar_key if author else "") or "avatar-person-1",
        "avatarClass": "nature",
        "area": "",
        "time": item_svc._time_ago(post.published_at or post.created_at),
        "status": post.status,
        "statusLabel": LIFE_STATUS_LABELS.get(post.status, post.status),
        "createdAt": epoch_ms(post.created_at),
        "publishedAt": epoch_ms(post.published_at),
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
    community_id = await browse_community_id(db, user)
    if not community_id:
        return paginated([], page, pageSize, 0)
    stmt = select(LifePost).where(LifePost.status == "PUBLISHED",
                                  LifePost.community_id == community_id)
    # 移动端「全部」Tab 会原样下发中文分类名，不能当作真实分类过滤。
    if category and category != "全部":
        stmt = stmt.where(LifePost.category == category)
    rows, total = await paginate(db, stmt.order_by(LifePost.published_at.desc().nullslast(),
                                                   LifePost.id.desc()), page, pageSize)
    return paginated([await _row(db, post, user) for post in rows], page, pageSize, total)


@router.post("/life/posts")
async def publish_life(payload: PublishLifeIn, user: CurrentUser, db: DbSession):
    """发布生活动态：进入待审核（内容状态机 PENDING_REVIEW），复核通过后发布。"""
    resident = await browse_resident(db, user)
    if not resident:
        raise ApiError(ERR_BIZ_RULE, "请先完善入住小区信息后再发布生活动态", 422)
    title = payload.title.strip()
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)
    media = [str(item).strip() for item in payload.media if str(item).strip()]
    if not media:
        raise ApiError(ERR_PARAM, "请至少上传一张图片或一个视频", 400)
    is_video = payload.mediaType == "video"
    if is_video and len(media) != 1:
        raise ApiError(ERR_PARAM, "短视频动态只能上传一个视频", 400)
    if not is_video:
        media = media[:12]
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
        media_type="VIDEO" if is_video else "GALLERY",
        cover_key=media[0],
        media=media,
        status="PENDING_REVIEW",
        stats={"views": 0, "likes": 0, "comments": 0},
    )
    db.add(post)
    await db.commit()
    return ok(await _row(db, post, user), "已提交审核，通过后将在小区生活展示")


@router.get("/life/posts/mine")
async def my_life_posts(user: CurrentUser, db: DbSession,
                        page: int = Query(default=1), pageSize: int = Query(default=20)):
    """我的生活动态：包含待审核/已驳回等全部状态，移动端「我的」用于查看审核进度。"""
    stmt = (select(LifePost).where(LifePost.author_id == user.id)
            .order_by(LifePost.id.desc()))
    rows, total = await paginate(db, stmt, page, pageSize)
    return paginated([await _row(db, post, user) for post in rows], page, pageSize, total)


@router.get("/life/posts/{post_id}")
async def life_post_detail(post_id: int, user: CurrentUser, db: DbSession):
    post = await db.get(LifePost, post_id)
    visible = bool(post) and (post.status == "PUBLISHED" or post.author_id == user.id)
    if not visible:
        raise ApiError(ERR_NOT_FOUND, "内容不存在或未发布", 404)
    stats = dict(post.stats or {})
    # 仅已发布内容计入阅读表现：作者预览待审/驳回内容不应抬高频道指标。
    if post.status == "PUBLISHED":
        stats["views"] = int(stats.get("views", 0)) + 1
        # 阅读数据按自然日累计（运营口径 UTC+8），供后台「今日阅读」实时聚合；
        # 仅保留最近 14 天。
        today = (utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
        views_by_day = stats.get("viewsByDay")
        if not isinstance(views_by_day, dict):
            views_by_day = {}
        views_by_day[today] = int(views_by_day.get(today, 0)) + 1
        stats["viewsByDay"] = {
            key: int(value) for key, value in sorted(views_by_day.items())[-14:]
        }
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
