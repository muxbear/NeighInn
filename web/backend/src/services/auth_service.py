"""C 端认证域服务（M01）：短信验证码、登录注册、认证状态计算。

验证码存储由 SMS_CODE_BACKEND 选择：redis（推荐，key 前缀 ni:sms:，重启/多副本不丢）
或 memory（开发降级，重启失效）。两种实现均带 60s 冷却、5 分钟 TTL 与 5 次错误上限
（NF-06 接口防刷）。
"""

from __future__ import annotations

import logging
import random
import time
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.responses import ERR_CONFLICT, ERR_PARAM, ERR_RATE_LIMIT, ApiError
from src.core.security import (
    encrypt_field,
    hmac_index,
    issue_access_token,
    issue_refresh_token,
    mask_phone,
)
from src.db.models import Certification, Community, Resident, User

logger = logging.getLogger(__name__)

SMS_CODE_TTL_SECONDS = 300
SMS_COOLDOWN_SECONDS = 60
SMS_MAX_ATTEMPTS = 5
SMS_REDIS_PREFIX = "ni:sms:"


class SmsCodeStore(Protocol):
    async def init(self) -> None: ...
    async def issue(self, phone: str) -> tuple[str, int]: ...
    async def verify(self, phone: str, code: str) -> bool: ...
    async def clear(self, phone: str) -> None: ...
    async def close(self) -> None: ...


class MemorySmsCodeStore:
    """进程内验证码存储（开发降级；服务重启/多副本会丢失）。"""

    def __init__(self) -> None:
        self._codes: dict[str, tuple[str, float, int, float]] = {}

    async def init(self) -> None: ...

    async def issue(self, phone: str) -> tuple[str, int]:
        now = time.time()
        row = self._codes.get(phone)
        if row and now - row[3] < SMS_COOLDOWN_SECONDS:
            raise ApiError(ERR_RATE_LIMIT, "发送过于频繁，请稍后再试", 429)
        code = f"{random.randint(100000, 999999)}"
        self._codes[phone] = (code, now + SMS_CODE_TTL_SECONDS, 0, now)
        return code, SMS_COOLDOWN_SECONDS

    async def verify(self, phone: str, code: str) -> bool:
        row = self._codes.get(phone)
        if not row:
            return False
        stored, expires_at, attempts, issued_at = row
        if attempts >= SMS_MAX_ATTEMPTS:
            self._codes.pop(phone, None)
            raise ApiError(ERR_RATE_LIMIT, "验证码错误次数过多，请重新获取", 429)
        if time.time() > expires_at:
            self._codes.pop(phone, None)
            return False
        if stored != code:
            self._codes[phone] = (stored, expires_at, attempts + 1, issued_at)
            return False
        self._codes.pop(phone, None)
        return True

    async def clear(self, phone: str) -> None:
        self._codes.pop(phone, None)

    async def close(self) -> None: ...


class RedisSmsCodeStore:
    """Redis 验证码存储：重启/多副本不丢；key 使用 HMAC 索引，避免明文手机号。"""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(url, decode_responses=True)

    async def init(self) -> None:
        await self._client.ping()

    @staticmethod
    def _key(phone: str) -> str:
        return f"{SMS_REDIS_PREFIX}{hmac_index(phone)}"

    async def issue(self, phone: str) -> tuple[str, int]:
        now = time.time()
        key = self._key(phone)
        row = await self._client.hgetall(key)
        if row and now - float(row.get("issuedAt", 0)) < SMS_COOLDOWN_SECONDS:
            raise ApiError(ERR_RATE_LIMIT, "发送过于频繁，请稍后再试", 429)
        code = f"{random.randint(100000, 999999)}"
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            pipe.hset(key, mapping={
                "code": code,
                "expiresAt": str(now + SMS_CODE_TTL_SECONDS),
                "attempts": "0",
                "issuedAt": str(now),
            })
            pipe.expire(key, SMS_CODE_TTL_SECONDS)
            await pipe.execute()
        return code, SMS_COOLDOWN_SECONDS

    async def verify(self, phone: str, code: str) -> bool:
        key = self._key(phone)
        row = await self._client.hgetall(key)
        if not row:
            return False
        if int(row.get("attempts", 0)) >= SMS_MAX_ATTEMPTS:
            await self._client.delete(key)
            raise ApiError(ERR_RATE_LIMIT, "验证码错误次数过多，请重新获取", 429)
        if time.time() > float(row.get("expiresAt", 0)):
            await self._client.delete(key)
            return False
        if row.get("code") != code:
            await self._client.hincrby(key, "attempts", 1)
            return False
        await self._client.delete(key)
        return True

    async def clear(self, phone: str) -> None:
        await self._client.delete(self._key(phone))

    async def close(self) -> None:
        await self._client.aclose()


class FailoverSmsCodeStore:
    """优先 Redis；初始化失败（未配置/认证失败/不可达）时自动降级到进程内存储。

    保证开发环境 Redis 配错不会导致验证码登录不可用；生产应修复 REDIS_URL 以启用持久化。
    """

    def __init__(self) -> None:
        self._fallback = MemorySmsCodeStore()
        self._redis: RedisSmsCodeStore | None = None
        self._active: SmsCodeStore = self._fallback

    async def init(self) -> None:
        if settings.sms_code_backend.lower() != "redis":
            logger.info("短信验证码使用进程内存储（重启失效）")
            return
        if not settings.redis_url:
            logger.warning("SMS_CODE_BACKEND=redis 但未配置 REDIS_URL，验证码降级为进程内存储（重启失效）")
            return
        try:
            redis_store = RedisSmsCodeStore(settings.redis_url)
            await redis_store.init()
        except ImportError:  # pragma: no cover
            logger.warning("redis 依赖不可用，验证码降级为进程内存储（重启失效）")
            return
        except Exception as exc:  # noqa: BLE001 - 连接/认证失败均降级，避免登录不可用
            logger.warning("Redis 验证码存储不可用（%s），降级为进程内存储（重启失效）", exc)
            return
        self._redis = redis_store
        self._active = redis_store
        logger.info("短信验证码使用 Redis 存储")

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
        self._active = self._fallback

    async def issue(self, phone: str) -> tuple[str, int]:
        return await self._active.issue(phone)

    async def verify(self, phone: str, code: str) -> bool:
        return await self._active.verify(phone, code)

    async def clear(self, phone: str) -> None:
        await self._active.clear(phone)


def build_sms_code_store() -> SmsCodeStore:
    return FailoverSmsCodeStore()


sms_code_store: SmsCodeStore = build_sms_code_store()


async def get_or_create_user_by_phone(db: AsyncSession, phone: str) -> tuple[User, bool]:
    """同一手机号唯一账号（M01-01）。不存在则注册。"""
    phone_hash = hmac_index(phone)
    user = await db.scalar(select(User).where(User.phone_hash == phone_hash))
    if user:
        return user, False
    user = User(
        phone_enc=encrypt_field(phone),
        phone_hash=phone_hash,
        nickname=f"邻居{phone[-4:]}",
        status="ACTIVE",
        realname_status="UNVERIFIED",
    )
    db.add(user)
    await db.flush()
    return user, True


def issue_token_pair(user: User) -> dict:
    return {
        "accessToken": issue_access_token(user.id),
        "refreshToken": issue_refresh_token(user.id),
    }


async def latest_certification(
    db: AsyncSession, user_id: int, cert_type: str
) -> Certification | None:
    return await db.scalar(
        select(Certification)
        .where(Certification.user_id == user_id, Certification.type == cert_type)
        .order_by(Certification.id.desc())
        .limit(1)
    )


async def bound_resident(db: AsyncSession, user_id: int) -> Resident | None:
    return await db.scalar(
        select(Resident)
        .where(Resident.user_id == user_id, Resident.certification_status == "VERIFIED")
        .order_by(Resident.id.desc())
        .limit(1)
    )


async def compute_auth_status(db: AsyncSession, user: User) -> dict:
    """移动端 AuthStatusResult（mobile/models/user.model.ts）。

    NOT_LOGIN → LOGGED_IN_UNVERIFIED → VERIFYING → VERIFIED_UNOWNER
      → SUBMITTING_PROOF → PENDING_AUDIT → VERIFIED_OWNER；REJECTED 可重提；FROZEN 冻结。
    """
    if user.status == "FROZEN":
        return {"status": "FROZEN", "realnameVerified": True, "ownerVerified": True,
                "canResubmit": False}

    realname = await latest_certification(db, user.id, "REALNAME")
    realname_verified = bool(realname and realname.status == "VERIFIED")
    owner = await latest_certification(db, user.id, "OWNER_PROOF")
    owner_verified = bool(owner and owner.status == "VERIFIED")

    if realname is None:
        status = "LOGGED_IN_UNVERIFIED"
    elif realname.status == "PENDING" or realname.status == "SUPPLEMENT":
        status = "VERIFYING"
    elif realname.status == "REJECTED":
        return {
            "status": "REJECTED", "realnameVerified": False, "ownerVerified": False,
            "rejectReason": realname.reject_reason, "canResubmit": realname.reject_count < 3,
        }
    elif owner is None:
        status = "VERIFIED_UNOWNER"
    elif owner.status in ("PENDING", "SUPPLEMENT"):
        status = "PENDING_AUDIT"
    elif owner.status == "REJECTED":
        return {
            "status": "REJECTED", "realnameVerified": True, "ownerVerified": False,
            "rejectReason": owner.reject_reason, "canResubmit": owner.reject_count < 3,
        }
    elif owner.status == "FROZEN":
        status = "FROZEN"
    else:
        status = "VERIFIED_OWNER"

    return {
        "status": status,
        "realnameVerified": realname_verified,
        "ownerVerified": owner_verified,
        "canResubmit": True,
    }


async def serialize_profile(db: AsyncSession, user: User) -> dict:
    """移动端 UserProfile。手机号脱敏展示（SRS 9.2）；实名信息不出服务端。"""
    from src.core.security import decrypt_field

    resident = await bound_resident(db, user.id)
    community_name = ""
    if resident:
        community = await db.get(Community, resident.community_id)
        community_name = community.name if community else ""
    auth = await compute_auth_status(db, user)
    phone = decrypt_field(user.phone_enc)
    joined_days = max(0, (datetime.now(UTC).replace(tzinfo=None)
                          - user.registered_at.replace(tzinfo=None)).days) if user.registered_at else 0
    return {
        "id": str(user.id),
        "nickname": user.nickname,
        "phone": mask_phone(phone),
        "email": "",
        "address": "",
        "bio": "",
        "avatarPreset": user.avatar_key or "avatar-person-1",
        "avatarDataUrl": "",
        "showBio": True,
        "shareAddressAfterOrder": False,
        "verified": bool(auth.get("ownerVerified")),
        "creditScore": user.credit_score,
        "creditLevel": user.credit_level,
        "dealCount": 0,
        "communityName": community_name,
        "joinedDays": joined_days,
        "authStatus": auth["status"],
    }


def validate_phone(phone: str) -> None:
    if not phone or len(phone) != 11 or not phone.isdigit() or not phone.startswith("1"):
        raise ApiError(ERR_PARAM, "手机号格式不正确", 400)


async def assert_no_pending_certification(db: AsyncSession, user_id: int, cert_type: str) -> None:
    existing = await latest_certification(db, user_id, cert_type)
    if existing and existing.status in ("PENDING", "SUPPLEMENT"):
        raise ApiError(ERR_CONFLICT, "已有审核中的申请，请耐心等待审核结果", 409)
