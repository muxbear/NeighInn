from __future__ import annotations

import time
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import (
    allowed_community_ids,
    community_scope_conditions,
    require_permission,
    resolve_community_scope,
)
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.core.security import encrypt_field
from src.db.models import (
    Broadcast,
    Certification,
    Community,
    Dispute,
    Feedback,
    HelpRequest,
    Item,
    LifePost,
    Notice,
    Order,
    Region,
    RepairOrder,
    Report,
    Resident,
    User,
    admin_user_communities,
)

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


class CommunityImportRow(BaseModel):
    name: str
    code: str = ""
    type: str = "商品房社区"
    districtName: str
    streetName: str = ""
    address: str = ""
    longitude: float | None = None
    latitude: float | None = None
    households: int = 0
    population: int = 0
    propertyContact: str = ""
    managerName: str = ""
    status: str = "OPERATING"


class CommunityImportIn(BaseModel):
    cityId: int
    items: list[CommunityImportRow]


VALID_COMMUNITY_STATUS = ("OPERATING", "PREPARING", "SUSPENDED")
STATUS_ALIASES = {
    "正常运营": "OPERATING", "运营中": "OPERATING", "OPERATING": "OPERATING",
    "筹备中": "PREPARING", "PREPARING": "PREPARING",
    "已停用": "SUSPENDED", "停用": "SUSPENDED", "SUSPENDED": "SUSPENDED",
}


def _validate_optional_coordinates(longitude: float | None, latitude: float | None) -> None:
    """经纬度为选填；填写时需成对出现，用于距离计算与邻近小区排序。"""
    if longitude is None and latitude is None:
        return
    if longitude is None or latitude is None:
        raise ApiError(ERR_PARAM, "经度与纬度需同时填写或同时留空", 400)
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ApiError(ERR_PARAM, "经度需在 -180~180，纬度需在 -90~90", 400)


def _normalize_status(value: str) -> str:
    raw = (value or "").strip()
    status = STATUS_ALIASES.get(raw, raw.upper())
    if status not in VALID_COMMUNITY_STATUS:
        raise ApiError(ERR_PARAM, "运营状态不合法（正常运营 / 筹备中 / 已停用）", 400)
    return status


async def _resolve_region(db: DbSession, region_id: int | None,
                          street_id: int | None) -> tuple[Region | None, Region | None]:
    """校验并返回（区县，街道）；街道为空表示不指定（可选）。"""
    region = await db.get(Region, region_id) if region_id else None
    if region_id and region is None:
        raise ApiError(ERR_PARAM, "所在区/县不存在", 400)
    if region is not None and region.level != "DISTRICT":
        raise ApiError(ERR_PARAM, "请选择区/县", 400)
    street = await db.get(Region, street_id) if street_id else None
    if street_id and street is None:
        raise ApiError(ERR_PARAM, "所在街道不存在", 400)
    if street is not None and street.level != "STREET":
        raise ApiError(ERR_PARAM, "所选街道不合法", 400)
    if region is not None and street is not None and street.parent_id != region.id:
        raise ApiError(ERR_PARAM, "所选街道不属于该区/县", 400)
    return region, street


async def _generate_community_code(db: DbSession, region: Region | None) -> str:
    prefix = region.code[:6] if region and region.code else "000000"
    for _ in range(8):
        code = f"SQ{prefix}{uuid4().hex[:6].upper()}"
        if not await db.scalar(select(Community.id).where(Community.code == code)):
            return code
    raise ApiError(50000, "社区编码生成失败，请稍后重试", 500)


async def _assert_unique_community_name(db: DbSession, region: Region,
                                        name: str, exclude_id: int | None = None) -> None:
    stmt = select(Community.id).where(Community.region_id == region.id, Community.name == name)
    if exclude_id:
        stmt = stmt.where(Community.id != exclude_id)
    if await db.scalar(stmt):
        raise ApiError(40901, "该区/县已存在同名社区", 409)


async def _community_references(db: DbSession, community_id: int) -> list[str]:
    """删除前检查业务引用；有引用时返回可读的占用项，避免外键错误。"""
    models = (
        (Resident, "业主档案"), (Item, "物品"), (Order, "订单"),
        (HelpRequest, "互助请求"), (Broadcast, "社区喇叭"), (LifePost, "生活内容"),
        (Report, "举报"), (Notice, "公告"), (Dispute, "纠纷"),
        (RepairOrder, "报修工单"), (Feedback, "投诉建议"), (Certification, "认证单"),
    )
    blocked: list[str] = []
    for model, label in models:
        count = await db.scalar(
            select(func.count()).select_from(model).where(model.community_id == community_id))
        if count:
            blocked.append(f"{label}{int(count)}条")
    intent_count = await db.scalar(
        select(func.count()).select_from(User).where(User.intent_community_id == community_id))
    if intent_count:
        blocked.append(f"用户意向小区{int(intent_count)}条")
    admin_count = await db.scalar(
        select(func.count()).select_from(admin_user_communities)
        .where(admin_user_communities.c.community_id == community_id))
    if admin_count:
        blocked.append(f"管理员数据权限{int(admin_count)}条")
    return blocked


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


# 区划为低频变更的参考数据：按父节点缓存直接子级，配合前端懒加载避免每次拉取 1800+ 节点。
_REGION_CACHE_TTL_SECONDS = 600.0
_region_children_cache: dict[int | None, tuple[float, list[dict]]] = {}


def clear_region_cache() -> None:
    _region_children_cache.clear()


async def _region_children_payload(db: DbSession, parent_id: int | None) -> list[dict]:
    now = time.monotonic()
    cached = _region_children_cache.get(parent_id)
    if cached is not None and now - cached[0] < _REGION_CACHE_TTL_SECONDS:
        return cached[1]

    stmt = select(Region).order_by(Region.sort, Region.id)
    stmt = (stmt.where(Region.parent_id == parent_id) if parent_id
            else stmt.where(Region.parent_id.is_(None)))
    rows = list((await db.execute(stmt)).scalars().all())

    child_counts: dict[int, int] = {}
    ids = [row.id for row in rows]
    if ids:
        count_rows = (await db.execute(
            select(Region.parent_id, func.count())
            .where(Region.parent_id.in_(ids))
            .group_by(Region.parent_id)
        )).all()
        child_counts = {pid: int(count) for pid, count in count_rows if pid is not None}

    payload = [{"id": str(row.id), "name": row.name, "level": row.level,
                "code": row.code, "childCount": child_counts.get(row.id, 0)}
               for row in rows]
    _region_children_cache[parent_id] = (now, payload)
    return payload


@router.get("/regions/tree")
async def region_tree(admin: CurrentAdmin, db: DbSession,
                      scoped: bool = Query(default=False)):
    """完整区划树（兼容旧客户端）；社区运维页面改用 roots/children 分级加载。

    ``scoped=true`` 时按后台账号的社区数据范围裁剪：只保留其可管理社区所在的
    区县/街道及其上级节点，供筛选栏四级联动使用（超级管理员仍返回全量）。
    """
    rows = list((await db.execute(select(Region).order_by(Region.sort, Region.id))).scalars().all())
    keep_ids: set[int] | None = None
    if scoped:
        allowed = await allowed_community_ids(db, admin)
        if allowed is not None:
            by_id = {row.id: row for row in rows}
            seeds: set[int] = set()
            if allowed:
                pairs = (await db.execute(
                    select(Community.region_id, Community.street_id)
                    .where(Community.id.in_(allowed))
                )).all()
                for region_id, street_id in pairs:
                    if region_id:
                        seeds.add(int(region_id))
                    if street_id:
                        seeds.add(int(street_id))
            keep_ids = set(seeds)
            # 补齐所有上级节点，保证裁剪后的树从省到街道连续。
            for seed in seeds:
                current = by_id.get(seed)
                while current is not None and current.parent_id:
                    keep_ids.add(int(current.parent_id))
                    current = by_id.get(int(current.parent_id))
    nodes = {row.id: {"id": str(row.id), "name": row.name, "level": row.level,
                      "code": row.code, "children": []} for row in rows
             if keep_ids is None or row.id in keep_ids}
    roots: list[dict] = []
    for row in rows:
        node = nodes.get(row.id)
        if node is None:
            continue
        if row.parent_id and row.parent_id in nodes:
            nodes[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok(roots)


@router.get("/regions/roots")
async def region_roots(admin: CurrentAdmin, db: DbSession):
    return ok(await _region_children_payload(db, None))


@router.get("/regions/{region_id}/children")
async def region_children(region_id: int, admin: CurrentAdmin, db: DbSession):
    return ok(await _region_children_payload(db, region_id))


@router.get("/communities")
async def list_communities(admin: CurrentAdmin, db: DbSession,
                           keyword: str | None = Query(default=None),
                           cityId: int | None = Query(default=None),
                           streetId: int | None = Query(default=None),
                           regionId: int | None = Query(default=None),
                           status: str | None = Query(default=None),
                           page: int = Query(default=1), pageSize: int = Query(default=20)):
    resolved = await resolve_community_scope(db, admin, None)
    stmt = select(Community).where(
        *community_scope_conditions(resolved, Community.id))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Community.name.ilike(like), Community.code.ilike(like),
                              Community.address.ilike(like)))
    if cityId:
        # 社区档案的 region_id 指向区县；按地市筛选时展开其下区县。
        district_ids = select(Region.id).where(Region.parent_id == cityId)
        stmt = stmt.where(or_(Community.region_id.in_(district_ids), Community.region_id == cityId))
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
    resolved = await resolve_community_scope(db, admin, None)
    stmt = select(Community).where(
        *community_scope_conditions(resolved, Community.id))
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
    if len(name) > 64:
        raise ApiError(ERR_PARAM, "社区名称最多 64 字", 400)
    _validate_optional_coordinates(payload.longitude, payload.latitude)
    status = _normalize_status(payload.status)
    region, street = await _resolve_region(db, payload.regionId, payload.streetId)
    if region is None:
        raise ApiError(ERR_PARAM, "请选择所在区/县", 400)
    await _assert_unique_community_name(db, region, name)

    code = (payload.code or "").strip()
    if len(code) > 32:
        raise ApiError(ERR_PARAM, "社区编码最多 32 位", 400)
    if code:
        if await db.scalar(select(Community.id).where(Community.code == code)):
            raise ApiError(40901, "社区编码已存在", 409)
    else:
        code = await _generate_community_code(db, region)

    community = Community(
        region_id=region.id, street_id=street.id if street else None, name=name, code=code,
        type=payload.type.strip() or "商品房社区", address=payload.address.strip(),
        longitude=payload.longitude, latitude=payload.latitude,
        property_contact_enc=encrypt_field(payload.propertyContact) if payload.propertyContact else "",
        households=max(0, payload.households), population=max(0, payload.population),
        manager_name=payload.managerName.strip(), status=status,
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
    await resolve_community_scope(db, admin, community.id)
    return ok(_row(community))


@router.put("/communities/{community_id}",
            dependencies=[Depends(require_permission("community:maintenance:update"))])
async def update_community(community_id: int, payload: CommunityIn,
                           request: Request, admin: CurrentAdmin, db: DbSession):
    community = await db.get(Community, community_id)
    if not community:
        raise ApiError(ERR_NOT_FOUND, "社区不存在", 404)
    await resolve_community_scope(db, admin, community.id)
    before = _row(community)
    name = payload.name.strip()
    if not name:
        raise ApiError(ERR_PARAM, "社区名称必填", 400)
    if len(name) > 64:
        raise ApiError(ERR_PARAM, "社区名称最多 64 字", 400)

    fields = payload.model_fields_set
    region_id = payload.regionId if "regionId" in fields else community.region_id
    street_id = payload.streetId if "streetId" in fields else community.street_id
    region, street = await _resolve_region(db, region_id, street_id)
    if region is None:
        raise ApiError(ERR_PARAM, "请选择所在区/县", 400)
    await _assert_unique_community_name(db, region, name, exclude_id=community.id)

    coords_supplied = "longitude" in fields or "latitude" in fields
    if coords_supplied:
        _validate_optional_coordinates(payload.longitude, payload.latitude)
    status = _normalize_status(payload.status) if "status" in fields else community.status

    community.name = name
    community.region_id = region.id
    community.street_id = street.id if street else None
    community.type = payload.type.strip() or community.type
    community.address = payload.address.strip()
    if coords_supplied:
        community.longitude = payload.longitude
        community.latitude = payload.latitude
    if payload.propertyContact:
        community.property_contact_enc = encrypt_field(payload.propertyContact)
    community.households = max(0, payload.households)
    community.population = max(0, payload.population)
    community.manager_name = payload.managerName.strip()
    community.status = status
    await write_audit(db, request, actor=admin, action="community.update",
                      resource_type="community", resource_id=community.id,
                      before=before, after=_row(community))
    await db.commit()
    return ok(_row(community), "社区已更新")


@router.delete("/communities/{community_id}",
               dependencies=[Depends(require_permission("community:maintenance:update"))])
async def delete_community(community_id: int, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    """仅允许删除无业务引用的社区；已有业主/物品/订单等数据时建议改为停用。"""
    community = await db.get(Community, community_id)
    if not community:
        raise ApiError(ERR_NOT_FOUND, "社区不存在", 404)
    await resolve_community_scope(db, admin, community.id)
    references = await _community_references(db, community_id)
    if references:
        raise ApiError(
            40901,
            f"该社区已有业务数据（{'、'.join(references)}），不能删除，建议改为停用",
            409,
        )
    before = _row(community)
    await db.delete(community)
    await write_audit(db, request, actor=admin, action="community.delete",
                      resource_type="community", resource_id=community_id,
                      before=before, after=None)
    await db.commit()
    return ok({"id": str(community_id)}, "社区已删除")


@router.post("/communities/import",
             dependencies=[Depends(require_permission("community:maintenance:create"))])
async def import_communities(payload: CommunityImportIn, request: Request,
                             admin: CurrentAdmin, db: DbSession):
    """按当前地市批量导入社区；逐行独立保存，返回成功数与失败明细。"""
    if not payload.items:
        raise ApiError(ERR_PARAM, "导入内容为空，请先选择 CSV 文件", 400)
    if len(payload.items) > 500:
        raise ApiError(ERR_PARAM, "单次最多导入 500 个社区", 400)

    city = await db.get(Region, payload.cityId)
    if city is None or city.level != "CITY":
        raise ApiError(ERR_PARAM, "请先在左侧选择地市后再导入", 400)
    districts = list((await db.execute(
        select(Region).where(Region.parent_id == city.id, Region.level == "DISTRICT")
        .order_by(Region.sort, Region.id)
    )).scalars().all())
    if not districts:
        raise ApiError(ERR_PARAM, "该地市暂无区/县数据，无法导入", 400)
    districts_by_name = {row.name: row for row in districts}
    district_ids = [row.id for row in districts]

    existing_rows = (await db.execute(
        select(Community.region_id, Community.name, Community.code)
        .where(Community.region_id.in_(district_ids))
    )).all()
    existing_names = {(int(region_id), str(name))
                      for region_id, name, _ in existing_rows if region_id is not None}
    existing_codes = {str(code) for _, _, code in existing_rows if code}
    street_cache: dict[int, dict[str, Region]] = {}

    async def street_map(district_id: int) -> dict[str, Region]:
        if district_id not in street_cache:
            rows = list((await db.execute(
                select(Region).where(Region.parent_id == district_id, Region.level == "STREET")
                .order_by(Region.sort, Region.id)
            )).scalars().all())
            street_cache[district_id] = {row.name: row for row in rows}
        return street_cache[district_id]

    created = 0
    errors: list[dict] = []
    for index, item in enumerate(payload.items, start=1):
        try:
            name = item.name.strip()
            if not name:
                raise ApiError(ERR_PARAM, "社区名称必填", 400)
            if len(name) > 64:
                raise ApiError(ERR_PARAM, "社区名称最多 64 字", 400)
            district = districts_by_name.get(item.districtName.strip())
            if district is None:
                raise ApiError(ERR_PARAM, f"区/县“{item.districtName.strip() or '空'}”不存在", 400)
            street = None
            street_name = item.streetName.strip()
            if street_name:
                street = (await street_map(district.id)).get(street_name)
                if street is None:
                    raise ApiError(ERR_PARAM, f"街道“{street_name}”不属于{district.name}", 400)
            _validate_optional_coordinates(item.longitude, item.latitude)
            status = _normalize_status(item.status)
            if item.households < 0 or item.population < 0:
                raise ApiError(ERR_PARAM, "户数/人口不能为负数", 400)
            if (district.id, name) in existing_names:
                raise ApiError(40901, "该区/县已存在同名社区", 409)

            code = item.code.strip()
            if len(code) > 32:
                raise ApiError(ERR_PARAM, "社区编码最多 32 位", 400)
            if code:
                if code in existing_codes:
                    raise ApiError(40901, "社区编码已存在", 409)
                if await db.scalar(select(Community.id).where(Community.code == code)):
                    raise ApiError(40901, "社区编码已存在", 409)
            else:
                code = await _generate_community_code(db, district)

            async with db.begin_nested():
                community = Community(
                    region_id=district.id, street_id=street.id if street else None,
                    name=name, code=code,
                    type=item.type.strip() or "商品房社区", address=item.address.strip(),
                    longitude=item.longitude, latitude=item.latitude,
                    property_contact_enc=(encrypt_field(item.propertyContact)
                                          if item.propertyContact else ""),
                    households=item.households, population=item.population,
                    manager_name=item.managerName.strip(), status=status,
                )
                db.add(community)
                await db.flush()
            existing_names.add((district.id, name))
            existing_codes.add(code)
            created += 1
        except ApiError as exc:
            errors.append({"row": index, "name": item.name, "message": exc.message})
        except IntegrityError:
            errors.append({"row": index, "name": item.name, "message": "数据冲突，请检查编码是否重复"})

    await write_audit(db, request, actor=admin, action="community.import",
                      resource_type="community", resource_id="",
                      before=None, after={"cityId": payload.cityId, "total": len(payload.items),
                                          "created": created, "failed": len(errors)})
    await db.commit()
    message = f"成功导入 {created} 个社区"
    if errors:
        message += f"，{len(errors)} 行失败"
    return ok({"created": created, "failed": len(errors), "errors": errors[:100]}, message)


@router.patch("/communities/{community_id}/status",
              dependencies=[Depends(require_permission("community:maintenance:update"))])
async def update_community_status(community_id: int, payload: dict,
                                  request: Request, admin: CurrentAdmin, db: DbSession):
    """停用后移动端不可见，已绑定业主保留历史数据（详设 4.7.7）。"""
    community = await db.get(Community, community_id)
    if not community:
        raise ApiError(ERR_NOT_FOUND, "社区不存在", 404)
    await resolve_community_scope(db, admin, community.id)
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
