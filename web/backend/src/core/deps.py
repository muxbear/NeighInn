from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.responses import (
    ERR_FORBIDDEN,
    ERR_MUST_CHANGE_PASSWORD,
    ERR_UNAUTHORIZED,
    ApiError,
)
from src.core.security import decode_token
from src.core.sessions import session_store
from src.db.base import get_db
from src.db.models import AdminUser, User

DbSession = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


# ---- C 端：移动端 JWT（Authorization: Bearer，SRS 8.3） ----
async def get_current_user(request: Request, db: DbSession) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise ApiError(ERR_UNAUTHORIZED, "未登录或 Token 已失效", 401)
    user_id = decode_token(auth[7:].strip())
    if not user_id:
        raise ApiError(ERR_UNAUTHORIZED, "未登录或 Token 已失效", 401)
    user = await db.get(User, user_id)
    if not user or user.status != "ACTIVE":
        raise ApiError(ERR_UNAUTHORIZED, "账号不可用", 401)
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(request: Request, db: DbSession) -> User | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    user_id = decode_token(auth[7:].strip())
    if not user_id:
        return None
    return await db.get(User, user_id)


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


# ---- 管理端：HttpOnly Cookie 会话 + CSRF（SRS 8.3、后台详设 5.9.1） ----
# 首次登录强制改密期间只放行自助接口，避免绕过改密直接访问业务数据。
MUST_CHANGE_PASSWORD_ALLOWED = (
    "/auth/me",
    "/auth/password/change",
    "/auth/logout",
    "/auth/csrf",
)


async def get_current_admin(request: Request, db: DbSession) -> AdminUser:
    token = request.cookies.get(settings.session_cookie_name)
    data = await session_store.get(token)
    if not data:
        raise ApiError(ERR_UNAUTHORIZED, "未登录或会话已失效", 401)
    admin = await db.get(AdminUser, int(data["admin_id"]))
    if not admin or admin.status != "ACTIVE":
        raise ApiError(ERR_UNAUTHORIZED, "账号不可用", 401)
    # 撤销授权、停用、重置密码会自增版本，旧 Cookie 会话立即失效。
    if int(data.get("session_version", 0)) != int(admin.session_version or 0):
        raise ApiError(ERR_UNAUTHORIZED, "会话已失效，请重新登录", 401)
    if admin.must_change_password and not any(
        request.url.path.endswith(path) for path in MUST_CHANGE_PASSWORD_ALLOWED
    ):
        raise ApiError(
            ERR_MUST_CHANGE_PASSWORD,
            "首次登录需先修改初始密码",
            403,
        )
    request.state.session_token = token
    request.state.csrf_token = data.get("csrf")
    request.state.admin = admin
    return admin


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]


def require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    header = request.headers.get("x-csrf-token")
    expected = getattr(request.state, "csrf_token", None)
    if not header or not expected or header != expected:
        raise ApiError(ERR_FORBIDDEN, "CSRF 校验失败，请刷新页面后重试", 403)
