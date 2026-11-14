from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from src.core.config import settings
from src.core.deps import CurrentAdmin, DbSession, get_permission_codes
from src.core.responses import ApiError, ok
from src.core.security import new_csrf_token, new_token, verify_password
from src.core.sessions import session_store
from src.db.models import AdminUser, Role, admin_user_roles

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str
    otp: str | None = None


async def admin_payload(db: DbSession, admin: AdminUser) -> dict:
    role_rows = await db.execute(
        select(Role.code, Role.name)
        .join(admin_user_roles, admin_user_roles.c.role_id == Role.id)
        .where(admin_user_roles.c.admin_user_id == admin.id)
    )
    roles = [{"code": code, "name": name} for code, name in role_rows.all()]
    permissions = await get_permission_codes(db, admin)
    return {
        "id": str(admin.id),
        "username": admin.username,
        "realName": admin.real_name,
        "avatarText": admin.avatar_text,
        "isSuperAdmin": admin.is_super_admin,
        "roles": roles,
        "permissions": permissions,
    }


@router.post("/login")
async def login(payload: LoginIn, response: Response, db: DbSession):
    admin = await db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    if not admin or not verify_password(payload.password, admin.password_hash):
        raise ApiError(40102, "账号或密码错误", 401)
    if admin.status != "ACTIVE":
        raise ApiError(40301, "账号已停用", 403)
    if settings.auth_require_2fa and admin.two_factor_enabled and not payload.otp:
        return ok({"twoFactorRequired": True, "challengeId": str(admin.id)})
    token = new_token()
    csrf = new_csrf_token()
    await session_store.set(
        token,
        {"admin_id": admin.id, "csrf": csrf, "created_at": __import__("time").time()},
        settings.session_ttl_minutes * 60,
    )
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "prod",
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    response.set_cookie(
        "ni_csrf",
        csrf,
        httponly=False,
        samesite="lax",
        secure=settings.app_env == "prod",
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    return ok({"admin": await admin_payload(db, admin), "csrfToken": csrf})


@router.get("/me")
async def me(admin: CurrentAdmin, db: DbSession):
    return ok({"admin": await admin_payload(db, admin)})


@router.get("/csrf")
async def csrf(request: Request):
    return ok({"csrfToken": getattr(request.state, "csrf_token", None)})


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(settings.session_cookie_name)
    await session_store.delete(token)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("ni_csrf", path="/")
    return ok(None, "已退出登录")
