from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import delete, select

from src.api.utils import paginate
from src.core.config import settings
from src.core.deps import CurrentUser, DbSession, OptionalUser
from src.core.responses import ERR_BIZ_RULE, ERR_PARAM, ApiError, ok, paginated
from src.db.models import Favorite, Item, ItemAudit, ItemCategory, ItemComment, ItemMedia, User
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import item_sm
from src.services import ai_audit_service as ai
from src.services import item_service as svc
from src.services.notify_service import notify_user

router = APIRouter(tags=["c:items"])


class CreateItemIn(BaseModel):
    title: str
    tradeType: str = E.TradeType.MONETARY
    priceCents: int = 0
    barterExpect: str = ""
    condition: str = "轻微使用痕迹"
    category: str = ""
    qualityDesc: str = ""
    description: str = ""
    images: list[str] = []
    videoUrl: str = ""
    invoices: list[str] = []
    expectTime: str = ""
    communityId: int | None = None


class CommentIn(BaseModel):
    content: str
    parentId: int | None = None


# ---------------------------------------------------------------- 列表与详情

@router.get("/items")
async def list_items(
    user: OptionalUser, db: DbSession,
    zone: str | None = Query(default=None),
    type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    communityId: int | None = Query(default=None),
    near: bool = Query(default=False),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    """物品信息流（M02）：本小区默认；near=true 看邻近；zone 对应四专属区。"""
    from src.services.auth_service import bound_resident

    viewer_community_id = None
    if user:
        resident = await bound_resident(db, user.id)
        viewer_community_id = resident.community_id if resident else None

    class _Q:
        pass

    q = _Q()
    q.zone, q.type, q.category, q.keyword, q.communityId, q.near = (
        zone, type, category, keyword, communityId, near)
    conditions = svc.build_list_query(viewer_community_id, q)

    stmt = select(Item).outerjoin(ItemCategory, Item.category_id == ItemCategory.id)
    for condition in conditions:
        stmt = stmt.where(condition)
    if sort == "price":
        stmt = stmt.order_by(Item.price_cents)
    else:
        stmt = stmt.order_by(Item.published_at.desc().nullslast(), Item.id.desc())

    rows, total = await paginate(db, stmt, page, pageSize)
    return paginated([await svc.serialize_item(db, item, user) for item in rows],
                     page, pageSize, total)


@router.get("/items/mine")
async def my_items(user: CurrentUser, db: DbSession,
                   page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(Item).where(Item.seller_id == user.id).order_by(Item.id.desc())
    rows, total = await paginate(db, stmt, page, pageSize)
    return paginated([await svc.serialize_item(db, item, user) for item in rows],
                     page, pageSize, total)


@router.post("/items")
async def create_item(payload: CreateItemIn, user: CurrentUser, db: DbSession):
    """发布物品（M03-01）：本小区强绑定（BR-02）；创建为草稿，需提交 AI 质检。"""
    resident = await svc.assert_can_publish(db, user)
    if payload.communityId and payload.communityId != resident.community_id:
        raise ApiError(ERR_BIZ_RULE, "只能发布到本小区商店（BR-02）", 422)
    categories = await svc.category_names(db)
    svc.validate_draft(categories, payload)

    category_id = None
    if payload.category:
        category_id = await db.scalar(
            select(ItemCategory.id).where(ItemCategory.name == payload.category))

    item = Item(
        community_id=resident.community_id,
        seller_id=user.id,
        category_id=category_id,
        title=payload.title.strip(),
        description=payload.description or payload.qualityDesc,
        quality_desc=payload.qualityDesc,
        trade_type=payload.tradeType,
        price_cents=payload.priceCents if payload.tradeType == E.TradeType.MONETARY else 0,
        condition=payload.condition,
        barter_expect=payload.barterExpect,
        expect_time=payload.expectTime,
        status=E.ItemStatus.DRAFT,
        stats={"views": 0, "favorites": 0, "comments": 0},
    )
    db.add(item)
    await db.flush()
    for media in svc.replace_media(item.id, payload):
        db.add(media)
    await db.commit()
    return ok({"id": str(item.id), "status": item.status}, "草稿已保存，请提交 AI 质检")


@router.get("/items/{item_id}")
async def item_detail(item_id: int, user: OptionalUser, db: DbSession):
    item = await svc.get_item_or_404(db, item_id)
    is_owner = bool(user and user.id == item.seller_id)
    # 非上架物品仅卖家可见（审核中/被驳回/下架）
    if item.status not in (E.ItemStatus.ON_SALE, E.ItemStatus.RESERVED, E.ItemStatus.SOLD,
                           E.ItemStatus.GIFTED) and not is_owner:
        raise ApiError(40401, "物品不存在或已下架", 404)
    if not is_owner:
        stats = dict(item.stats or {})
        stats["views"] = stats.get("views", 0) + 1
        item.stats = stats
        await db.commit()
    return ok(await svc.serialize_item(db, item, user, detail=True))


@router.put("/items/{item_id}")
async def update_item(item_id: int, payload: CreateItemIn, user: CurrentUser, db: DbSession):
    """编辑（M03-08）：仅草稿/被驳回可编辑；修改后回到草稿，需重新质检。"""
    item = await svc.get_item_or_404(db, item_id)
    svc.assert_owner(item, user)
    if item.status not in (E.ItemStatus.DRAFT, E.ItemStatus.AI_REJECTED, E.ItemStatus.REJECTED):
        raise ApiError(ERR_BIZ_RULE, "当前状态不可编辑，请先下架或等待审核完成", 422)
    categories = await svc.category_names(db)
    svc.validate_draft(categories, payload)

    if item.status != E.ItemStatus.DRAFT:
        item.status = item_sm.fire(item.status, E.ItemStatus.DRAFT)
    item.title = payload.title.strip()
    item.description = payload.description or payload.qualityDesc
    item.quality_desc = payload.qualityDesc
    item.trade_type = payload.tradeType
    item.price_cents = payload.priceCents if payload.tradeType == E.TradeType.MONETARY else 0
    item.condition = payload.condition
    item.barter_expect = payload.barterExpect
    item.expect_time = payload.expectTime
    item.reject_reason = ""
    if payload.category:
        item.category_id = await db.scalar(
            select(ItemCategory.id).where(ItemCategory.name == payload.category))

    await db.execute(delete(ItemMedia).where(ItemMedia.item_id == item.id))
    for media in svc.replace_media(item.id, payload):
        db.add(media)
    await db.commit()
    return ok(await svc.serialize_item(db, item, user, detail=True), "已保存，请重新提交质检")


@router.post("/items/{item_id}/submit")
async def submit_item(item_id: int, user: CurrentUser, db: DbSession):
    """提交 AI 质检（M03-04/BR-04）：Mock 流水线同步出结果（≤60s 约束 NF-04）。
    PASS + 高置信 → 快车道直接上架（阈值可配，W03-01）；PASS/转人工 → 人工复核队列；
    FAIL → 驳回并给出可执行改进建议（A-08）。"""
    item = await svc.get_item_or_404(db, item_id)
    svc.assert_owner(item, user)
    item.status = item_sm.fire(item.status, E.ItemStatus.AUDITING)

    media = await svc.media_of(db, item.id)
    report = await ai.get_provider().audit(item, media)
    audit = ItemAudit(
        item_id=item.id,
        overall=report["overall"],
        confidence=report["confidence"],
        dimensions=report["dimensions"],
        risks=report["risks"],
        suggestions=report["suggestions"],
        trace_id=report["trace_id"],
        model_version=report["model_version"],
    )
    db.add(audit)
    await db.flush()

    now = utcnow()
    if report["overall"] == ai.AiDecision.PASS:
        if report["confidence"] >= settings.ai_fast_track_confidence:
            item.status = item_sm.fire(item.status, E.ItemStatus.ON_SALE)
            item.published_at = now
            item.expires_at = now + timedelta(days=settings.item_expire_days)
            notice = "AI 质检通过（高置信快车道），物品已上架"
        else:
            item.status = item_sm.fire(item.status, E.ItemStatus.PENDING_REVIEW)
            notice = "AI 质检通过，已进入人工复核"
        await notify_user(db, user.id, category="TRADE", title=notice,
                          description=f"物品「{item.title}」", icon="sparkles", tag="质检",
                          route={"type": "item", "id": str(item.id)})
    elif report["overall"] == ai.AiDecision.NEED_HUMAN_REVIEW:
        item.status = item_sm.fire(item.status, E.ItemStatus.PENDING_REVIEW)
        await notify_user(db, user.id, category="TRADE", title="质检完成，需人工复核",
                          description=f"物品「{item.title}」已转人工复核队列",
                          icon="shield", tag="质检", route={"type": "item", "id": str(item.id)})
    else:
        item.status = item_sm.fire(item.status, E.ItemStatus.AI_REJECTED)
        reasons = "；".join(report["suggestions"][:3])
        item.reject_reason = reasons
        await notify_user(db, user.id, category="TRADE", title="AI 质检未通过",
                          description=reasons, icon="alert", tag="质检",
                          route={"type": "item", "id": str(item.id)})

    from src.core.audit import write_outbox

    await write_outbox(db, event_type="ItemAudited", aggregate_type="item",
                       aggregate_id=item.id,
                       payload={"overall": report["overall"], "traceId": report["trace_id"],
                                "status": item.status})
    await db.commit()
    return ok({"auditId": str(audit.id), "status": item.status})


@router.get("/items/{item_id}/audit-progress")
async def audit_progress(item_id: int, user: CurrentUser, db: DbSession):
    """质检进度与报告（M03-05）：驳回展示具体原因与改进建议，支持一键返回修改。"""
    item = await svc.get_item_or_404(db, item_id)
    svc.assert_owner(item, user)
    audit = await db.scalar(
        select(ItemAudit).where(ItemAudit.item_id == item.id)
        .order_by(ItemAudit.id.desc()).limit(1))
    if audit is None:
        progress = ai.build_progress(item, None)
    else:
        report = {
            "overall": audit.overall,
            "confidence": float(audit.confidence or 0),
            "dimensions": audit.dimensions or [],
            "risks": audit.risks or [],
            "suggestions": audit.suggestions or [],
            "trace_id": audit.trace_id,
        }
        progress = ai.build_progress(item, report)
        if progress.get("report"):
            progress["report"]["checkedAt"] = (
                int(audit.created_at.timestamp() * 1000) if audit.created_at else 0)
    return ok(progress)


@router.post("/items/{item_id}/renew")
async def renew_item(item_id: int, user: CurrentUser, db: DbSession):
    """续期（BR-07）：到期物品重新上架 30 天（可配置）。"""
    item = await svc.get_item_or_404(db, item_id)
    svc.assert_owner(item, user)
    if item.status not in (E.ItemStatus.EXPIRED, E.ItemStatus.ON_SALE):
        raise ApiError(ERR_BIZ_RULE, "仅上架中或已到期物品可续期", 422)
    if item.status == E.ItemStatus.EXPIRED:
        item.status = item_sm.fire(item.status, E.ItemStatus.ON_SALE)
    item.expires_at = utcnow() + timedelta(days=settings.item_expire_days)
    await db.commit()
    return ok({"success": True, "expiresAt": int(item.expires_at.timestamp() * 1000)},
              "已续期 30 天")


@router.post("/items/{item_id}/off-shelf")
async def off_shelf_item(item_id: int, user: CurrentUser, db: DbSession):
    item = await svc.get_item_or_404(db, item_id)
    svc.assert_owner(item, user)
    if item.status == E.ItemStatus.RESERVED:
        raise ApiError(ERR_BIZ_RULE, "物品存在进行中的预约订单，请先完成或取消订单", 422)
    item.status = item_sm.fire(item.status, E.ItemStatus.OFF_SHELF)
    await db.commit()
    return ok({"success": True}, "已下架")


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, user: CurrentUser, db: DbSession):
    item = await svc.get_item_or_404(db, item_id)
    svc.assert_owner(item, user)
    if item.status in (E.ItemStatus.ON_SALE, E.ItemStatus.RESERVED):
        raise ApiError(ERR_BIZ_RULE, "上架中或交易中的物品请先下架再删除", 422)
    await db.execute(delete(ItemMedia).where(ItemMedia.item_id == item.id))
    await db.execute(delete(ItemComment).where(ItemComment.item_id == item.id))
    await db.execute(delete(ItemAudit).where(ItemAudit.item_id == item.id))
    await db.delete(item)
    await db.commit()
    return ok({"success": True}, "已删除")


# ---------------------------------------------------------------- 留言（M05-01/BR-14/A-09）

@router.get("/items/{item_id}/comments")
async def item_comments(item_id: int, user: OptionalUser, db: DbSession):
    rows = list((await db.execute(
        select(ItemComment).where(ItemComment.item_id == item_id,
                                  ItemComment.status == "PUBLISHED")
        .order_by(ItemComment.id.desc()).limit(100)
    )).scalars().all())
    result = []
    for row in rows:
        author = await db.get(User, row.user_id)
        result.append({
            "id": str(row.id),
            "author": author.nickname if author else "",
            "avatar": (author.avatar_key if author else "") or "avatar-person-1",
            "time": svc._time_ago(row.created_at),
            "content": row.content,
            "replyTo": str(row.parent_id) if row.parent_id else None,
        })
    return ok(result)


@router.post("/items/{item_id}/comments")
async def add_item_comment(item_id: int, payload: CommentIn, user: CurrentUser, db: DbSession):
    """留言需过内容安全审核（A-09 兜底；命中违禁词直接拦截并告警）。"""
    item = await svc.get_item_or_404(db, item_id)
    content = payload.content.strip()
    if not (1 <= len(content) <= 200):
        raise ApiError(ERR_PARAM, "留言需 1–200 个字", 400)
    hit = next((kw for kw in ai.BANNED_KEYWORDS if kw in content), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"留言包含违禁内容（{hit}），已被内容安全审核拦截", 422)
    comment = ItemComment(item_id=item.id, user_id=user.id, parent_id=payload.parentId,
                          content=content, status="PUBLISHED")
    db.add(comment)
    stats = dict(item.stats or {})
    stats["comments"] = stats.get("comments", 0) + 1
    item.stats = stats
    await db.commit()
    return ok({"id": str(comment.id), "author": user.nickname, "content": content,
               "time": "刚刚"})


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: int, user: CurrentUser, db: DbSession):
    comment = await db.get(ItemComment, comment_id)
    if not comment:
        raise ApiError(40401, "留言不存在", 404)
    item = await svc.get_item_or_404(db, comment.item_id)
    if comment.user_id != user.id and item.seller_id != user.id:
        raise ApiError(40301, "仅留言者或卖家可删除", 403)
    comment.status = "DELETED"
    await db.commit()
    return ok({"success": True})


# ---------------------------------------------------------------- 收藏与距离

@router.post("/items/{item_id}/favorite")
async def toggle_item_favorite(item_id: int, user: CurrentUser, db: DbSession):
    item = await svc.get_item_or_404(db, item_id)
    existing = await db.scalar(select(Favorite).where(
        Favorite.user_id == user.id, Favorite.target_type == "ITEM",
        Favorite.target_id == item.id))
    stats = dict(item.stats or {})
    if existing:
        await db.delete(existing)
        stats["favorites"] = max(0, stats.get("favorites", 0) - 1)
        favorite = False
    else:
        db.add(Favorite(user_id=user.id, target_type="ITEM", target_id=item.id))
        stats["favorites"] = stats.get("favorites", 0) + 1
        favorite = True
    item.stats = stats
    await db.commit()
    return ok({"favorite": favorite})


@router.get("/items/{item_id}/distance")
async def item_distance(item_id: int, user: CurrentUser, db: DbSession):
    """距离与耗时（M04-02/SRS 8.2）：直线距离 + 步行/骑行/驾车预估（降级标注「预估」）。"""
    item = await svc.get_item_or_404(db, item_id)
    from src.db.models import Community
    from src.services.auth_service import bound_resident

    resident = await bound_resident(db, user.id)
    if not resident:
        raise ApiError(40302, "请先完成小区认证", 403)
    viewer_community = await db.get(Community, resident.community_id)
    item_community = await db.get(Community, item.community_id)
    km = svc._distance_km(viewer_community.longitude if viewer_community else None,
                          viewer_community.latitude if viewer_community else None,
                          item_community.longitude if item_community else None,
                          item_community.latitude if item_community else None)
    return ok({
        "distance": svc._distance_label(km),
        "walk": f"步行{svc._duration_label(km, 4.8)}",
        "bike": f"骑行{svc._duration_label(km, 12)}",
        "car": f"驾车{svc._duration_label(km, 30)}",
        "meters": int(km * 1000) if km is not None else 0,
        "estimated": True,
    })
