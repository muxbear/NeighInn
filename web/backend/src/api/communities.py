from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import camelize, get_or_404, model_dict, paginate
from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ApiError, ok, paginated
from src.db.models import Community, Region

router = APIRouter(tags=["communities"])


@router.get("/regions/tree")
async def region_tree(db: DbSession, admin: CurrentAdmin):
    rows = list((await db.execute(select(Region).order_by(Region.sort, Region.id))).scalars().all())
    nodes = {row.id: {**model_dict(row), "children": []} for row in rows}
    roots: list[dict] = []
    for row in rows:
        node = nodes[row.id]
        if row.parent_id and row.parent_id in nodes:
            nodes[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok(camelize(roots))


@router.get("/regions/{region_id}/children")
async def region_children(region_id: int, db: DbSession, admin: CurrentAdmin):
    rows = await db.execute(select(Region).where(Region.parent_id == region_id).order_by(Region.sort, Region.id))
    return ok(camelize([model_dict(row) for row in rows.scalars().all()]))


@router.get("/communities")
async def communities(
    db: DbSession,
    admin: CurrentAdmin,
    keyword: str | None = Query(default=None),
    streetId: int | None = Query(default=None),
    regionId: int | None = Query(default=None),
    page: int = Query(default=1),
    pageSize: int = Query(default=20),
):
    stmt = select(Community)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Community.name.ilike(like), Community.code.ilike(like)))
    if streetId:
        stmt = stmt.where(Community.street_id == streetId)
    if regionId:
        stmt = stmt.where(Community.region_id == regionId)
    stmt = stmt.order_by(Community.id)
    rows, total = await paginate(db, stmt, page, pageSize)
    return paginated([camelize(model_dict(row)) for row in rows], page, pageSize, total)


@router.get("/communities/search")
async def search_communities(db: DbSession, admin: CurrentAdmin, q: str = Query(default="")):
    stmt = select(Community)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Community.name.ilike(like), Community.code.ilike(like), Community.address.ilike(like)))
    rows = list((await db.execute(stmt.order_by(Community.id).limit(20))).scalars().all())
    return ok(camelize([model_dict(row) for row in rows]))


@router.get("/communities/{community_id}")
async def community_detail(community_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Community, community_id)
    return ok(camelize(model_dict(row)))


class CommunityIn(BaseModel):
    name: str
    code: str | None = None
    type: str = "商品房社区"
    address: str = ""
    regionId: int | None = None
    streetId: int | None = None
    households: int = 0
    population: int = 0
    managerName: str = ""
    status: str = "正常运营"


@router.post("/communities")
async def create_community(payload: CommunityIn, db: DbSession, admin: CurrentAdmin):
    code = payload.code or f"SQ{int(__import__('time').time() * 1000)}"
    if await db.scalar(select(Community.id).where(Community.code == code)):
        raise ApiError(40901, "社区编码已存在", 409)
    row = Community(
        region_id=payload.regionId, street_id=payload.streetId, name=payload.name, code=code,
        type=payload.type, address=payload.address, households=payload.households,
        population=payload.population, manager_name=payload.managerName, status=payload.status,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(camelize(model_dict(row)), "社区已创建")


@router.put("/communities/{community_id}")
async def update_community(community_id: int, payload: CommunityIn, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Community, community_id)
    row.name = payload.name
    row.type = payload.type
    row.address = payload.address
    row.region_id = payload.regionId or row.region_id
    row.street_id = payload.streetId or row.street_id
    row.households = payload.households
    row.population = payload.population
    row.manager_name = payload.managerName
    row.status = payload.status
    await db.commit()
    return ok(camelize(model_dict(row)), "社区已更新")


@router.patch("/communities/{community_id}/status")
async def update_community_status(community_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Community, community_id)
    row.status = payload.get("status", "正常运营")
    await db.commit()
    return ok(camelize(model_dict(row)), "社区状态已更新")
