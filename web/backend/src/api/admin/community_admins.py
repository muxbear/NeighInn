"""社区管理员：后台账号的社区管理范围（区划授权 + 指定社区）。

- 指定社区沿用 ``admin_user_communities``（与用户管理、住户绑定共用）；
- 区划授权写入 ``admin_user_region_grants``，按区划子树动态展开；
- 两者并集由 ``core.permissions.allowed_community_ids`` 统一解析，确保配置后
  立即影响账号的实际数据范围。

写操作仅允许全局数据范围（ALL）的管理员执行，避免受限管理员通过授权提权。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.idempotency import complete_idempotency, guard_idempotency
from src.core.permissions import get_data_scope, require_permission
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
)
from src.db.models import (
    AdminUser,
    AdminUserRegionGrant,
    Community,
    Region,
    Resident,
    admin_user_communities,
)

router = APIRouter(tags=["admin:community-admins"])

ScopeViewPerm = Depends(require_permission("system:admin-user:view"))
ScopeManagePerm = Depends(require_permission("system:admin-user:update"))

MAX_REGION_GRANTS = 200
MAX_COMMUNITY_GRANTS = 2000


class CommunityScopeIn(BaseModel):
    regionIds: list[int] = []
    communityIds: list[int] = []


def _ms(value) -> int:
    return int(value.timestamp() * 1000) if value else 0


async def _load_region_closure(db: AsyncSession, seed_ids: set[int]) -> dict[int, Region]:
    """加载给定区划及其全部祖先（区划树最多 4 层，循环查询足够轻量）。"""
    loaded: dict[int, Region] = {}
    pending = {int(item) for item in seed_ids if item}
    while pending:
        rows = list((await db.execute(
            select(Region).where(Region.id.in_(pending))
        )).scalars().all())
        pending = set()
        for row in rows:
            loaded[row.id] = row
            if row.parent_id and row.parent_id not in loaded:
                pending.add(row.parent_id)
    return loaded


def _region_path(region_id: int | None, regions: dict[int, Region]) -> list[dict]:
    chain: list[Region] = []
    current = region_id
    seen: set[int] = set()
    while current and current in regions and current not in seen:
        seen.add(current)
        node = regions[current]
        chain.append(node)
        current = node.parent_id
    return [
        {"id": str(node.id), "name": node.name, "level": node.level}
        for node in reversed(chain)
    ]


def _community_path(community: Community, regions: dict[int, Region]) -> list[dict]:
    district = regions.get(community.region_id) if community.region_id else None
    street = regions.get(community.street_id) if community.street_id else None
    target = street if street and district and street.parent_id == district.id else district
    return _region_path(target.id, regions) if target else []


async def _scope_payload(db: AsyncSession, row: AdminUser) -> dict:
    region_grants = list((await db.execute(
        select(AdminUserRegionGrant)
        .where(AdminUserRegionGrant.admin_user_id == row.id)
        .order_by(AdminUserRegionGrant.id)
    )).scalars().all())
    communities = list((await db.execute(
        select(Community)
        .join(admin_user_communities,
              admin_user_communities.c.community_id == Community.id)
        .where(admin_user_communities.c.admin_user_id == row.id)
        .order_by(Community.id)
    )).scalars().all())

    seed_ids = {grant.region_id for grant in region_grants}
    for community in communities:
        if community.region_id:
            seed_ids.add(community.region_id)
        if community.street_id:
            seed_ids.add(community.street_id)
    regions = await _load_region_closure(db, seed_ids)

    return {
        "adminUserId": str(row.id),
        "isSuperAdmin": bool(row.is_super_admin),
        "scopeEditable": bool(not row.is_super_admin and row.status == "ACTIVE"),
        "regionGrants": [
            {
                "id": str(grant.id),
                "regionId": str(grant.region_id),
                "path": _region_path(grant.region_id, regions),
                "level": (regions[grant.region_id].level
                          if grant.region_id in regions else ""),
                "createdAt": _ms(grant.created_at),
                "updatedAt": _ms(grant.updated_at),
            }
            for grant in region_grants
        ],
        "communities": [
            {
                "id": str(community.id),
                "name": community.name,
                "code": community.code,
                "type": community.type,
                "address": community.address,
                "regionId": str(community.region_id) if community.region_id else "",
                "streetId": str(community.street_id) if community.street_id else "",
                "path": _community_path(community, regions),
                # 关联表没有单独的授权时间，前端对 0 展示“已生效”。
                "updatedAt": 0,
            }
            for community in communities
        ],
    }


async def _scope_snapshot(db: AsyncSession, admin_id: int) -> dict:
    region_ids = sorted((await db.execute(
        select(AdminUserRegionGrant.region_id)
        .where(AdminUserRegionGrant.admin_user_id == admin_id)
    )).scalars().all())
    community_ids = sorted((await db.execute(
        select(admin_user_communities.c.community_id)
        .where(admin_user_communities.c.admin_user_id == admin_id)
    )).scalars().all())
    return {"regionIds": region_ids, "communityIds": community_ids}


async def _assert_global_scope(db: AsyncSession, admin: AdminUser) -> None:
    if admin.is_super_admin:
        return
    if await get_data_scope(db, admin) != "ALL":
        raise ApiError(
            ERR_FORBIDDEN,
            "仅全局数据范围的管理员可调整社区管理范围",
            403,
        )


async def _normalize_region_ids(db: AsyncSession, region_ids: set[int]) -> list[int]:
    """校验区划存在，并移除已被更上级区划覆盖的下级授权。"""
    if not region_ids:
        return []
    regions = await _load_region_closure(db, region_ids)
    missing = sorted(region_ids - set(regions))
    if missing:
        raise ApiError(ERR_PARAM, f"区划不存在：{', '.join(map(str, missing[:3]))}", 400)

    kept: list[int] = []
    for region_id in sorted(region_ids):
        parent_id = regions[region_id].parent_id
        covered = False
        while parent_id:
            if parent_id in region_ids:
                covered = True
                break
            parent = regions.get(parent_id)
            parent_id = parent.parent_id if parent else None
        if not covered:
            kept.append(region_id)
    return kept


async def _validate_communities(db: AsyncSession, community_ids: set[int]) -> None:
    if not community_ids:
        return
    existing = set((await db.execute(
        select(Community.id).where(Community.id.in_(community_ids))
    )).scalars().all())
    missing = sorted(community_ids - existing)
    if missing:
        raise ApiError(ERR_PARAM, f"社区不存在：{', '.join(map(str, missing[:3]))}", 400)


@router.get("/admin-users/{admin_id}/community-scope", dependencies=[ScopeViewPerm])
async def get_admin_community_scope(admin_id: int, admin: CurrentAdmin, db: DbSession):
    row = await db.get(AdminUser, admin_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "管理员不存在", 404)
    return ok(await _scope_payload(db, row))


@router.put("/admin-users/{admin_id}/community-scope", dependencies=[ScopeManagePerm])
async def update_admin_community_scope(admin_id: int, payload: CommunityScopeIn,
                                       request: Request, admin: CurrentAdmin,
                                       db: DbSession):
    """全量替换账号的社区管理范围：区划授权 + 指定社区。"""
    row = await db.get(AdminUser, admin_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "管理员不存在", 404)
    if row.is_super_admin:
        raise ApiError(ERR_BIZ_RULE, "超级管理员默认拥有全部社区权限，无需分配", 422)
    if row.status != "ACTIVE":
        raise ApiError(ERR_BIZ_RULE, "账号已停用，请先启用后再分配管理范围", 422)
    await _assert_global_scope(db, admin)

    region_ids = {int(item) for item in payload.regionIds if int(item) > 0}
    community_ids = {int(item) for item in payload.communityIds if int(item) > 0}
    if len(region_ids) > MAX_REGION_GRANTS:
        raise ApiError(ERR_PARAM, f"区划授权最多 {MAX_REGION_GRANTS} 项", 400)
    if len(community_ids) > MAX_COMMUNITY_GRANTS:
        raise ApiError(ERR_PARAM, f"指定社区最多 {MAX_COMMUNITY_GRANTS} 个", 400)

    idem = await guard_idempotency(db, request, {
        "adminId": admin_id,
        "regionIds": sorted(region_ids),
        "communityIds": sorted(community_ids),
    })
    if idem and idem.status == "COMPLETED":
        return ok((idem.response_json or {}).get("data"))

    normalized_regions = await _normalize_region_ids(db, region_ids)
    await _validate_communities(db, community_ids)

    # 住户绑定账号必须保留本小区：住户授权页与登录态都依赖该映射。
    if row.resident_id:
        resident = await db.get(Resident, row.resident_id)
        if resident and resident.community_id:
            community_ids.add(resident.community_id)

    before = await _scope_snapshot(db, row.id)
    await db.execute(delete(AdminUserRegionGrant).where(
        AdminUserRegionGrant.admin_user_id == row.id))
    if normalized_regions:
        await db.execute(insert(AdminUserRegionGrant), [
            {"admin_user_id": row.id, "region_id": region_id}
            for region_id in normalized_regions
        ])

    await db.execute(delete(admin_user_communities).where(
        admin_user_communities.c.admin_user_id == row.id))
    if community_ids:
        await db.execute(insert(admin_user_communities), [
            {"admin_user_id": row.id, "community_id": community_id}
            for community_id in sorted(community_ids)
        ])

    await write_audit(
        db, request, actor=admin, action="admin-user.scope.update",
        resource_type="admin_user", resource_id=row.id,
        before=before,
        after={"regionIds": normalized_regions, "communityIds": sorted(community_ids)},
    )
    data = await _scope_payload(db, row)
    await complete_idempotency(db, idem, data)
    await db.commit()
    return ok(data, "社区管理范围已保存")
