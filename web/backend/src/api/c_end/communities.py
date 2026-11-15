from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from src.core.config import settings
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ok
from src.db.models import Community, HelpRequest, Item, Resident

router = APIRouter(tags=["c:communities"])


def _distance_km(lng1: float | None, lat1: float | None, lng2: float | None, lat2: float | None) -> float | None:
    """球面直线距离（km，Haversine 简化）。SRS 8.2：列表展示保留到 10m 级并加「约」。"""
    if None in (lng1, lat1, lng2, lat2):
        return None
    import math

    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2)
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _distance_label(km: float | None) -> str:
    if km is None:
        return ""
    meters = int(round(km * 1000, -1))
    return f"约{meters}m" if meters < 1000 else f"约{km:.1f}km"


async def _to_binding(db: DbSession, community: Community, resident: Resident | None,
                      base: Community | None = None) -> dict:
    member_count = int((await db.scalar(
        select(func.count()).select_from(Resident).where(
            Resident.community_id == community.id, Resident.certification_status == "VERIFIED")
    )) or 0)
    item_count = int((await db.scalar(
        select(func.count()).select_from(Item).where(
            Item.community_id == community.id, Item.status == "ON_SALE")
    )) or 0)
    help_count = int((await db.scalar(
        select(func.count()).select_from(HelpRequest).where(
            HelpRequest.community_id == community.id, HelpRequest.status == "OPEN")
    )) or 0)
    km = None
    if base:
        km = _distance_km(community.longitude, community.latitude, base.longitude, base.latitude)
    status_map = {"VERIFIED": "已认证", "PENDING": "审核中", "REJECTED": "已驳回"}
    role_map = {"业主": "业主", "租户": "租户", "家属": "家属"}
    return {
        "id": str(community.id),
        "name": community.name,
        "building": resident.building if resident else "",
        "role": role_map.get(resident.identity_type, "业主") if resident else "业主",
        "status": status_map.get(resident.certification_status, "审核中") if resident else "已驳回",
        "memberCount": member_count,
        "itemCount": item_count,
        "helpCount": help_count,
        "distance": _distance_label(km),
        "address": community.address,
    }


@router.get("/communities/mine")
async def my_communities(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(Resident, Community)
        .join(Community, Community.id == Resident.community_id)
        .where(Resident.user_id == user.id)
        .order_by(Resident.id.desc())
    )).all())
    return ok([await _to_binding(db, community, resident) for resident, community in rows])


@router.get("/communities/nearby")
async def nearby_communities(user: CurrentUser, db: DbSession):
    """邻近小区（BR-03/W04-02）：以绑定小区坐标为圆心，按半径参数过滤、距离排序。"""
    base_resident = await db.scalar(
        select(Resident).where(Resident.user_id == user.id,
                               Resident.certification_status == "VERIFIED").limit(1))
    base = await db.get(Community, base_resident.community_id) if base_resident else None
    rows = list((await db.execute(
        select(Community).where(Community.status == "OPERATING").order_by(Community.id)
    )).scalars().all())
    results = []
    for community in rows:
        if base and community.id == base.id:
            continue
        km = _distance_km(community.longitude, community.latitude,
                          base.longitude if base else None, base.latitude if base else None)
        if base and km is not None and km > settings.nearby_radius_km:
            continue
        binding = await _to_binding(db, community, None, base)
        binding["_km"] = km if km is not None else 9999.0
        results.append(binding)
    results.sort(key=lambda row: row["_km"])
    for row in results:
        row.pop("_km", None)
    return ok(results[: settings.nearby_max_count])


@router.get("/communities/search")
async def search_communities(
    user: CurrentUser, db: DbSession, keyword: str = Query(default=""),
    page: int = 1, pageSize: int = 20,
):
    stmt = select(Community).where(Community.status == "OPERATING")
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Community.name.ilike(like), Community.code.ilike(like),
                              Community.address.ilike(like)))
    rows = list((await db.execute(stmt.order_by(Community.id).limit(20))).scalars().all())
    return ok([await _to_binding(db, community, None) for community in rows])
