from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_NOT_FOUND, ApiError, ok
from src.db.models import (
    CreditLog,
    Favorite,
    HelpRequest,
    HotKeyword,
    Item,
    LifePost,
    SearchHistory,
    ViewHistory,
)
from src.domain import enums as E
from src.services import item_service as item_svc

router = APIRouter(tags=["c:engage"])


class FavoriteIn(BaseModel):
    id: int
    type: str = "ITEM"  # ITEM / SERVICE / LIFE / BROADCAST


@router.get("/favorites")
async def favorites(user: CurrentUser, db: DbSession,
                    type: str = Query(default="item")):
    """收藏（M07-02）：商品/服务/生活动态分 Tab。"""
    target_map = {"item": ("ITEM", Item), "service": ("SERVICE", HelpRequest),
                  "life": ("LIFE", LifePost)}
    target_type, model = target_map.get(type, target_map["item"])
    rows = list((await db.execute(
        select(Favorite).where(Favorite.user_id == user.id,
                               Favorite.target_type == target_type)
        .order_by(Favorite.id.desc()).limit(100))).scalars().all())
    result = {"items": [], "services": [], "life": []}
    for favorite in rows:
        target = await db.get(model, favorite.target_id)
        if not target:
            continue
        if target_type == "ITEM":
            if target.status == E.ItemStatus.ON_SALE:
                result["items"].append(await item_svc.serialize_item(db, target, user))
        elif target_type == "SERVICE":
            result["services"].append({"id": str(target.id), "title": target.title,
                                       "category": target.category, "reward": target.reward})
        else:
            result["life"].append({"id": str(target.id), "title": target.title,
                                   "cover": target.cover_key, "category": target.category})
    return ok(result)


@router.post("/favorites")
async def add_favorite(user: CurrentUser, db: DbSession, payload: FavoriteIn):
    target_type = payload.type.upper()
    existing = await db.scalar(
        select(Favorite).where(Favorite.user_id == user.id,
                               Favorite.target_type == target_type,
                               Favorite.target_id == payload.id))
    if not existing:
        db.add(Favorite(user_id=user.id, target_type=target_type, target_id=payload.id))
        await db.commit()
    return ok({"success": True})


@router.delete("/favorites")
async def remove_favorite(user: CurrentUser, db: DbSession, id: int = Query(...),
                          type: str = Query(default="ITEM")):
    existing = await db.scalar(
        select(Favorite).where(Favorite.user_id == user.id,
                               Favorite.target_type == type.upper(),
                               Favorite.target_id == id))
    if not existing:
        raise ApiError(ERR_NOT_FOUND, "收藏不存在", 404)
    await db.delete(existing)
    await db.commit()
    return ok({"success": True})


@router.get("/history")
async def view_history(user: CurrentUser, db: DbSession):
    """浏览足迹（M02-07，≤100 条）。"""
    rows = list((await db.execute(
        select(ViewHistory).where(ViewHistory.user_id == user.id)
        .order_by(ViewHistory.viewed_at.desc()).limit(100))).scalars().all())
    items = []
    for row in rows:
        item = await db.get(Item, row.item_id)
        if item:
            items.append(await item_svc.serialize_item(db, item, user))
    return ok(items)


@router.post("/history")
async def add_view_history(user: CurrentUser, db: DbSession, payload: FavoriteIn):
    existing = await db.scalar(
        select(ViewHistory).where(ViewHistory.user_id == user.id,
                                  ViewHistory.item_id == payload.id))
    if existing:
        from src.db.models.common import utcnow

        existing.viewed_at = utcnow()
    else:
        db.add(ViewHistory(user_id=user.id, item_id=payload.id))
    await db.commit()
    return ok({"success": True})


@router.get("/search")
async def search_all(user: CurrentUser, db: DbSession, keyword: str = Query(default="")):
    """全局搜索（M02-05）：标题 + 描述（pg_trgm/全文检索 Phase 3 增强）。"""
    keyword = keyword.strip()
    if not keyword:
        return ok({"keyword": "", "items": [], "lifePosts": [], "services": []})
    like = f"%{keyword}%"
    items = list((await db.execute(
        select(Item).where(Item.status == E.ItemStatus.ON_SALE,
                           or_(Item.title.ilike(like), Item.description.ilike(like)))
        .order_by(Item.id.desc()).limit(20))).scalars().all())
    life = list((await db.execute(
        select(LifePost).where(LifePost.status == "PUBLISHED",
                               or_(LifePost.title.ilike(like),
                                   LifePost.description.ilike(like)))
        .order_by(LifePost.id.desc()).limit(10))).scalars().all())
    services = list((await db.execute(
        select(HelpRequest).where(HelpRequest.status == E.HelpStatus.OPEN,
                                  or_(HelpRequest.title.ilike(like),
                                      HelpRequest.description.ilike(like)))
        .order_by(HelpRequest.id.desc()).limit(10))).scalars().all())
    return ok({
        "keyword": keyword,
        "items": [await item_svc.serialize_item(db, item, user) for item in items],
        "lifePosts": [{"id": str(post.id), "title": post.title, "cover": post.cover_key}
                      for post in life],
        "services": [{"id": str(row.id), "title": row.title, "category": row.category,
                      "reward": row.reward} for row in services],
    })


@router.get("/search/hot")
async def hot_keywords(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(HotKeyword).where(HotKeyword.status == "启用")
        .order_by(HotKeyword.sort, HotKeyword.score.desc()).limit(10))).scalars().all())
    return ok([row.keyword for row in rows])


@router.get("/search/history")
async def search_history(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(SearchHistory).where(SearchHistory.user_id == user.id)
        .order_by(SearchHistory.id.desc()).limit(10))).scalars().all())
    return ok([row.keyword for row in rows])


class SearchHistoryIn(BaseModel):
    keyword: str


@router.post("/search/history")
async def add_search_history(user: CurrentUser, db: DbSession, payload: SearchHistoryIn):
    keyword = payload.keyword.strip()
    if keyword:
        existing = await db.scalar(
            select(SearchHistory).where(SearchHistory.user_id == user.id,
                                        SearchHistory.keyword == keyword))
        if existing:
            await db.delete(existing)
        db.add(SearchHistory(user_id=user.id, keyword=keyword[:64]))
        await db.commit()
    rows = list((await db.execute(
        select(SearchHistory).where(SearchHistory.user_id == user.id)
        .order_by(SearchHistory.id.desc()).limit(10))).scalars().all())
    return ok([row.keyword for row in rows])


@router.delete("/search/history")
async def clear_search_history(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(SearchHistory).where(SearchHistory.user_id == user.id))).scalars().all())
    for row in rows:
        await db.delete(row)
    await db.commit()
    return ok([])


@router.get("/mine/stats")
async def mine_stats(user: CurrentUser, db: DbSession):
    publish_count = int((await db.scalar(
        select(func.count()).select_from(Item).where(Item.seller_id == user.id))) or 0)
    favorite_count = int((await db.scalar(
        select(func.count()).select_from(Favorite).where(Favorite.user_id == user.id))) or 0)
    history_count = int((await db.scalar(
        select(func.count()).select_from(ViewHistory).where(
            ViewHistory.user_id == user.id))) or 0)
    life_count = int((await db.scalar(
        select(func.count()).select_from(LifePost).where(
            LifePost.author_id == user.id))) or 0)
    service_count = int((await db.scalar(
        select(func.count()).select_from(HelpRequest).where(
            HelpRequest.requester_id == user.id))) or 0)
    return ok({
        "publishCount": publish_count,
        "favoriteCount": favorite_count,
        "historyCount": history_count,
        "lifeCount": life_count,
        "serviceCount": service_count,
        "creditScore": user.credit_score,
    })


@router.get("/mine/credit")
async def mine_credit(user: CurrentUser, db: DbSession):
    """信用中心（M07-08）：分数构成明细（成交履约/按时验货/评价/违规）。"""
    logs = list((await db.execute(
        select(CreditLog).where(CreditLog.user_id == user.id)
        .order_by(CreditLog.id.desc()).limit(50))).scalars().all())
    level = ("极好" if user.credit_score >= 90 else "良好" if user.credit_score >= 70
             else "一般" if user.credit_score >= 50 else "待提升")
    next_level = "极好" if user.credit_score < 90 else "—"
    return ok({
        "score": user.credit_score,
        "level": level,
        "nextLevel": next_level,
        "records": [
            {"id": str(log.id), "title": log.note or log.event_type, "delta": log.delta,
             "time": log.created_at.strftime("%m-%d %H:%M") if log.created_at else ""}
            for log in logs
        ],
    })
