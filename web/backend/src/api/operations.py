from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import get_or_404, paginate
from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ok, paginated
from src.db.models import Broadcast, HelpRequest, Item, LifePost

router = APIRouter(tags=["operations"])

STATUS_MAP = {
    "broadcast": "待审核",
    "item": "待审核",
    "help": "待响应",
    "life": "待审核",
}

METRICS: dict[str, list[dict]] = {
    "broadcast": [
        {"label": "今日播报", "value": "28", "note": "较昨日 +6"},
        {"label": "待审核", "value": "6", "note": "2 条高优先级", "attention": True},
        {"label": "今日互动", "value": "1,286", "note": "评论与点赞"},
        {"label": "内容触达率", "value": "82.4%", "note": "近 7 日 +3.2%"},
    ],
    "items": [
        {"label": "在售物品", "value": "386", "note": "本周新增 52"},
        {"label": "待审核", "value": "12", "note": "平均等待 18 分钟", "attention": True},
        {"label": "本周成交", "value": "86", "note": "成交额 ¥12,680"},
        {"label": "热门推荐位", "value": "8 / 12", "note": "剩余 4 个展位"},
    ],
    "help": [
        {"label": "今日求助", "value": "18", "note": "紧急求助 2 条"},
        {"label": "待响应", "value": "8", "note": "平均等待 12 分钟", "attention": True},
        {"label": "本周完成", "value": "126", "note": "完成率 94.6%"},
        {"label": "互助信用分", "value": "96.2", "note": "社区平均分"},
    ],
    "life": [
        {"label": "频道内容", "value": "248", "note": "覆盖 8 个分类"},
        {"label": "今日阅读", "value": "6,328", "note": "较昨日 +14.8%", "attention": True},
        {"label": "待审核", "value": "9", "note": "含 3 条商户投稿"},
        {"label": "内容收藏率", "value": "12.6%", "note": "近 7 日 +1.9%"},
    ],
}


class OperationIn(BaseModel):
    communityId: int = 1
    title: str
    subtitle: str = ""
    owner: str = "社区运营 · 李知夏"
    category: str = ""
    content: str = ""
    priceCents: int = 0
    tradeType: str = "MONETARY"


def serialize_broadcast(row: Broadcast) -> dict:
    return {
        "id": str(row.id), "code": row.code, "title": row.title, "subtitle": row.subtitle,
        "owner": row.owner, "category": row.category, "performance": row.performance,
        "status": row.status, "updatedAt": row.updated_label, "communityId": str(row.community_id),
    }


def serialize_item(row: Item) -> dict:
    return {
        "id": str(row.id), "code": row.code, "title": row.title, "subtitle": row.subtitle,
        "owner": row.seller, "seller": row.seller, "category": row.category,
        "performance": row.performance, "status": row.status, "updatedAt": row.updated_label,
        "price": f"¥{row.price_cents / 100:g}", "priceCents": row.price_cents,
        "tradeType": row.trade_type, "communityId": str(row.community_id),
    }


def serialize_help(row: HelpRequest) -> dict:
    return {
        "id": str(row.id), "code": row.code, "title": row.title, "subtitle": row.subtitle,
        "owner": row.owner, "category": row.category, "performance": row.performance,
        "status": row.status, "updatedAt": row.updated_label, "communityId": str(row.community_id),
    }


def serialize_life(row: LifePost) -> dict:
    return {
        "id": str(row.id), "code": row.code, "title": row.title, "subtitle": row.subtitle,
        "owner": row.owner, "category": row.category, "performance": row.performance,
        "status": row.status, "updatedAt": row.updated_label, "communityId": str(row.community_id),
    }


async def _list(db, model, serializer, community_id, status, keyword, page, page_size):
    stmt = select(model)
    if community_id:
        stmt = stmt.where(model.community_id == community_id)
    if status:
        stmt = stmt.where(model.status == status)
    if keyword:
        like = f"%{keyword}%"
        text_fields = [model.title]
        if hasattr(model, "subtitle"):
            text_fields.append(model.subtitle)
        stmt = stmt.where(or_(*[field.ilike(like) for field in text_fields]))
    stmt = stmt.order_by(model.id)
    rows, total = await paginate(db, stmt, page, page_size)
    return paginated([serializer(row) for row in rows], page, page_size, total)


@router.get("/operations/overview")
async def overview(db: DbSession, admin: CurrentAdmin, module: str = Query(default="broadcast")):
    return ok({"metrics": METRICS.get(module, METRICS["broadcast"])})


@router.get("/broadcasts")
async def broadcasts(
    db: DbSession, admin: CurrentAdmin,
    communityId: int | None = None, status: str | None = None, keyword: str | None = None,
    page: int = 1, pageSize: int = 20,
):
    return await _list(db, Broadcast, serialize_broadcast, communityId, status, keyword, page, pageSize)


@router.post("/broadcasts")
async def create_broadcast(payload: OperationIn, db: DbSession, admin: CurrentAdmin):
    row = Broadcast(
        community_id=payload.communityId, code=f"LB{int(datetime.now().timestamp() * 1000)}",
        title=payload.title, subtitle=payload.subtitle, owner=payload.owner,
        category=payload.category or "邻里播报", status="待审核", updated_label="刚刚",
        content=payload.content,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_broadcast(row), "发布喇叭已提交审核")


@router.post("/broadcasts/{broadcast_id}/review")
async def review_broadcast(broadcast_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Broadcast, broadcast_id)
    row.status = "已发布" if payload.get("decision", "APPROVE") == "APPROVE" else "已下架"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_broadcast(row), "审核完成")


@router.post("/broadcasts/{broadcast_id}/offline")
async def offline_broadcast(broadcast_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Broadcast, broadcast_id)
    row.status = "已下架"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_broadcast(row), "内容已下架")


@router.get("/items")
async def items(
    db: DbSession, admin: CurrentAdmin,
    communityId: int | None = None, status: str | None = None, keyword: str | None = None,
    page: int = 1, pageSize: int = 20,
):
    return await _list(db, Item, serialize_item, communityId, status, keyword, page, pageSize)


@router.post("/items/{item_id}/review")
async def review_item(item_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Item, item_id)
    row.status = "在售" if payload.get("decision", "APPROVE") == "APPROVE" else "已下架"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_item(row), "物品审核完成")


@router.post("/items/{item_id}/recommend")
async def recommend_item(item_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Item, item_id)
    row.recommended = bool(payload.get("enabled", True))
    await db.commit()
    return ok(serialize_item(row), "推荐位已更新")


@router.post("/items/{item_id}/offline")
async def offline_item(item_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Item, item_id)
    row.status = "已下架"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_item(row), "物品已下架")


@router.get("/help-requests")
async def help_requests(
    db: DbSession, admin: CurrentAdmin,
    communityId: int | None = None, status: str | None = None, keyword: str | None = None,
    page: int = 1, pageSize: int = 20,
):
    return await _list(db, HelpRequest, serialize_help, communityId, status, keyword, page, pageSize)


@router.post("/help-requests")
async def create_help(payload: OperationIn, db: DbSession, admin: CurrentAdmin):
    row = HelpRequest(
        community_id=payload.communityId, code=f"HZ{int(datetime.now().timestamp() * 1000)}",
        title=payload.title, subtitle=payload.subtitle, owner=payload.owner,
        category=payload.category or "邻里帮忙", status="待响应", updated_label="刚刚",
        description=payload.content,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_help(row), "互助已代发")


@router.post("/help-requests/{help_id}/match")
async def match_help(help_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, HelpRequest, help_id)
    row.status = "进行中"
    row.performance = f"已匹配 {payload.get('helper', '陈师傅')}"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_help(row), "撮合成功")


@router.post("/help-requests/{help_id}/close")
async def close_help(help_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, HelpRequest, help_id)
    row.status = "已完成"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_help(row), "互助已关闭")


@router.get("/life-posts")
async def life_posts(
    db: DbSession, admin: CurrentAdmin,
    communityId: int | None = None, status: str | None = None, keyword: str | None = None,
    page: int = 1, pageSize: int = 20,
):
    return await _list(db, LifePost, serialize_life, communityId, status, keyword, page, pageSize)


@router.post("/life-posts")
async def create_life(payload: OperationIn, db: DbSession, admin: CurrentAdmin):
    row = LifePost(
        community_id=payload.communityId, code=f"SH{int(datetime.now().timestamp() * 1000)}",
        title=payload.title, subtitle=payload.subtitle, owner=payload.owner,
        category=payload.category or "周末去哪", status="待审核", updated_label="刚刚",
        content=payload.content,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_life(row), "内容已提交审核")


@router.post("/life-posts/{post_id}/review")
async def review_life(post_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, LifePost, post_id)
    row.status = "已发布" if payload.get("decision", "APPROVE") == "APPROVE" else "已下线"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_life(row), "内容审核完成")


@router.post("/life-posts/{post_id}/offline")
async def offline_life(post_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, LifePost, post_id)
    row.status = "已下线"
    row.updated_label = "刚刚"
    await db.commit()
    return ok(serialize_life(row), "内容已下线")
