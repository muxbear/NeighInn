from __future__ import annotations

import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from src.core.config import settings
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import get_data_scope, get_permission_codes
from src.core.responses import (
    ERR_2FA_INVALID,
    ERR_BAD_CREDENTIALS,
    ERR_FORBIDDEN,
    ERR_PARAM,
    ApiError,
    not_implemented,
    ok,
)
from src.core.security import (
    decrypt_field,
    encrypt_field,
    new_csrf_token,
    new_token,
    verify_password,
    verify_totp,
)
from src.core.sessions import session_store
from src.db.models import (
    AdminUser,
    Community,
    PlatformUser,
    Resident,
    Role,
    admin_user_communities,
    admin_user_roles,
)
from src.db.models.common import ensure_utc, utcnow

router = APIRouter(tags=["admin:auth"])

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15


class LoginIn(BaseModel):
    username: str
    password: str
    otp: str | None = None


class PasswordChangeIn(BaseModel):
    oldPassword: str
    newPassword: str


def _cookie_secure(request: Request) -> bool:
    """会话 Cookie 是否带 Secure：配置显式指定优先，否则按实际访问协议判定。

    生产环境经 HTTPS 反向代理时 X-Forwarded-Proto 为 https，Cookie 保持 Secure；
    直接以 HTTP 暴露（如内网 IP + 端口）时若仍带 Secure，浏览器会直接丢弃 Cookie，
    导致登录成功后所有接口 401。"""
    if settings.session_cookie_secure is not None:
        return settings.session_cookie_secure
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return (forwarded or request.url.scheme) == "https"


def _validate_password_strength(password: str, min_length: int) -> None:
    if len(password) < min_length:
        raise ApiError(
            ERR_PARAM, f"密码最短 {min_length} 位，需包含大小写/数字/符号中的三类", 400)
    kinds = sum(
        bool(re.search(pattern, password))
        for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    )
    if kinds < 3:
        raise ApiError(ERR_PARAM, "密码需包含大小写字母、数字、符号中的至少三类", 400)


def validate_admin_password(password: str) -> None:
    """后台账号统一密码策略：至少 12 位，且大小写字母/数字/符号至少三类。"""
    _validate_password_strength(password, 12)


def validate_initial_admin_password(password: str) -> None:
    """新建后台账号的初始密码策略：至少 6 位，且大小写字母/数字/符号至少三类。"""
    _validate_password_strength(password, 6)


async def _assert_resident_account_active(db: DbSession, admin: AdminUser) -> None:
    """住户授权的后台账号：关联 C 端账号与住户资格必须仍有效。"""
    if not admin.platform_user_id:
        return
    user = await db.get(PlatformUser, admin.platform_user_id)
    if not user or user.status != "ACTIVE":
        raise ApiError(ERR_FORBIDDEN, "关联的移动端账号不可用，请联系管理员", 403)
    if admin.resident_id:
        resident = await db.get(Resident, admin.resident_id)
        if not resident or resident.status != "ACTIVE":
            raise ApiError(ERR_FORBIDDEN, "住户资格已失效，请联系管理员", 403)
        if resident.certification_status in ("FROZEN", "REVOKED"):
            raise ApiError(ERR_FORBIDDEN, "住户认证已失效，请联系管理员", 403)


async def admin_payload(db: DbSession, admin: AdminUser) -> dict:
    role_rows = await db.execute(
        select(Role.code, Role.name)
        .join(admin_user_roles, admin_user_roles.c.role_id == Role.id)
        .where(admin_user_roles.c.admin_user_id == admin.id)
    )
    data_scope = await get_data_scope(db, admin)
    if admin.is_super_admin or data_scope == "ALL":
        community_rows = (await db.execute(
            select(Community.id, Community.name).order_by(Community.id)
        )).all()
    else:
        community_rows = (await db.execute(
            select(Community.id, Community.name)
            .join(admin_user_communities, admin_user_communities.c.community_id == Community.id)
            .where(admin_user_communities.c.admin_user_id == admin.id)
            .order_by(Community.id)
        )).all()
    return {
        "id": str(admin.id),
        "username": admin.username,
        "realName": admin.real_name,
        "avatarText": admin.avatar_text,
        "isSuperAdmin": admin.is_super_admin,
        "twoFactorEnabled": admin.two_factor_enabled,
        "source": admin.source or "MANUAL",
        "dataScope": data_scope,
        "communities": [{"id": str(cid), "name": name} for cid, name in community_rows],
        "residentId": str(admin.resident_id) if admin.resident_id else "",
        "mustChangePassword": bool(admin.must_change_password),
        "roles": [{"code": code, "name": name} for code, name in role_rows.all()],
        "permissions": await get_permission_codes(db, admin),
    }


@router.post("/auth/login")
async def login(payload: LoginIn, request: Request, response: Response, db: DbSession):
    """W01-01：账号密码 + 强制双因素（开启时）。
    登录失败 5 次锁定 15 分钟；连续失败触发图形验证码由前端处理（次数经 40102 返回）。"""
    admin = await db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    if not admin:
        raise ApiError(ERR_BAD_CREDENTIALS, "账号或密码错误", 401)
    locked_until = ensure_utc(admin.locked_until)
    if locked_until and locked_until > utcnow():
        raise ApiError(ERR_FORBIDDEN, f"账号已锁定，请 {LOCK_MINUTES} 分钟后再试", 403)
    if admin.status != "ACTIVE":
        raise ApiError(ERR_FORBIDDEN, "账号已停用", 403)

    if not verify_password(payload.password, admin.password_hash):
        admin.failed_attempts += 1
        if admin.failed_attempts >= MAX_FAILED_ATTEMPTS:
            admin.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
            admin.failed_attempts = 0
        await db.commit()
        raise ApiError(ERR_BAD_CREDENTIALS, "账号或密码错误", 401)

    admin.failed_attempts = 0
    admin.locked_until = None

    if settings.auth_require_2fa and admin.two_factor_enabled:
        if not payload.otp:
            return ok({"twoFactorRequired": True, "challengeId": str(admin.id)})
        secret = decrypt_field(admin.two_factor_secret_enc or "")
        if not verify_totp(secret, payload.otp.strip()):
            # 恢复码兜底（一次性，命中后立即消费）
            from src.core.security import hmac_index

            code_hash = hmac_index(payload.otp.replace("-", "").upper())
            remaining = list(admin.recovery_codes_hash or [])
            if code_hash in remaining:
                remaining.remove(code_hash)
                admin.recovery_codes_hash = remaining
            else:
                raise ApiError(ERR_2FA_INVALID, "动态验证码或恢复码错误", 401)

    await _assert_resident_account_active(db, admin)
    admin.last_login_at = utcnow()
    token = new_token()
    csrf = new_csrf_token()
    await session_store.set(
        token,
        {
            "admin_id": admin.id,
            "csrf": csrf,
            "ip": request.client.host if request.client else "",
            "session_version": int(admin.session_version or 0),
        },
        settings.session_ttl_minutes * 60,
    )
    cookie_kwargs = {
        "httponly": True,
        "samesite": "lax",
        "secure": _cookie_secure(request),
        "max_age": settings.session_ttl_minutes * 60,
        "path": "/",
    }
    response.set_cookie(settings.session_cookie_name, token, **cookie_kwargs)
    response.set_cookie("ni_csrf", csrf, **{**cookie_kwargs, "httponly": False})
    await db.commit()
    return ok({"admin": await admin_payload(db, admin), "csrfToken": csrf})


@router.post("/auth/login/2fa")
async def login_2fa(db: DbSession):
    raise not_implemented("POST /auth/login/2fa（独立挑战式 2FA，登录接口已内联支持）")


@router.post("/auth/2fa/send-sms")
async def send_2fa_sms(db: DbSession):
    raise not_implemented("POST /auth/2fa/send-sms（短信兜底通道，Phase 2）")


@router.post("/auth/2fa/bind")
async def bind_2fa(admin: CurrentAdmin, db: DbSession):
    """绑定 TOTP（W01-01）：生成密钥与 8 个一次性恢复码（哈希存储）。
    返回密钥与 otpauth URI 供扫码；需调用 verify-bind 确认后才会启用。"""
    from src.core.security import hmac_index, new_totp_secret, totp_uri

    secret = new_totp_secret()
    admin.two_factor_secret_enc = encrypt_field(secret)
    recovery_codes = [f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
                      for _ in range(8)]
    admin.recovery_codes_hash = [hmac_index(code.replace("-", "")) for code in recovery_codes]
    admin.two_factor_enabled = False
    await db.commit()
    return ok({
        "secret": secret,
        "otpauthUrl": totp_uri(secret, admin.username),
        "recoveryCodes": recovery_codes,
        "enabled": False,
    }, "请用验证器扫码，并输入动态码完成绑定")


class VerifyBindIn(BaseModel):
    otp: str


@router.post("/auth/2fa/verify-bind")
async def verify_bind_2fa(payload: VerifyBindIn, admin: CurrentAdmin, db: DbSession):
    """确认绑定：动态码校验通过后启用 2FA；此后登录必须提供动态码或恢复码。"""
    secret = decrypt_field(admin.two_factor_secret_enc or "")
    if not secret:
        raise ApiError(ERR_PARAM, "请先调用 bind 获取密钥", 400)
    if not verify_totp(secret, payload.otp.strip()):
        raise ApiError(ERR_2FA_INVALID, "动态验证码错误", 401)
    admin.two_factor_enabled = True
    await db.commit()
    return ok({"enabled": True}, "双因素认证已启用")


@router.get("/auth/me")
async def me(admin: CurrentAdmin, db: DbSession):
    return ok({"admin": await admin_payload(db, admin)})


@router.get("/auth/csrf")
async def csrf(request: Request):
    return ok({"csrfToken": getattr(request.state, "csrf_token", None)})


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(settings.session_cookie_name)
    await session_store.delete(token)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("ni_csrf", path="/")
    return ok(None, "已退出登录")


@router.post("/auth/password/change")
async def change_password(payload: PasswordChangeIn, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    from src.core.security import hash_password

    if not verify_password(payload.oldPassword, admin.password_hash):
        raise ApiError(ERR_BAD_CREDENTIALS, "原密码错误", 401)
    validate_admin_password(payload.newPassword)
    if payload.oldPassword == payload.newPassword:
        raise ApiError(ERR_PARAM, "新密码不能与原密码相同", 400)
    admin.password_hash = hash_password(payload.newPassword)
    admin.must_change_password = False
    admin.session_version = int(admin.session_version or 0) + 1
    await db.commit()
    # 当前会话同步到新版本，其他旧会话因版本不一致立即失效。
    token = getattr(request.state, "session_token", None)
    if token:
        await session_store.set(
            token,
            {
                "admin_id": admin.id,
                "csrf": getattr(request.state, "csrf_token", None),
                "ip": request.client.host if request.client else "",
                "session_version": int(admin.session_version),
            },
            settings.session_ttl_minutes * 60,
        )
    return ok({"mustChangePassword": False}, "密码已更新")
