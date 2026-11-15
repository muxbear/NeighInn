from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from src.core.config import settings

_hasher = PasswordHasher()


# ---- 密码（Argon2id，后台详设 5.9.3） ----
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, ValueError):
        return False


# ---- 随机令牌 ----
def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


# ---- C 端 JWT（移动端 Authorization: Bearer，SRS 8.3） ----
def issue_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def issue_refresh_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "typ": "refresh",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> int | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != expected_type:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None


# ---- 2FA TOTP（W01-01：30s、±1 窗口） ----
def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="邻里小栈后台")


# ---- 敏感字段加密/哈希（SRS 9.2：SM4/AES-256 + HMAC 查重） ----
def hmac_index(value: str) -> str:
    """手机号/身份证查重索引（不可逆、可匹配）。"""
    return hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def encrypt_field(value: str) -> str:
    """敏感字段加密占位。生产接入 KMS/国密 SM4（AES-256-GCM 亦可）。
    当前 dev 实现为可逆混淆，严禁视为安全实现。"""
    if not value:
        return ""
    import base64

    key = hashlib.sha256(settings.secret_key.encode()).digest()
    raw = value.encode()
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return base64.urlsafe_b64encode(xored).decode()


def decrypt_field(value: str) -> str:
    if not value:
        return ""
    import base64

    key = hashlib.sha256(settings.secret_key.encode()).digest()
    raw = base64.urlsafe_b64decode(value.encode())
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode()


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "****"


def mask_id_card(id_card: str) -> str:
    return f"{id_card[:3]}{'*' * 11}{id_card[-4:]}" if len(id_card) >= 8 else "****"
