from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, update

from src.api.utils import paginate
from src.core.audit import write_audit, write_outbox
from src.core.config import settings
from src.core.deps import CurrentAdmin, DbSession
from src.core.idempotency import complete_idempotency, guard_idempotency
from src.core.permissions import require_permission
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_CONFLICT,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.db.models import (
    Community,
    Conversation,
    Favorite,
    HelpRequest,
    Item,
    ItemAudit,
    ItemCategory,
    ItemComment,
    ItemMedia,
    LifePost,
    Order,
    Resident,
    User,
    ViewHistory,
)
from src.db.models.common import ensure_utc, utcnow
from src.domain import enums as E
from src.domain.state import item_sm
from src.services.item_service import _public_media_url
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:operations"])

ItemReviewPerm = Depends(require_permission("community:item:review"))


class ReviewIn(BaseModel):
    decision: str = "APPROVE"  # APPROVE / REJECT / DOWNGRADE（W03-01）
    reason: str = ""
    recommend: bool = False


class RecommendIn(BaseModel):
    enabled: bool = True


class OfflineIn(BaseModel):
    reason: str = ""


class BatchOfflineIn(BaseModel):
    ids: list[int]
    reason: str


ITEM_CONDITIONS = ("全新", "九九新", "轻微使用痕迹", "明显使用痕迹", "有功能缺陷")


class ItemUpdateIn(BaseModel):
    """后台编辑物品：仅传需要变更的字段，未传字段保持原值。"""

    title: str | None = None
    description: str | None = None
    qualityDesc: str | None = None
    categoryId: int | None = None
    tradeType: str | None = None
    priceCents: int | None = None
    condition: str | None = None
    barterExpect: str | None = None


class CategoryIn(BaseModel):
    name: str
    parentId: int | None = None
    icon: str = ""
    sort: int = 0


# ---------------------------------------------------------------- 序列化

async def _row(db: DbSession, item: Item) -> dict:
    seller = await db.get(User, item.seller_id)
    community = await db.get(Community, item.community_id)
    category = await db.get(ItemCategory, item.category_id) if item.category_id else None
    media_count = int((await db.scalar(
        select(func.count()).select_from(ItemMedia).where(ItemMedia.item_id == item.id))) or 0)
    return {
        "id": str(item.id),
        "code": f"IT{item.id:08d}",
        "title": item.title,
        "subtitle": (item.quality_desc or "")[:60],
        "description": item.description,
        "qualityDesc": item.quality_desc,
        "barterExpect": item.barter_expect,
        "seller": seller.nickname if seller else "",
        "sellerId": str(item.seller_id),
        "category": category.name if category else "",
        "categoryId": str(item.category_id) if item.category_id else "",
        "priceCents": item.price_cents,
        "price": f"¥{item.price_cents / 100:g}" if item.trade_type == E.TradeType.MONETARY else "—",
        "tradeType": item.trade_type,
        "condition": item.condition,
        "status": item.status,
        "recommended": item.recommended,
        "mediaCount": media_count,
        "rejectReason": item.reject_reason,
        "communityId": str(item.community_id),
        "communityName": community.name if community else "",
        "publishedAt": int(item.published_at.timestamp() * 1000) if item.published_at else 0,
        "updatedAt": int(item.updated_at.timestamp() * 1000) if item.updated_at else 0,
    }


async def _audit_row(audit: ItemAudit) -> dict:
    return {
        "id": str(audit.id),
        "overall": audit.overall,
        "confidence": float(audit.confidence or 0),
        "dimensions": audit.dimensions or [],
        "risks": audit.risks or [],
        "suggestions": audit.suggestions or [],
        "decision": audit.decision,
        "reviewerId": str(audit.reviewer_id) if audit.reviewer_id else "",
        "reviewNote": audit.review_note,
        "traceId": audit.trace_id,
        "modelVersion": audit.model_version,
        "createdAt": int(audit.created_at.timestamp() * 1000) if audit.created_at else 0,
    }


# ---------------------------------------------------------------- 运营概览（真实聚合）

@router.get("/operations/overview")
async def operations_overview(admin: CurrentAdmin, db: DbSession,
                              module: str = Query(default="items"),
                              communityId: int | None = Query(default=None)):
    """运营页指标卡与 Tab 计数：全部来自实时聚合，禁止前端硬编码。"""
    if module == "help":
        return await _help_overview(db, communityId)
    if module == "life":
        return await _life_overview(db, communityId)
    if module != "items":
        raise ApiError(ERR_PARAM, "暂不支持该模块概览", 400)
    now = utcnow()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    scope = [Item.community_id == communityId] if communityId else []

    status_rows = (await db.execute(
        select(Item.status, func.count()).where(*scope).group_by(Item.status))).all()
    status_counts = {str(status): int(count) for status, count in status_rows}
    total = sum(status_counts.values())
    on_sale = status_counts.get(E.ItemStatus.ON_SALE, 0)
    pending_review = status_counts.get(E.ItemStatus.PENDING_REVIEW, 0)

    pending_times = list((await db.execute(
        select(Item.created_at).where(
            *scope, Item.status == E.ItemStatus.PENDING_REVIEW))).scalars().all())
    pending_waits = [
        max(0, int((now - ensure_utc(created_at)).total_seconds() // 60))
        for created_at in pending_times if created_at
    ]
    pending_avg_minutes = (
        round(sum(pending_waits) / len(pending_waits)) if pending_waits else 0)

    week_new = int((await db.scalar(
        select(func.count()).select_from(Item).where(
            *scope, Item.created_at >= week_start))) or 0)
    recommended = int((await db.scalar(
        select(func.count()).select_from(Item).where(
            *scope, Item.recommended.is_(True), Item.status == E.ItemStatus.ON_SALE))) or 0)

    order_scope = [Order.community_id == communityId] if communityId else []
    week_deals = int((await db.scalar(
        select(func.count()).select_from(Order).where(
            *order_scope,
            Order.status == E.OrderStatus.COMPLETED,
            func.coalesce(Order.completed_at, Order.updated_at) >= week_start,
        ))) or 0)
    week_gmv_cents = int((await db.scalar(
        select(func.coalesce(func.sum(Order.amount_cents), 0)).where(
            *order_scope,
            Order.status == E.OrderStatus.COMPLETED,
            Order.trade_type == E.TradeType.MONETARY,
            func.coalesce(Order.completed_at, Order.updated_at) >= week_start,
        ))) or 0)

    return ok({
        "module": module,
        "total": total,
        "statusCounts": status_counts,
        "metrics": {
            "onSale": on_sale,
            "pendingReview": pending_review,
            "pendingAvgMinutes": pending_avg_minutes,
            "weekNew": week_new,
            "weekDeals": week_deals,
            "weekGmvCents": week_gmv_cents,
            "recommended": recommended,
            "recommendSlots": settings.item_recommend_slots,
        },
    })


async def _help_overview(db: DbSession, community_id: int | None) -> dict:
    """邻里互助指标：今日求助、待响应、本周完成与社区信用分实时聚合。

    自然日/自然周按中国标准时间（UTC+8）划分；待响应平均等待时长按当前
    仍未响应的请求创建时间计算；本周完成率 = 本周完成 /（本周完成 + 本周关闭）。
    """
    scope = [HelpRequest.community_id == community_id] if community_id else []
    status_rows = (await db.execute(
        select(HelpRequest.status, func.count()).where(*scope).group_by(HelpRequest.status))).all()
    status_counts = {str(status): int(count) for status, count in status_rows}
    total = sum(status_counts.values())

    now = utcnow()
    local_now = now + timedelta(hours=8)
    today_start = local_now.replace(
        hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    week_start = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)

    today_help = int((await db.scalar(
        select(func.count()).select_from(HelpRequest).where(
            *scope, HelpRequest.kind == "HELP",
            HelpRequest.created_at >= today_start))) or 0)
    urgent_help = int((await db.scalar(
        select(func.count()).select_from(HelpRequest).where(
            *scope, HelpRequest.kind == "HELP", HelpRequest.urgent.is_(True),
            HelpRequest.created_at >= today_start))) or 0)

    pending_times = list((await db.execute(
        select(HelpRequest.created_at).where(
            *scope, HelpRequest.status == E.HelpStatus.OPEN))).scalars().all())
    pending_waits = [
        max(0, int((now - ensure_utc(created_at)).total_seconds() // 60))
        for created_at in pending_times if created_at
    ]
    pending_avg_minutes = (
        round(sum(pending_waits) / len(pending_waits)) if pending_waits else 0)

    week_completed = int((await db.scalar(
        select(func.count()).select_from(HelpRequest).where(
            *scope, HelpRequest.status == E.HelpStatus.COMPLETED,
            HelpRequest.closed_at >= week_start))) or 0)
    week_closed = int((await db.scalar(
        select(func.count()).select_from(HelpRequest).where(
            *scope, HelpRequest.status == E.HelpStatus.CLOSED,
            HelpRequest.closed_at >= week_start))) or 0)
    completed_denominator = week_completed + week_closed
    completion_rate = (
        round(week_completed / completed_denominator * 100, 1)
        if completed_denominator else 0.0
    )

    if community_id:
        credit_stmt = (
            select(func.avg(User.credit_score))
            .join(Resident, Resident.user_id == User.id)
            .where(Resident.community_id == community_id, Resident.status == "ACTIVE")
        )
    else:
        credit_stmt = select(func.avg(User.credit_score))
    credit_avg = float((await db.scalar(credit_stmt)) or 0)

    return ok({
        "module": "help",
        "total": total,
        "statusCounts": status_counts,
        "metrics": {
            "todayHelp": today_help,
            "urgentHelp": urgent_help,
            "pendingResponse": status_counts.get(E.HelpStatus.OPEN, 0),
            "pendingAvgMinutes": pending_avg_minutes,
            "weekCompleted": week_completed,
            "weekClosed": week_closed,
            "completionRate": completion_rate,
            "creditScore": round(credit_avg, 1),
        },
    })


async def _life_overview(db: DbSession, community_id: int | None) -> dict:
    """社区生活指标：内容量、待审核、今日阅读与收藏率全部实时聚合。

    「今日阅读」来自详情页按日累计的 stats.viewsByDay；
    「内容收藏率」= 累计点赞（Favorite LIFE）/ 累计阅读，阅读为 0 时展示 0。
    """
    scope = [LifePost.community_id == community_id] if community_id else []
    status_rows = (await db.execute(
        select(LifePost.status, func.count()).where(*scope).group_by(LifePost.status))).all()
    status_counts = {str(status): int(count) for status, count in status_rows}
    total = sum(status_counts.values())
    published = status_counts.get("PUBLISHED", 0)
    pending_review = status_counts.get("PENDING_REVIEW", 0)

    # 阅读/收藏指标只统计已发布内容：待审、驳回、下线的浏览不计入频道表现。
    published_scope = [*scope, LifePost.status == "PUBLISHED"]
    category_count = int((await db.scalar(
        select(func.count(func.distinct(LifePost.category))).where(*published_scope))) or 0)
    stats_rows = list((await db.execute(
        select(LifePost.stats).where(*published_scope))).scalars().all())

    now = utcnow()
    # 运营侧按中国标准时间（UTC+8）划分自然日，避免早上 8 点前阅读被算到前一天。
    today_key = (now + timedelta(hours=8)).strftime("%Y-%m-%d")
    yesterday_key = (now - timedelta(days=1) + timedelta(hours=8)).strftime("%Y-%m-%d")
    today_views = yesterday_views = total_views = total_likes = 0
    for stats in stats_rows:
        stats = stats or {}
        total_views += int(stats.get("views", 0) or 0)
        total_likes += int(stats.get("likes", 0) or 0)
        views_by_day = stats.get("viewsByDay")
        if isinstance(views_by_day, dict):
            today_views += int(views_by_day.get(today_key, 0) or 0)
            yesterday_views += int(views_by_day.get(yesterday_key, 0) or 0)

    delta = (
        round((today_views - yesterday_views) / yesterday_views * 100, 1)
        if yesterday_views else 0
    )
    favorite_rate = round(total_likes / total_views * 100, 1) if total_views else 0

    return ok({
        "module": "life",
        "total": total,
        "statusCounts": status_counts,
        "metrics": {
            "total": total,
            "published": published,
            "pendingReview": pending_review,
            "categoryCount": category_count,
            "todayViews": today_views,
            "yesterdayViews": yesterday_views,
            "todayViewsDelta": delta,
            "totalViews": total_views,
            "totalLikes": total_likes,
            "favoriteRate": favorite_rate,
        },
    })


# ---------------------------------------------------------------- 物品（W03-01）

@router.get("/items")
async def list_items(
    admin: CurrentAdmin, db: DbSession,
    communityId: int | None = Query(default=None),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Item)
    if communityId:
        stmt = stmt.where(Item.community_id == communityId)
    if status:
        stmt = stmt.where(Item.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Item.title.ilike(like), Item.quality_desc.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(Item.id.desc()), page, pageSize)
    return paginated([await _row(db, item) for item in rows], page, pageSize, total)


@router.get("/items/{item_id}")
async def item_detail(item_id: int, admin: CurrentAdmin, db: DbSession):
    """详情：基本信息 + 媒体 + 最新 AI 报告 + 审核记录（只读）。"""
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在", 404)
    row = await _row(db, item)
    media = list((await db.execute(
        select(ItemMedia).where(ItemMedia.item_id == item.id)
        .order_by(ItemMedia.sort, ItemMedia.id))).scalars().all())
    row["media"] = [
        {"objectKey": m.object_key, "mediaType": m.media_type, "sort": m.sort,
         "url": _public_media_url(m.object_key)} for m in media
    ]
    audits = list((await db.execute(
        select(ItemAudit).where(ItemAudit.item_id == item.id)
        .order_by(ItemAudit.id.desc()))).scalars().all())
    row["audits"] = [await _audit_row(audit) for audit in audits]
    row["barterExpect"] = item.barter_expect
    row["qualityDesc"] = item.quality_desc
    return ok(row)


@router.put("/items/{item_id}",
            dependencies=[Depends(require_permission("community:item:update"))])
async def update_item(item_id: int, payload: ItemUpdateIn, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    """后台编辑物品信息（W03-01 配套）：交易中与已完成物品不可改，避免破坏成交快照。"""
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在", 404)
    if item.status in (E.ItemStatus.RESERVED, E.ItemStatus.SOLD, E.ItemStatus.GIFTED):
        raise ApiError(ERR_BIZ_RULE, "交易中或已成交的物品不可编辑", 422)

    title = payload.title.strip() if payload.title is not None else item.title
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)

    trade_type = payload.tradeType or item.trade_type
    if trade_type not in E.TradeType.ALL:
        raise ApiError(ERR_PARAM, "交易方式不合法", 400)

    price_cents = payload.priceCents if payload.priceCents is not None else item.price_cents
    if price_cents < 0:
        raise ApiError(ERR_PARAM, "价格不能为负数", 400)
    if trade_type == E.TradeType.MONETARY and price_cents <= 0:
        raise ApiError(ERR_PARAM, "货币交易必须填写价格", 400)
    if trade_type == E.TradeType.FREE_GIFT:
        price_cents = 0

    barter_expect = (payload.barterExpect.strip() if payload.barterExpect is not None
                     else item.barter_expect)
    if trade_type == E.TradeType.BARTER and len(barter_expect) < 2:
        raise ApiError(ERR_PARAM, "互换必须填写期望交换的物品描述（BR-13）", 400)

    condition = payload.condition or item.condition
    if condition not in ITEM_CONDITIONS:
        raise ApiError(ERR_PARAM, "请选择完整的成色档位（五档）", 400)

    quality_desc = (payload.qualityDesc.strip() if payload.qualityDesc is not None
                    else item.quality_desc)
    if payload.qualityDesc is not None and len(quality_desc) < 20:
        raise ApiError(ERR_PARAM, "质量说明至少 20 个字（M03-01）", 400)

    category_id = item.category_id
    if payload.categoryId is not None:
        category = await db.get(ItemCategory, payload.categoryId)
        if not category:
            raise ApiError(ERR_PARAM, "物品类目不存在", 400)
        category_id = category.id

    before = {
        "title": item.title, "tradeType": item.trade_type,
        "priceCents": item.price_cents, "condition": item.condition,
        "categoryId": item.category_id,
    }
    item.title = title
    if payload.description is not None:
        item.description = payload.description.strip()[:2000]
    item.quality_desc = quality_desc
    item.category_id = category_id
    item.trade_type = trade_type
    item.price_cents = price_cents
    item.condition = condition
    item.barter_expect = barter_expect

    await write_audit(db, request, actor=admin, action="item.update",
                      resource_type="item", resource_id=item.id,
                      before=before,
                      after={"title": item.title, "tradeType": item.trade_type,
                             "priceCents": item.price_cents,
                             "condition": item.condition,
                             "categoryId": item.category_id})
    await db.commit()
    return ok(await _row(db, item), "物品已更新")


@router.delete("/items/{item_id}",
               dependencies=[Depends(require_permission("community:item:delete"))])
async def delete_item(item_id: int, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    """删除物品：已有订单记录时拒绝（资金/履约凭证必须保留），请改用下架。"""
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在", 404)
    if item.status in (E.ItemStatus.RESERVED, E.ItemStatus.SOLD, E.ItemStatus.GIFTED):
        raise ApiError(ERR_BIZ_RULE, "交易中或已成交的物品不能删除，请使用下架", 422)
    order_count = int((await db.scalar(
        select(func.count()).select_from(Order).where(Order.item_id == item.id))) or 0)
    if order_count:
        raise ApiError(ERR_CONFLICT, "该物品已有订单记录，不能删除；请使用下架", 409)
    before = await _row(db, item)
    await db.execute(delete(ItemMedia).where(ItemMedia.item_id == item.id))
    await db.execute(delete(ItemAudit).where(ItemAudit.item_id == item.id))
    await db.execute(delete(ItemComment).where(ItemComment.item_id == item.id))
    await db.execute(delete(ViewHistory).where(ViewHistory.item_id == item.id))
    await db.execute(delete(Favorite).where(
        Favorite.target_type == "ITEM", Favorite.target_id == item.id))
    # 会话保留聊天记录，仅解除已删除物品的引用
    await db.execute(update(Conversation).where(Conversation.item_id == item.id)
                     .values(item_id=None))
    await db.delete(item)
    await write_audit(db, request, actor=admin, action="item.delete",
                      resource_type="item", resource_id=item_id,
                      before=before, after=None)
    await db.commit()
    return ok({"id": str(item_id)}, "物品已删除")


@router.get("/items/{item_id}/ai-audit")
async def item_ai_audit(item_id: int, admin: CurrentAdmin, db: DbSession):
    """AI 报告（W03-01/A-05）：总体结论、置信度、四维得分、问题与建议、traceId。"""
    audit = await db.scalar(
        select(ItemAudit).where(ItemAudit.item_id == item_id)
        .order_by(ItemAudit.id.desc()).limit(1))
    if not audit:
        raise ApiError(ERR_NOT_FOUND, "暂无质检记录", 404)
    return ok(await _audit_row(audit))


@router.post("/items/{item_id}/review", dependencies=[ItemReviewPerm])
async def review_item(item_id: int, payload: ReviewIn, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    """人工复核（W03-01/BR-04）：通过（可加热门推荐）/驳回（原因必填）/降级。
    AI 质检为上架必要非充分条件（SRS 11.1）；复核结论回流作为标注样本（A-10）。"""
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在", 404)
    if payload.decision not in ("APPROVE", "REJECT", "DOWNGRADE"):
        raise ApiError(ERR_PARAM, "decision 必须为 APPROVE / REJECT / DOWNGRADE", 400)
    if payload.decision == "REJECT" and len(payload.reason.strip()) < 5:
        raise ApiError(ERR_PARAM, "驳回原因必填（不少于 5 个字）", 400)

    idem = await guard_idempotency(db, request, {"id": item_id, **payload.model_dump()})
    if idem and idem.status == "COMPLETED":
        return ok(idem.response_json["data"])

    before = {"status": item.status, "recommended": item.recommended}
    now = utcnow()
    if payload.decision == "APPROVE":
        item.status = item_sm.fire(item.status, E.ItemStatus.ON_SALE)
        item.published_at = now
        item.expires_at = now + timedelta(days=settings.item_expire_days)
        item.recommended = payload.recommend
        notice_title = "物品复核通过，已上架"
    elif payload.decision == "DOWNGRADE":
        item.status = item_sm.fire(item.status, E.ItemStatus.ON_SALE)
        item.published_at = item.published_at or now
        item.expires_at = item.expires_at or now + timedelta(days=settings.item_expire_days)
        item.recommended = False
        notice_title = "物品已降级上架（不进入推荐位）"
    else:
        item.status = item_sm.fire(item.status, E.ItemStatus.REJECTED)
        item.reject_reason = payload.reason.strip()
        notice_title = "物品复核未通过"

    # 复核结论写入最新质检记录（A-10 标注样本回流）
    latest = await db.scalar(
        select(ItemAudit).where(ItemAudit.item_id == item.id)
        .order_by(ItemAudit.id.desc()).limit(1))
    if latest:
        latest.decision = payload.decision
        latest.reviewer_id = admin.id
        latest.review_note = payload.reason

    await notify_user(
        db, item.seller_id, category="TRADE", title=notice_title,
        description=payload.reason if payload.decision == "REJECT" else f"物品「{item.title}」",
        icon="package", tag="审核", route={"type": "item", "id": str(item.id)},
    )
    await write_audit(
        db, request, actor=admin, action="item.review",
        resource_type="item", resource_id=item.id, before=before,
        after={"status": item.status, "decision": payload.decision,
               "recommend": item.recommended, "reason": payload.reason},
    )
    await write_outbox(db, event_type="ItemReviewed", aggregate_type="item",
                       aggregate_id=item.id,
                       payload={"decision": payload.decision, "status": item.status})
    data = await _row(db, item)
    await complete_idempotency(db, idem, data)
    await db.commit()
    return ok(data, "复核完成")


@router.post("/items/{item_id}/recommend",
             dependencies=[Depends(require_permission("community:item:recommend"))])
async def recommend_item(item_id: int, payload: RecommendIn, request: Request,
                         admin: CurrentAdmin, db: DbSession):
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在", 404)
    before = {"recommended": item.recommended}
    item.recommended = payload.enabled
    await write_audit(db, request, actor=admin, action="item.recommend",
                      resource_type="item", resource_id=item.id,
                      before=before, after={"recommended": item.recommended})
    await db.commit()
    return ok(await _row(db, item), "推荐位已更新")


@router.post("/items/{item_id}/offline",
             dependencies=[Depends(require_permission("community:item:offline"))])
async def offline_item(item_id: int, payload: OfflineIn, request: Request,
                       admin: CurrentAdmin, db: DbSession):
    """违规下架：必填原因（巡检/举报处理入口，W03-03/W03-04）。"""
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在", 404)
    reason = payload.reason.strip()
    if len(reason) < 2:
        raise ApiError(ERR_PARAM, "下架原因必填（将通知卖家）", 400)
    before = {"status": item.status}
    item.status = item_sm.fire(item.status, E.ItemStatus.OFF_SHELF)
    item.reject_reason = reason
    await notify_user(db, item.seller_id, category="TRADE", title="物品已被平台下架",
                      description=reason, icon="alert", tag="违规",
                      route={"type": "item", "id": str(item.id)})
    await write_audit(db, request, actor=admin, action="item.offline",
                      resource_type="item", resource_id=item.id,
                      before=before, after={"status": item.status, "reason": reason})
    await db.commit()
    return ok(await _row(db, item), "物品已下架")


@router.post("/items/batch-offline",
             dependencies=[Depends(require_permission("community:item:offline"))])
async def batch_offline_items(payload: BatchOfflineIn, request: Request,
                              admin: CurrentAdmin, db: DbSession):
    """巡检批量下架（W03-03）：逐条处理，返回成功/失败明细。"""
    if len(payload.reason.strip()) < 2:
        raise ApiError(ERR_PARAM, "批量下架原因必填", 400)
    successes: list[str] = []
    failures: list[dict] = []
    for item_id in payload.ids[:50]:
        item = await db.get(Item, item_id)
        if not item:
            failures.append({"id": str(item_id), "reason": "物品不存在"})
            continue
        try:
            item.status = item_sm.fire(item.status, E.ItemStatus.OFF_SHELF)
            item.reject_reason = payload.reason.strip()
            await notify_user(db, item.seller_id, category="TRADE",
                              title="物品已被平台下架", description=payload.reason.strip(),
                              icon="alert", tag="违规",
                              route={"type": "item", "id": str(item.id)})
            successes.append(str(item_id))
        except ApiError as exc:
            failures.append({"id": str(item_id), "reason": exc.message})
    await write_audit(db, request, actor=admin, action="item.batch-offline",
                      resource_type="item", resource_id=",".join(successes),
                      before=None, after={"success": len(successes),
                                          "failed": len(failures),
                                          "reason": payload.reason.strip()})
    await db.commit()
    return ok({"success": len(successes), "failed": len(failures), "failures": failures},
              f"成功下架 {len(successes)} 件，失败 {len(failures)} 件")


# ---------------------------------------------------------------- 类目管理（W04-03）

@router.get("/item-categories")
async def list_item_categories(admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(ItemCategory).order_by(ItemCategory.sort, ItemCategory.id))).scalars().all())
    nodes: dict[int, dict] = {}
    roots: list[dict] = []
    for row in rows:
        nodes[row.id] = {"id": str(row.id), "name": row.name, "icon": row.icon,
                         "sort": row.sort, "status": row.status, "children": []}
    for row in rows:
        node = nodes[row.id]
        if row.parent_id and row.parent_id in nodes:
            nodes[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok(roots)


@router.post("/item-categories",
             dependencies=[Depends(require_permission("community:item:category"))])
async def create_item_category(payload: CategoryIn, request: Request,
                               admin: CurrentAdmin, db: DbSession):
    name = payload.name.strip()
    if not name:
        raise ApiError(ERR_PARAM, "类目名称必填", 400)
    if await db.scalar(select(ItemCategory.id).where(ItemCategory.name == name)):
        raise ApiError(40901, "类目名称已存在", 409)
    category = ItemCategory(name=name, parent_id=payload.parentId,
                            icon=payload.icon, sort=payload.sort)
    db.add(category)
    await db.flush()
    await write_audit(db, request, actor=admin, action="item-category.create",
                      resource_type="item_category", resource_id=category.id,
                      before=None, after={"name": name})
    await db.commit()
    return ok({"id": str(category.id), "name": name}, "类目已创建")


@router.put("/item-categories/{category_id}",
            dependencies=[Depends(require_permission("community:item:category"))])
async def update_item_category(category_id: int, payload: CategoryIn, request: Request,
                               admin: CurrentAdmin, db: DbSession):
    category = await db.get(ItemCategory, category_id)
    if not category:
        raise ApiError(ERR_NOT_FOUND, "类目不存在", 404)
    before = {"name": category.name, "icon": category.icon, "sort": category.sort,
              "status": category.status}
    category.name = payload.name.strip() or category.name
    category.icon = payload.icon or category.icon
    category.sort = payload.sort
    await write_audit(db, request, actor=admin, action="item-category.update",
                      resource_type="item_category", resource_id=category.id,
                      before=before, after={"name": category.name})
    await db.commit()
    return ok({"id": str(category.id), "name": category.name}, "类目已更新")
