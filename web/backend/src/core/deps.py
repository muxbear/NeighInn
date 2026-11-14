from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.responses import ApiError
from src.core.sessions import session_store
from src.db.base import get_db
from src.db.models import (
    AdminUser,
    Permission,
    admin_user_communities,
    admin_user_roles,
    role_permissions,
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


async def get_session_token(request: Request) -> str | None:
    return request.cookies.get(settings.session_cookie_name)


async def get_current_admin(request: Request, db: DbSession) -> AdminUser:
    token = request.cookies.get(settings.session_cookie_name)
    data = await session_store.get(token)
    if not data:
        raise ApiError(40101, "未登录或会话已失效", 401)
    admin = await db.get(AdminUser, int(data["admin_id"]))
    if not admin or admin.status != "ACTIVE":
        raise ApiError(40101, "账号不可用", 401)
    request.state.session_token = token
    request.state.csrf_token = data.get("csrf")
    request.state.admin = admin
    return admin


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]


async def get_permission_codes(db: AsyncSession, admin: AdminUser) -> list[str]:
    if admin.is_super_admin:
        rows = await db.execute(select(Permission.code).where(Permission.status == "ACTIVE"))
        return list(rows.scalars().all())
    rows = await db.execute(
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .join(admin_user_roles, admin_user_roles.c.role_id == role_permissions.c.role_id)
        .where(admin_user_roles.c.admin_user_id == admin.id, Permission.status == "ACTIVE")
    )
    return list(dict.fromkeys(rows.scalars().all()))


async def require_permission(code: str, admin: CurrentAdmin, db: DbSession) -> None:
    if admin.is_super_admin:
        return
    codes = await get_permission_codes(db, admin)
    if code not in codes:
        raise ApiError(40301, "无权限执行该操作", 403)


async def require_csrf(request: Request) -> None:
    if not settings.auth_enforce_csrf or request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    header = request.headers.get("x-csrf-token")
    expected = getattr(request.state, "csrf_token", None)
    if not header or not expected or header != expected:
        raise ApiError(40301, "CSRF 校验失败，请刷新页面后重试", 403)


async def allowed_community_ids(db: AsyncSession, admin: AdminUser) -> set[int] | None:
    if admin.is_super_admin:
        return None
    rows = await db.execute(
        select(admin_user_communities.c.community_id).where(
            admin_user_communities.c.admin_user_id == admin.id
        )
    )
    return set(rows.scalars().all())
