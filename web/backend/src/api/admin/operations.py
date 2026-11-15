from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.api.utils import paginate
from src.core.audit import write_audit, write_outbox
from src.core.config import settings
from src.core.deps import CurrentAdmin, DbSession
from src.core.idempotency import complete_idempotency, guard_idempotency
from src.core.permissions import require_permission
from src.core.responses import (
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.db.models import Community, Item, ItemAudit, ItemCategory, ItemMedia, User
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import item_sm
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
        "seller": seller.nickname if seller else "",
        "sellerId": str(item.seller_id),
        "category": category.name if category else "",
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
        {"objectKey": m.object_key, "mediaType": m.media_type, "sort": m.sort} for m in media
    ]
    audits = list((await db.execute(
        select(ItemAudit).where(ItemAudit.item_id == item.id)
        .order_by(ItemAudit.id.desc()))).scalars().all())
    row["audits"] = [await _audit_row(audit) for audit in audits]
    row["barterExpect"] = item.barter_expect
    row["qualityDesc"] = item.quality_desc
    return ok(row)


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
