from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ERR_DATA_SCOPE, ERR_FORBIDDEN, ApiError
from src.db.models import (
    AdminUser,
    AdminUserRegionGrant,
    Community,
    Permission,
    Region,
    Role,
    admin_user_communities,
    admin_user_roles,
    role_permissions,
)


async def get_permission_codes(db: AsyncSession, admin: AdminUser) -> list[str]:
    if admin.is_super_admin:
        rows = await db.execute(select(Permission.code).where(Permission.status == "ACTIVE"))
        return list(rows.scalars().all())
    rows = await db.execute(
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .join(admin_user_roles, admin_user_roles.c.role_id == role_permissions.c.role_id)
        .join(Role, Role.id == admin_user_roles.c.role_id)
        .where(
            admin_user_roles.c.admin_user_id == admin.id,
            Permission.status == "ACTIVE",
            Role.status == "ACTIVE",
        )
    )
    return list(dict.fromkeys(rows.scalars().all()))


async def get_data_scope(db: AsyncSession, admin: AdminUser) -> str:
    """多角色取并集，ALL 优先级最高（后台详设 5.9.2）。"""
    if admin.is_super_admin:
        return "ALL"
    rows = await db.execute(
        select(Role.data_scope)
        .join(admin_user_roles, admin_user_roles.c.role_id == Role.id)
        .where(admin_user_roles.c.admin_user_id == admin.id, Role.status == "ACTIVE")
    )
    scopes = list(rows.scalars().all())
    if "ALL" in scopes:
        return "ALL"
    if "COMMUNITY_SET" in scopes:
        return "COMMUNITY_SET"
    if "OWN_COMMUNITY" in scopes:
        return "OWN_COMMUNITY"
    return "SELF"


async def region_granted_community_ids(db: AsyncSession, admin_id: int) -> set[int]:
    """展开后台账号的“整个区划”授权，返回其下全部社区 ID。

    社区档案的 ``region_id`` 指向区县、``street_id`` 指向街道；区划授权可能
    落在省/市/区县/街道任一层级，因此统一按区划子树匹配这两个字段。
    """
    has_grant = await db.scalar(
        select(AdminUserRegionGrant.id)
        .where(AdminUserRegionGrant.admin_user_id == admin_id)
        .limit(1)
    )
    if not has_grant:
        return set()

    region_scope = (
        select(AdminUserRegionGrant.region_id.label("region_id"))
        .where(AdminUserRegionGrant.admin_user_id == admin_id)
        .cte(name="admin_region_scope", recursive=True)
    )
    region_scope = region_scope.union_all(
        select(Region.id).where(Region.parent_id == region_scope.c.region_id)
    )
    region_ids = select(region_scope.c.region_id)
    rows = await db.execute(
        select(Community.id).where(or_(
            Community.region_id.in_(region_ids),
            Community.street_id.in_(region_ids),
        ))
    )
    return set(rows.scalars().all())


async def allowed_community_ids(db: AsyncSession, admin: AdminUser) -> set[int] | None:
    """None 表示全部社区可见。仓储查询必须以此过滤，禁止在 Router 手工拼 community_id。

    受限账号的可见社区 = 指定社区集合（admin_user_communities）
    ∪ 区划授权动态展开的社区（admin_user_region_grants）。
    """
    if admin.is_super_admin:
        return None
    scope = await get_data_scope(db, admin)
    if scope == "ALL":
        return None
    rows = await db.execute(
        select(admin_user_communities.c.community_id).where(
            admin_user_communities.c.admin_user_id == admin.id
        )
    )
    explicit = set(rows.scalars().all())
    return explicit | await region_granted_community_ids(db, admin.id)


async def assert_community_allowed(db: AsyncSession, admin: AdminUser, community_id: int) -> None:
    allowed = await allowed_community_ids(db, admin)
    if allowed is not None and community_id not in allowed:
        raise ApiError(ERR_DATA_SCOPE, "数据范围越界", 403)


async def resolve_community_scope(
    db: AsyncSession, admin: AdminUser, requested: int | None
) -> int | None | set[int]:
    """解析列表接口的社区范围。

    - ALL：返回请求值（None 表示不过滤）；
    - 受限范围：请求值必须在允许集合内，未传则返回允许集合；
    - 空集合由调用方渲染为空列表，不能退化成“不过滤”。
    """
    allowed = await allowed_community_ids(db, admin)
    if allowed is None:
        return requested
    if requested is not None:
        if requested not in allowed:
            raise ApiError(ERR_DATA_SCOPE, "数据范围越界", 403)
        return requested
    return allowed


def community_scope_conditions(scope: int | None | set[int], column) -> list:
    """把 resolve_community_scope 的结果转成 SQLAlchemy 条件列表。

    - None：不过滤（ALL）；
    - int：精确匹配；
    - set：IN 过滤；空集合生成恒假条件，返回空列表而不是泄露全量数据。
    """
    if isinstance(scope, int):
        return [column == scope]
    if isinstance(scope, set):
        return [column.in_(scope)]
    return []


def require_permission(code: str):
    """路由级权限校验依赖（W01-02：精确到菜单与操作按钮）。
    用法：@router.post(..., dependencies=[Depends(require_permission("community:item:review"))])
    或：admin: AdminWithPerm = Depends(require_permission("..."))"""

    async def checker(db: DbSession, admin: CurrentAdmin) -> AdminUser:
        if admin.is_super_admin:
            return admin
        codes = await get_permission_codes(db, admin)
        if code not in codes:
            raise ApiError(ERR_FORBIDDEN, "无权限执行该操作", 403)
        return admin

    return checker


def require_any_permission(*codes: str):
    """任一权限满足即可（用于跨内容域的共享能力，如媒体上传）。

    示例：生活内容与邻里互助都需要上传媒体，但分别归属
    ``community:life:update`` / ``community:help:update``。
    """

    async def checker(db: DbSession, admin: CurrentAdmin) -> AdminUser:
        if admin.is_super_admin:
            return admin
        admin_codes = set(await get_permission_codes(db, admin))
        if not any(code in admin_codes for code in codes):
            raise ApiError(ERR_FORBIDDEN, "无权限执行该操作", 403)
        return admin

    return checker


Perm = Annotated[AdminUser, Depends()]
