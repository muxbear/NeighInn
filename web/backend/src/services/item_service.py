"""物品域服务层（M02–M04）：发布校验、序列化、归属守卫、距离计算。

硬规则：
- BR-02 本小区强绑定：发布者必须持有已认证的小区档案；
- BR-05 照片 3–12 张（参数可调）；BR-06 三种交易方式；BR-13 互换必填期望交换描述；
- M03-01 质量说明 ≥20 字；W07 处置联动：限制发布/封禁用户禁止发布。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.responses import (
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_NOT_VERIFIED,
    ERR_PARAM,
    ApiError,
)
from src.db.models import (
    Community,
    Favorite,
    Item,
    ItemAudit,
    ItemCategory,
    ItemMedia,
    Order,
    Resident,
    User,
    UserPenalty,
)
from src.domain import enums as E
from src.services.auth_service import bound_resident

TRADE_LABEL = {E.TradeType.MONETARY: "出售", E.TradeType.FREE_GIFT: "免费", E.TradeType.BARTER: "互换"}
ZONE_TRADE = {"sale": E.TradeType.MONETARY, "gift": E.TradeType.FREE_GIFT, "swap": E.TradeType.BARTER}


def _time_ago(dt: datetime | None) -> str:
    if not dt:
        return ""
    delta = datetime.now(UTC).replace(tzinfo=None) - dt.replace(tzinfo=None)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    return f"{hours // 24}天前"


def _distance_km(a_lng, a_lat, b_lng, b_lat) -> float | None:
    if None in (a_lng, a_lat, b_lng, b_lat):
        return None
    import math

    radius = 6371.0
    d_lat = math.radians(b_lat - a_lat)
    d_lng = math.radians(b_lng - a_lng)
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(d_lng / 2) ** 2)
    return radius * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _distance_label(km: float | None) -> str:
    if km is None:
        return ""
    meters = int(round(km * 1000, -1))
    return f"约{meters}m" if meters < 1000 else f"约{km:.1f}km"


def _duration_label(km: float | None, speed_kmh: float) -> str:
    if km is None:
        return ""
    minutes = max(1, round(km / speed_kmh * 60))
    return f"约{minutes}分钟"


async def get_item_or_404(db: AsyncSession, item_id: int) -> Item:
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在", 404)
    return item


def assert_owner(item: Item, user: User) -> None:
    if item.seller_id != user.id:
        raise ApiError(ERR_FORBIDDEN, "只能操作自己发布的物品", 403)


async def assert_can_publish(db: AsyncSession, user: User) -> Resident:
    """发布前置守卫（BR-02 + W07 处置联动）。返回已认证的业主档案。"""
    resident = await bound_resident(db, user.id)
    if not resident:
        raise ApiError(ERR_NOT_VERIFIED, "请先完成实名与业主认证后再发布物品", 403)
    penalty = await db.scalar(
        select(UserPenalty).where(
            UserPenalty.user_id == user.id,
            UserPenalty.status == "ACTIVE",
            UserPenalty.type.in_([E.PenaltyType.PUBLISH_LIMIT, E.PenaltyType.BAN]),
        ).limit(1))
    if penalty:
        raise ApiError(ERR_FORBIDDEN, f"账号处于{penalty.type}处置期，暂不能发布物品", 403)
    return resident


async def media_of(db: AsyncSession, item_id: int) -> list[ItemMedia]:
    return list((await db.execute(
        select(ItemMedia).where(ItemMedia.item_id == item_id).order_by(ItemMedia.sort, ItemMedia.id)
    )).scalars().all())


def validate_draft(db_categories: set[str], payload) -> None:
    """发布校验（M03-01/BR-05/BR-06/BR-13）。payload 为 CreateItemIn。"""
    title = payload.title.strip()
    if not (2 <= len(title) <= 30):
        raise ApiError(ERR_PARAM, "标题需 2–30 个字", 400)
    if payload.tradeType not in E.TradeType.ALL:
        raise ApiError(ERR_PARAM, "交易方式不合法", 400)
    if payload.tradeType == E.TradeType.MONETARY and payload.priceCents <= 0:
        raise ApiError(ERR_PARAM, "货币交易必须填写价格", 400)
    if payload.tradeType == E.TradeType.FREE_GIFT and payload.priceCents != 0:
        raise ApiError(ERR_PARAM, "免费赠与价格必须为 0（BR-12）", 400)
    if payload.tradeType == E.TradeType.BARTER and len(payload.barterExpect.strip()) < 2:
        raise ApiError(ERR_PARAM, "互换必须填写期望交换的物品描述（BR-13）", 400)
    if len(payload.qualityDesc.strip()) < 20:
        raise ApiError(ERR_PARAM, "质量说明至少 20 个字（M03-01）", 400)
    if payload.condition not in ("全新", "九九新", "轻微使用痕迹", "明显使用痕迹", "有功能缺陷"):
        raise ApiError(ERR_PARAM, "请选择完整的成色档位（五档）", 400)
    if payload.category and payload.category not in db_categories:
        raise ApiError(ERR_PARAM, "物品类目不存在", 400)
    photos = len(payload.images)
    if not (settings.min_item_images <= photos <= settings.max_item_images):
        raise ApiError(
            ERR_PARAM,
            f"照片需 {settings.min_item_images}–{settings.max_item_images} 张（含整体、细节、缺陷处，BR-05）",
            400,
        )


async def category_names(db: AsyncSession) -> set[str]:
    rows = await db.execute(select(ItemCategory.name).where(ItemCategory.status == "启用"))
    return set(rows.scalars().all())


def replace_media(item_id: int, payload) -> list[ItemMedia]:
    """把上传对象键落成媒体行：IMAGE 默认；videoUrl → VIDEO；invoices → INVOICE。"""
    rows: list[ItemMedia] = [
        ItemMedia(item_id=item_id, object_key=key, media_type="IMAGE", sort=index)
        for index, key in enumerate(payload.images)
    ]
    if payload.videoUrl:
        rows.append(ItemMedia(item_id=item_id, object_key=payload.videoUrl,
                              media_type="VIDEO", sort=len(rows)))
    for key in payload.invoices:
        rows.append(ItemMedia(item_id=item_id, object_key=key,
                              media_type="INVOICE", sort=len(rows)))
    return rows


async def _seller_summary(db: AsyncSession, item: Item) -> dict:
    seller = await db.get(User, item.seller_id)
    resident = await bound_resident(db, item.seller_id)
    community = await db.get(Community, item.community_id)
    deal_count = 0
    if seller:
        deal_count = int((await db.scalar(
            select(func.count()).select_from(Order)
            .where(Order.seller_id == seller.id, Order.status == "COMPLETED")
        )) or 0)
    joined_days = 0
    if seller and seller.registered_at:
        joined_days = max(0, (datetime.now(UTC).replace(tzinfo=None)
                              - seller.registered_at.replace(tzinfo=None)).days)
    credit = seller.credit_score if seller else 100
    return {
        "id": str(item.seller_id),
        "name": seller.nickname if seller else "",
        "avatar": (seller.avatar_key if seller else "") or "avatar-person-1",
        "credit": "信用极好" if credit >= 90 else "信用良好" if credit >= 70 else "信用一般",
        "dealCount": deal_count,
        "area": f"{community.name if community else ''} · {resident.building}" if resident and resident.building else (community.name if community else ""),
        "verified": bool(resident),
        "joinedDays": joined_days,
        "level": min(9, max(1, credit // 12)),
    }


async def serialize_item(
    db: AsyncSession, item: Item, viewer: User | None = None, *, detail: bool = False
) -> dict:
    """移动端 Item（mobile/models/item.model.ts）。含距离与步行耗时（SRS 8.2）。"""
    media = await media_of(db, item.id)
    images = [m.object_key for m in media if m.media_type == "IMAGE"]
    community = await db.get(Community, item.community_id)

    km = None
    if viewer:
        viewer_resident = await bound_resident(db, viewer.id)
        if viewer_resident:
            viewer_community = await db.get(Community, viewer_resident.community_id)
            if viewer_community and community:
                km = _distance_km(viewer_community.longitude, viewer_community.latitude,
                                  community.longitude, community.latitude)

    favorite = False
    if viewer:
        favorite = bool(await db.scalar(
            select(Favorite.id).where(Favorite.user_id == viewer.id,
                                      Favorite.target_type == "ITEM",
                                      Favorite.target_id == item.id).limit(1)))

    stats = item.stats or {}
    latest_audit = await db.scalar(
        select(ItemAudit.id).where(ItemAudit.item_id == item.id).limit(1))

    data = {
        "id": str(item.id),
        "title": item.title,
        "price": item.price_cents / 100 if item.trade_type == E.TradeType.MONETARY else 0,
        "type": TRADE_LABEL[item.trade_type],
        "tradeTypeCode": item.trade_type,
        "condition": item.condition,
        "distance": _distance_label(km),
        "walk": f"步行{_duration_label(km, 4.8)}" if km is not None else "",
        "time": _time_ago(item.published_at or item.created_at),
        "image": images[0] if images else "",
        "images": images,
        "community": community.name if community else "",
        "barterExpect": item.barter_expect,
        "description": item.quality_desc or item.description,
        "status": item.status,
        "favorite": favorite,
        "category": await _category_name(db, item.category_id),
        "createdAt": int((item.created_at or datetime.now(UTC)).timestamp() * 1000),
        "viewCount": stats.get("views", 0),
        "commentCount": stats.get("comments", 0),
        "aiVerified": bool(latest_audit),
    }
    if detail:
        data["gallery"] = images
        data["seller"] = await _seller_summary(db, item)
        data["rejectReason"] = item.reject_reason
        data["expiresAt"] = int(item.expires_at.timestamp() * 1000) if item.expires_at else 0
    return data


async def _category_name(db: AsyncSession, category_id: int | None) -> str:
    if not category_id:
        return ""
    category = await db.get(ItemCategory, category_id)
    return category.name if category else ""


def build_list_query(viewer_resident_community_id: int | None, query) -> list:
    """列表筛选条件（M02：本小区 / 附近 / 专属区 / 类目 / 关键词 / 排序）。"""
    conditions = [Item.status == E.ItemStatus.ON_SALE]
    if query.zone and query.zone in ZONE_TRADE:
        conditions.append(Item.trade_type == ZONE_TRADE[query.zone])
    if query.type and query.type in E.TradeType.ALL:
        conditions.append(Item.trade_type == query.type)
    if query.category:
        conditions.append(ItemCategory.name == query.category)
    if query.communityId:
        conditions.append(Item.community_id == query.communityId)
    elif not query.near and viewer_resident_community_id:
        conditions.append(Item.community_id == viewer_resident_community_id)
    if query.keyword:
        like = f"%{query.keyword}%"
        conditions.append(or_(Item.title.ilike(like), Item.description.ilike(like)))
    return conditions
