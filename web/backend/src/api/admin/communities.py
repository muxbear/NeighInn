from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.core.security import encrypt_field
from src.db.models import Community, Region

router = APIRouter(tags=["admin:communities"])

# W04-01：社区档案与坐标（地图选点数据基础，SRS 8.2）。
# 停用需二次确认（前端）：停用后移动端不可见，已绑定业主保留历史数据。


class CommunityIn(BaseModel):
    name: str
    code: str | None = None
    type: str = "商品房社区"
    address: str = ""
    regionId: int | None = None
    streetId: int | None = None
    longitude: float | None = None
    latitude: float | None = None
    propertyContact: str = ""
    households: int = 0
    population: int = 0
    managerName: str = ""
    status: str = "OPERATING"


def _row(community: Community) -> dict:
    return {
        "id": str(community.id), "name": community.name, "code": community.code,
        "type": community.type, "address": community.address,
        "longitude": float(community.longitude) if community.longitude is not None else None,
        "latitude": float(community.latitude) if community.latitude is not None else None,
        "households": community.households, "population": community.population,
        "managerName": community.manager_name, "status": community.status,
        "regionId": str(community.region_id) if community.region_id else "",
        "streetId": str(community.street_id) if community.street_id else "",
        "openedAt": community.opened_at.isoformat() if community.opened_at else "",
        "updatedAt": int(community.updated_at.timestamp() * 1000) if community.updated_at else 0,
    }


@router.get("/regions/tree")
async def region_tree(admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(select(Region).order_by(Region.sort, Region.id))).scalars().all())
    nodes = {row.id: {"id": str(row.id), "name": row.name, "level": row.level,
                      "code": row.code, "children": []} for row in rows}
    roots: list[dict] = []
    for row in rows:
        node = nodes[row.id]
        if row.parent_id and row.parent_id in nodes:
            nodes[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok(roots)


@router.get("/regions/{region_id}/children")
async def region_children(region_id: int, admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(Region).where(Region.parent_id == region_id)
        .order_by(Region.sort, Region.id))).scalars().all())
    return ok([{"id": str(row.id), "name": row.name, "level": row.level, "code": row.code}
               for row in rows])


@router.get("/communities")
async def list_communities(admin: CurrentAdmin, db: DbSession,
                           keyword: str | None = Query(default=None),
                           streetId: int | None = Query(default=None),
                           regionId: int | None = Query(default=None),
                           status: str | None = Query(default=None),
                           page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(Community)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Community.name.ilike(like), Community.code.ilike(like),
                              Community.address.ilike(like)))
    if streetId:
        stmt = stmt.where(Community.street_id == streetId)
    if regionId:
        stmt = stmt.where(Community.region_id == regionId)
    if status:
        stmt = stmt.where(Community.status == status)
    rows, total = await paginate(db, stmt.order_by(Community.id), page, pageSize)
    return paginated([_row(row) for row in rows], page, pageSize, total)


@router.get("/communities/search")
async def search_communities(admin: CurrentAdmin, db: DbSession, q: str = Query(default="")):
    stmt = select(Community)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Community.name.ilike(like), Community.code.ilike(like),
                              Community.address.ilike(like)))
    rows = list((await db.execute(stmt.order_by(Community.id).limit(20))).scalars().all())
    return ok([_row(row) for row in rows])


@router.post("/communities",
             dependencies=[Depends(require_permission("community:maintenance:create"))])
async def create_community(payload: CommunityIn, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    name = payload.name.strip()
    if not name:
        raise ApiError(ERR_PARAM, "社区名称必填", 400)
    if payload.longitude is None or payload.latitude is None:
        raise ApiError(ERR_PARAM, "小区坐标必填（距离计算的数据基础，SRS 8.2）", 400)
    code = payload.code or f"SQ{int(utc_timestamp())}"
    if await db.scalar(select(Community.id).where(Community.code == code)):
        raise ApiError(40901, "社区编码已存在", 409)
    community = Community(
        region_id=payload.regionId, street_id=payload.streetId, name=name, code=code,
        type=payload.type, address=payload.address,
        longitude=payload.longitude, latitude=payload.latitude,
        property_contact_enc=encrypt_field(payload.propertyContact) if payload.propertyContact else "",
        households=payload.households, population=payload.population,
        manager_name=payload.managerName, status=payload.status,
    )
    db.add(community)
    await db.flush()
    await write_audit(db, request, actor=admin, action="community.create",
                      resource_type="community", resource_id=community.id,
                      before=None, after={"name": name, "code": code})
    await db.commit()
    return ok(_row(community), "社区已创建")


@router.get("/communities/{community_id}")
async def community_detail(community_id: int, admin: CurrentAdmin, db: DbSession):
    community = await db.get(Community, community_id)
    if not community:
        raise ApiError(ERR_NOT_FOUND, "社区不存在", 404)
    return ok(_row(community))


@router.put("/communities/{community_id}",
            dependencies=[Depends(require_permission("community:maintenance:update"))])
async def update_community(community_id: int, payload: CommunityIn,
                           request: Request, admin: CurrentAdmin, db: DbSession):
    community = await db.get(Community, community_id)
    if not community:
        raise ApiError(ERR_NOT_FOUND, "社区不存在", 404)
    before = _row(community)
    community.name = payload.name.strip() or community.name
    community.type = payload.type
    community.address = payload.address
    if payload.regionId:
        community.region_id = payload.regionId
    if payload.streetId:
        community.street_id = payload.streetId
    if payload.longitude is not None:
        community.longitude = payload.longitude
    if payload.latitude is not None:
        community.latitude = payload.latitude
    if payload.propertyContact:
        community.property_contact_enc = encrypt_field(payload.propertyContact)
    community.households = payload.households
    community.population = payload.population
    community.manager_name = payload.managerName
    await write_audit(db, request, actor=admin, action="community.update",
                      resource_type="community", resource_id=community.id,
                      before=before, after=_row(community))
    await db.commit()
    return ok(_row(community), "社区已更新")


@router.patch("/communities/{community_id}/status",
              dependencies=[Depends(require_permission("community:maintenance:update"))])
async def update_community_status(community_id: int, payload: dict,
                                  request: Request, admin: CurrentAdmin, db: DbSession):
    """停用后移动端不可见，已绑定业主保留历史数据（详设 4.7.7）。"""
    community = await db.get(Community, community_id)
    if not community:
        raise ApiError(ERR_NOT_FOUND, "社区不存在", 404)
    status = payload.get("status", "")
    if status not in ("OPERATING", "PREPARING", "SUSPENDED"):
        raise ApiError(ERR_PARAM, "状态不合法（OPERATING / PREPARING / SUSPENDED）", 400)
    before = {"status": community.status}
    community.status = status
    await write_audit(db, request, actor=admin, action="community.status",
                      resource_type="community", resource_id=community.id,
                      before=before, after={"status": status})
    await db.commit()
    return ok(_row(community), "社区状态已更新")


def utc_timestamp() -> float:
    from src.db.models.common import utcnow

    return utcnow().timestamp()
