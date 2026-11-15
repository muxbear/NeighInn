from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from src.core.config import settings
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ok
from src.db.models import Community, HelpRequest, Item, Region, Resident

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


async def _region_lookup(db: DbSession) -> dict[int, Region]:
    """一次取出区划树，供列表内各小区解析省/市/区/街道，避免逐条查询。"""
    rows = list((await db.execute(select(Region))).scalars().all())
    return {row.id: row for row in rows}


def _region_fields(community: Community, regions: dict[int, Region]) -> dict:
    """沿 street_id（缺省时 region_id）向上追溯 PROVINCE / CITY / DISTRICT / STREET。"""
    node = regions.get(community.street_id) if community.street_id else None
    if node is None and community.region_id:
        node = regions.get(community.region_id)
    by_level: dict[str, str] = {}
    guard = 0
    while node is not None and guard < 8:
        by_level.setdefault(node.level, node.name)
        node = regions.get(node.parent_id) if node.parent_id else None
        guard += 1
    province = by_level.get("PROVINCE", "")
    city = by_level.get("CITY", "")
    district = by_level.get("DISTRICT", "")
    street = by_level.get("STREET", "")
    # 直辖市可能省、市同名，展示路径去重相邻重复项。
    parts: list[str] = []
    for name in (province, city, district, street):
        if name and (not parts or parts[-1] != name):
            parts.append(name)
    return {
        "province": province,
        "city": city,
        "district": district,
        "street": street,
        "regionPath": " ".join(parts),
        "regionId": str(community.region_id) if community.region_id else "",
        "streetId": str(community.street_id) if community.street_id else "",
    }


async def _to_binding(db: DbSession, community: Community, resident: Resident | None,
                      base: Community | None = None,
                      regions: dict[int, Region] | None = None) -> dict:
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
    region_data = _region_fields(community, regions) if regions is not None else {}
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
        **region_data,
    }


@router.get("/regions/children")
async def region_children(user: CurrentUser, db: DbSession, parentId: int = 0):
    """行政区划逐级下钻（省份/直辖市 → 地市 → 区/县 → 街道），供移动端小区选择使用。"""
    stmt = select(Region).order_by(Region.sort, Region.id)
    stmt = stmt.where(Region.parent_id == parentId) if parentId else stmt.where(Region.parent_id.is_(None))
    rows = list((await db.execute(stmt)).scalars().all())
    return ok([{"id": str(row.id), "name": row.name, "level": row.level, "code": row.code}
               for row in rows])


@router.get("/communities/mine")
async def my_communities(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(Resident, Community)
        .join(Community, Community.id == Resident.community_id)
        .where(Resident.user_id == user.id)
        .order_by(Resident.id.desc())
    )).all())
    regions = await _region_lookup(db)
    return ok([await _to_binding(db, community, resident, regions=regions)
               for resident, community in rows])


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
    regions = await _region_lookup(db)
    results = []
    for community in rows:
        if base and community.id == base.id:
            continue
        km = _distance_km(community.longitude, community.latitude,
                          base.longitude if base else None, base.latitude if base else None)
        if base and km is not None and km > settings.nearby_radius_km:
            continue
        binding = await _to_binding(db, community, None, base, regions)
        binding["_km"] = km if km is not None else 9999.0
        results.append(binding)
    results.sort(key=lambda row: row["_km"])
    for row in results:
        row.pop("_km", None)
    return ok(results[: settings.nearby_max_count])


@router.get("/communities/search")
async def search_communities(
    user: CurrentUser, db: DbSession, keyword: str = Query(default=""),
    cityId: int | None = Query(default=None),
    streetId: int | None = Query(default=None),
    regionId: int | None = Query(default=None),
    page: int = 1, pageSize: int = 20,
):
    """小区检索：支持关键词，以及按地市/区县/街道筛选（住户认证选择小区）。"""
    stmt = select(Community).where(Community.status == "OPERATING")
    if cityId:
        district_ids = select(Region.id).where(Region.parent_id == cityId)
        stmt = stmt.where(or_(Community.region_id.in_(district_ids), Community.region_id == cityId))
    if streetId:
        stmt = stmt.where(Community.street_id == streetId)
    if regionId:
        stmt = stmt.where(Community.region_id == regionId)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Community.name.ilike(like), Community.code.ilike(like),
                              Community.address.ilike(like)))
    rows = list((await db.execute(stmt.order_by(Community.id).limit(50))).scalars().all())
    regions = await _region_lookup(db)
    return ok([await _to_binding(db, community, None, regions=regions) for community in rows])
