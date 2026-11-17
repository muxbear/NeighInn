from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from src.core.deps import CurrentUser, DbSession
from src.core.responses import ok
from src.db.models import AppNotification, Broadcast, Community, HelpRequest, Item, LifePost, Resident
from src.domain import enums as E
from src.services import item_service as item_svc
from src.services.auth_service import bound_resident
from src.services.broadcast_service import visibility_filters

router = APIRouter(tags=["c:home"])


@router.get("/home")
async def home_bundle(user: CurrentUser, db: DbSession):
    """首页聚合（M02）：本小区信息、四专属区统计、喇叭站、小区拾物、
    互助、生活流、通知未读数。"""
    resident = await bound_resident(db, user.id)
    community_id = resident.community_id if resident else None
    community = await db.get(Community, community_id) if community_id else None

    verified_count = item_count = service_count = 0
    if community_id:
        verified_count = int((await db.scalar(
            select(func.count()).select_from(Resident).where(
                Resident.community_id == community_id,
                Resident.certification_status == "VERIFIED"))) or 0)
        item_count = int((await db.scalar(
            select(func.count()).select_from(Item).where(
                Item.community_id == community_id, Item.status == E.ItemStatus.ON_SALE))) or 0)
        service_count = int((await db.scalar(
            select(func.count()).select_from(HelpRequest).where(
                HelpRequest.community_id == community_id,
                HelpRequest.status == E.HelpStatus.OPEN))) or 0)

    zones = []
    for zone_key, trade_type in (("gift", E.TradeType.FREE_GIFT),
                                 ("swap", E.TradeType.BARTER),
                                 ("sale", E.TradeType.MONETARY)):
        count_stmt = select(func.count()).select_from(Item).where(
            Item.trade_type == trade_type, Item.status == E.ItemStatus.ON_SALE)
        if community_id:
            count_stmt = count_stmt.where(Item.community_id == community_id)
        count = int((await db.scalar(count_stmt)) or 0)
        zones.append({"key": zone_key,
                      "name": {"gift": "物品赠与", "swap": "物品互换", "sale": "闲置赚米"}[zone_key],
                      "count": count})
    service_zone_count = service_count
    zones.append({"key": "service", "name": "邻里互助", "count": service_zone_count})

    broadcasts = []
    if community_id:
        broadcast_rows = list((await db.execute(
            select(Broadcast).where(Broadcast.community_id == community_id,
                                    *visibility_filters())
            .order_by(Broadcast.important.desc(), Broadcast.id.desc()).limit(5))
        ).scalars().all())
        from src.api.c_end.broadcasts import _row as broadcast_row

        broadcasts = [await broadcast_row(db, row, user) for row in broadcast_rows]

    hot_stmt = (select(Item).where(Item.status == E.ItemStatus.ON_SALE)
                .order_by(Item.recommended.desc(), Item.published_at.desc().nullslast(),
                          Item.id.desc()).limit(10))
    if community_id:
        hot_stmt = hot_stmt.where(Item.community_id == community_id)
    hot_items = [await item_svc.serialize_item(db, item, user)
                 for item in (await db.execute(hot_stmt)).scalars().all()]

    help_stmt = (select(HelpRequest)
                 .where(HelpRequest.status == E.HelpStatus.OPEN)
                 .order_by(HelpRequest.urgent.desc(), HelpRequest.id.desc()).limit(4))
    if community_id:
        help_stmt = help_stmt.where(HelpRequest.community_id == community_id)
    from src.api.c_end.services import _row as service_row

    help_rows = list((await db.execute(help_stmt)).scalars().all())
    service_help = [await service_row(db, row, user) for row in help_rows if row.kind == "HELP"]
    service_offer = [await service_row(db, row, user) for row in help_rows if row.kind == "OFFER"]

    life_stmt = (select(LifePost).where(LifePost.status == "PUBLISHED")
                 .order_by(LifePost.published_at.desc().nullslast(), LifePost.id.desc()).limit(10))
    if community_id:
        life_stmt = life_stmt.where(LifePost.community_id == community_id)
    from src.api.c_end.life import _row as life_row

    life_posts = [await life_row(db, post, user)
                  for post in (await db.execute(life_stmt)).scalars().all()]

    unread = int((await db.scalar(
        select(func.count()).select_from(AppNotification).where(
            AppNotification.user_id == user.id,
            AppNotification.read_at.is_(None)))) or 0)

    return ok({
        "community": {
            "id": str(community.id) if community else "",
            "name": community.name if community else "",
            "building": resident.building if resident else "",
            "verifiedCount": verified_count,
            "itemCount": item_count,
            "serviceCount": service_count,
        },
        "zones": zones,
        "broadcasts": broadcasts,
        "hotItems": hot_items,
        "serviceHelp": service_help,
        "serviceOffer": service_offer,
        "lifePosts": life_posts,
        "notificationUnread": unread,
    })
