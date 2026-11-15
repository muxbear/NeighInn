"""C 端认证域服务（M01）：短信验证码、登录注册、认证状态计算。

验证码存储由 SMS_CODE_BACKEND 选择：redis（推荐，key 前缀 ni:sms:，重启/多副本不丢）
或 memory（开发降级，重启失效）。两种实现均带 60s 冷却、5 分钟 TTL 与 5 次错误上限
（NF-06 接口防刷）。
"""

from __future__ import annotations

import logging
import random
import time
from datetime import UTC, datetime, timedelta
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
from src.db.models.common import ensure_utc, utcnow

logger = logging.getLogger(__name__)

SMS_CODE_TTL_SECONDS = 300
SMS_COOLDOWN_SECONDS = 60
SMS_MAX_ATTEMPTS = 5
SMS_REDIS_PREFIX = "ni:sms:"
# 账号注销后重新注册冷却期（产品确认：7 个自然日）。
REREGISTER_COOLDOWN_DAYS = 7

# 内置头像键（与 mobile/static/avatars 对齐）；注册完善资料时做白名单校验。
AVATAR_PRESET_KEYS = frozenset({
    "avatar-person-1", "avatar-person-2", "avatar-person-3",
    "avatar-animal-1", "avatar-animal-2", "avatar-animal-3",
    "avatar-landmark-1", "avatar-landmark-2", "avatar-landmark-3",
    "avatar-nature-1", "avatar-nature-2", "avatar-nature-3",
})


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


async def find_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    return await db.scalar(select(User).where(User.phone_hash == hmac_index(phone)))


async def get_or_create_user_by_phone(
    db: AsyncSession, phone: str, channel: str = "sms"
) -> tuple[User, bool]:
    """同一手机号唯一账号（M01-01）。不存在则注册。
    仅注册入口调用；登录入口必须先 find_user_by_phone 判定是否已注册。"""
    user = await find_user_by_phone(db, phone)
    if user:
        return user, False
    user = User(
        phone_enc=encrypt_field(phone),
        phone_hash=hmac_index(phone),
        nickname=f"邻居{phone[-4:]}",
        status="ACTIVE",
        realname_status="UNVERIFIED",
        onboarding_status="NEW",
        registration_channel=channel,
    )
    db.add(user)
    await db.flush()
    return user, True


def record_agreement(user: User, user_version: str, privacy_version: str) -> None:
    """记录协议同意版本与时间（P0 落在 users 主表）。"""
    if not user_version and not privacy_version:
        return
    if user_version:
        user.agreement_version = user_version[:32]
    if privacy_version:
        user.privacy_version = privacy_version[:32]
    user.agreed_at = utcnow()


def assert_phone_can_register(user: User) -> None:
    """注销账号重新注册：7 个自然日冷却（产品确认）；冷却后仍需客服开通。"""
    if user.status != "CANCELLED":
        return
    updated_at = ensure_utc(user.updated_at)
    if updated_at and utcnow() < updated_at + timedelta(days=REREGISTER_COOLDOWN_DAYS):
        raise ApiError(
            ERR_CONFLICT,
            "账号已注销，注销后 7 个自然日内不可重新注册，请联系客服",
            409,
        )
    raise ApiError(ERR_CONFLICT, "账号已注销，请联系客服重新开通", 409)


async def complete_registration(
    db: AsyncSession,
    user: User,
    *,
    nickname: str | None = None,
    avatar_key: str | None = None,
    intent_community_id: int | None = None,
    skip: bool = False,
    finish: bool = False,
) -> dict:
    """注册新人引导：完善资料 / 跳过 / 完成。

    NEW → PROFILE_COMPLETED（保存资料或跳过）→ COMPLETED（关闭成功引导页）。
    存量用户迁移后为 COMPLETED，不会进入本流程。
    """
    if finish:
        user.onboarding_status = "COMPLETED"
        await db.commit()
        return await serialize_profile(db, user)

    if skip:
        if user.onboarding_status != "COMPLETED":
            user.onboarding_status = "PROFILE_COMPLETED"
        await db.commit()
        return await serialize_profile(db, user)

    if user.onboarding_status == "COMPLETED":
        return await serialize_profile(db, user)

    name = (nickname or "").strip()
    if not name:
        raise ApiError(ERR_PARAM, "请填写昵称", 400)
    if len(name) > 16:
        raise ApiError(ERR_PARAM, "昵称最多 16 字", 400)
    if avatar_key and avatar_key not in AVATAR_PRESET_KEYS:
        raise ApiError(ERR_PARAM, "头像不存在，请重新选择", 400)

    if intent_community_id is not None:
        community = await db.get(Community, intent_community_id)
        if not community or community.status != "OPERATING":
            raise ApiError(ERR_PARAM, "所选小区不存在或已停用", 400)
        user.intent_community_id = intent_community_id

    user.nickname = name
    if avatar_key:
        user.avatar_key = avatar_key
    if user.onboarding_status != "COMPLETED":
        user.onboarding_status = "PROFILE_COMPLETED"
    await db.commit()
    return await serialize_profile(db, user)


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


def _cert_payload(cert: Certification | None) -> dict:
    if cert is None:
        return {
            "status": "UNVERIFIED",
            "rejectReason": "",
            "canResubmit": True,
            "submittedAt": 0,
            "certId": "",
        }
    reject_reason = ""
    if cert.status == "REJECTED":
        reject_reason = cert.reject_reason
    elif cert.status == "SUPPLEMENT":
        reject_reason = cert.review_note or "请按要求补充认证材料后重新提交"
    return {
        "status": cert.status,
        "rejectReason": reject_reason,
        "canResubmit": cert.reject_count < 3,
        "submittedAt": int(cert.submitted_at.timestamp() * 1000) if cert.submitted_at else 0,
        "certId": str(cert.id),
    }


async def compute_auth_status(db: AsyncSession, user: User) -> dict:
    """移动端认证状态：实名与住户认证相互独立。

    整体 status 保留给旧页面做流程判断；realname/owner 两个子状态供认证中心与
    标识展示使用。住户认证通过即可成为认证业主，不要求先完成实名。
    """
    realname = await latest_certification(db, user.id, "REALNAME")
    owner = await latest_certification(db, user.id, "OWNER_PROOF")
    realname_verified = bool(realname and realname.status == "VERIFIED")
    owner_verified = bool(owner and owner.status == "VERIFIED")

    realname_payload = _cert_payload(realname)
    owner_payload = _cert_payload(owner)
    if owner is not None and owner.status == "REVOKED":
        owner_payload["rejectReason"] = "住户认证已被撤销，请重新提交认证材料"
    if owner is not None and owner.community_id:
        community = await db.get(Community, owner.community_id)
        owner_payload["communityId"] = str(owner.community_id)
        owner_payload["communityName"] = community.name if community else ""
    else:
        owner_payload["communityId"] = ""
        owner_payload["communityName"] = ""

    if user.status == "FROZEN":
        status = "FROZEN"
        reject_type = ""
    elif owner_verified:
        status = "VERIFIED_OWNER"
        reject_type = ""
    elif owner is not None and owner.status in ("PENDING", "SUPPLEMENT"):
        status = "PENDING_AUDIT"
        reject_type = ""
    elif owner is not None and owner.status == "FROZEN":
        status = "FROZEN"
        reject_type = ""
    elif owner is not None and owner.status in ("REJECTED", "REVOKED"):
        status = "REJECTED"
        reject_type = "OWNER_PROOF"
    elif realname is not None and realname.status in ("PENDING", "SUPPLEMENT"):
        status = "VERIFYING"
        reject_type = ""
    elif realname is not None and realname.status == "REJECTED":
        status = "REJECTED"
        reject_type = "REALNAME"
    elif realname_verified:
        status = "VERIFIED_UNOWNER"
        reject_type = ""
    else:
        status = "LOGGED_IN_UNVERIFIED"
        reject_type = ""

    if reject_type == "OWNER_PROOF":
        can_resubmit = owner_payload["canResubmit"]
        reject_reason = owner_payload["rejectReason"]
    elif reject_type == "REALNAME":
        can_resubmit = realname_payload["canResubmit"]
        reject_reason = realname_payload["rejectReason"]
    else:
        can_resubmit = True
        reject_reason = ""

    return {
        "status": status,
        "realname": realname_payload,
        "owner": owner_payload,
        "realnameVerified": realname_verified,
        "ownerVerified": owner_verified,
        "canResubmit": can_resubmit,
        "rejectReason": reject_reason,
        "rejectType": reject_type,
    }


async def serialize_profile(db: AsyncSession, user: User) -> dict:
    """移动端 UserProfile。手机号脱敏展示（SRS 9.2）；实名信息不出服务端。"""
    from src.core.security import decrypt_field

    resident = await bound_resident(db, user.id)
    community_name = ""
    if resident:
        community = await db.get(Community, resident.community_id)
        community_name = community.name if community else ""
    intent_community = (
        await db.get(Community, user.intent_community_id)
        if user.intent_community_id else None
    )
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
        "realnameVerified": bool(auth.get("realnameVerified")),
        "ownerVerified": bool(auth.get("ownerVerified")),
        "realnameStatus": auth["realname"]["status"],
        "ownerStatus": auth["owner"]["status"],
        "creditScore": user.credit_score,
        "creditLevel": user.credit_level,
        "dealCount": 0,
        "communityName": community_name,
        "joinedDays": joined_days,
        "authStatus": auth["status"],
        "onboardingStatus": user.onboarding_status or "COMPLETED",
        "intentCommunityId": str(user.intent_community_id) if user.intent_community_id else "",
        "intentCommunityName": intent_community.name if intent_community else "",
    }


def validate_phone(phone: str) -> None:
    if not phone or len(phone) != 11 or not phone.isdigit() or not phone.startswith("1"):
        raise ApiError(ERR_PARAM, "手机号格式不正确", 400)


async def assert_no_pending_certification(db: AsyncSession, user_id: int, cert_type: str) -> None:
    existing = await latest_certification(db, user_id, cert_type)
    if existing and existing.status == "PENDING":
        raise ApiError(ERR_CONFLICT, "已有审核中的申请，请耐心等待审核结果", 409)
