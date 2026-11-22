"""住户 ↔ C 端账号 ↔ 后台账号的关联与凭证工具。

授权主体仍是 ``admin_users``；本模块只负责在需要时自动补齐
``platform_users`` 账号并把 ``admin_users.platform_user_id/resident_id`` 关联起来。
"""

from __future__ import annotations

import secrets
import string

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.responses import ERR_BIZ_RULE, ERR_CONFLICT, ApiError
from src.core.security import decrypt_field, encrypt_field, hmac_index
from src.db.models import (
    AdminUser,
    PlatformUser,
    Resident,
    admin_user_communities,
)

PASSWORD_GROUPS = (
    string.ascii_uppercase,
    string.ascii_lowercase,
    string.digits,
    "@#$%&*!?",
)


def generate_initial_password(length: int = 14) -> str:
    """生成满足后台密码策略的随机初始密码（仅返回一次，不落明文）。"""
    chars = [secrets.choice(group) for group in PASSWORD_GROUPS]
    pool = "".join(PASSWORD_GROUPS)
    while len(chars) < length:
        chars.append(secrets.choice(pool))
    for index in range(len(chars) - 1, 0, -1):
        target = secrets.randbelow(index + 1)
        chars[index], chars[target] = chars[target], chars[index]
    return "".join(chars)


async def ensure_platform_user_for_resident(
    db: AsyncSession, resident: Resident
) -> tuple[PlatformUser, bool]:
    """确保住户有可登录移动端的平台账号，返回 (账号, 是否新建)。

    优先使用 resident.user_id；否则按手机号哈希匹配；仍找不到则用档案手机号创建。
    """
    if resident.user_id:
        user = await db.get(PlatformUser, resident.user_id)
        if user:
            return user, False
        resident.user_id = None

    phone = decrypt_field(resident.phone_enc or "")
    phone_hash = resident.phone_hash or (hmac_index(phone) if phone else "")
    if not phone_hash:
        raise ApiError(
            ERR_BIZ_RULE,
            "住户缺少手机号，无法开通移动端账号，请先补充手机号",
            422,
        )

    user = await db.scalar(
        select(PlatformUser).where(PlatformUser.phone_hash == phone_hash)
    )
    if user:
        resident.user_id = user.id
        if not resident.phone_hash:
            resident.phone_hash = phone_hash
        return user, False

    if not phone:
        raise ApiError(
            ERR_BIZ_RULE,
            "住户手机号不可用，无法开通移动端账号，请先补充手机号",
            422,
        )
    user = PlatformUser(
        phone_enc=encrypt_field(phone),
        phone_hash=phone_hash,
        nickname=resident.name or f"邻居{phone[-4:]}",
        status="ACTIVE",
        realname_status="UNVERIFIED",
        onboarding_status="NEW",
        registration_channel="admin",
    )
    db.add(user)
    await db.flush()
    resident.user_id = user.id
    if not resident.phone_hash:
        resident.phone_hash = phone_hash
    return user, True


async def add_admin_community_scope(
    db: AsyncSession, admin_id: int, community_id: int
) -> None:
    """确保管理员的数据范围包含指定社区（已存在时保持幂等）。"""
    exists = await db.scalar(
        select(admin_user_communities.c.community_id).where(
            admin_user_communities.c.admin_user_id == admin_id,
            admin_user_communities.c.community_id == community_id,
        )
    )
    if exists is not None:
        return
    await db.execute(insert(admin_user_communities).values(
        admin_user_id=admin_id, community_id=community_id))


async def remove_admin_community_scope(
    db: AsyncSession, admin_id: int, community_id: int
) -> None:
    await db.execute(delete(admin_user_communities).where(
        admin_user_communities.c.admin_user_id == admin_id,
        admin_user_communities.c.community_id == community_id,
    ))


async def bind_admin_to_resident(
    db: AsyncSession, admin_row: AdminUser, resident: Resident
) -> tuple[PlatformUser, bool]:
    """把后台账号绑定到住户及其平台账号；返回 (平台账号, 是否新建)。

    同时把住户所在社区写入 ``admin_user_communities``：手工账号默认不再在
    表单里选择「可访问社区」，OWN_COMMUNITY 角色只有绑定住户后才有本社区。
    改绑其他住户时移除原住户社区，避免残留越权范围。
    """
    if resident.status != "ACTIVE":
        raise ApiError(ERR_BIZ_RULE, "住户已停用或已离开，不能绑定", 422)

    user, created = await ensure_platform_user_for_resident(db, resident)
    if user.status != "ACTIVE":
        raise ApiError(ERR_BIZ_RULE, "关联的移动端账号不可用", 422)

    existing = await db.scalar(
        select(AdminUser).where(
            AdminUser.platform_user_id == user.id,
            AdminUser.id != admin_row.id,
        )
    )
    if existing:
        raise ApiError(ERR_CONFLICT, "该住户已绑定其他后台账号", 409)

    previous = (await db.get(Resident, admin_row.resident_id)
                if admin_row.resident_id else None)
    admin_row.platform_user_id = user.id
    admin_row.resident_id = resident.id
    if previous and previous.community_id != resident.community_id:
        await remove_admin_community_scope(db, admin_row.id, previous.community_id)
    await add_admin_community_scope(db, admin_row.id, resident.community_id)
    return user, created


async def unbind_admin_from_resident(db: AsyncSession, admin_row: AdminUser) -> None:
    """解除后台账号与住户的关联，并移除原住户社区的数据范围。"""
    previous = (await db.get(Resident, admin_row.resident_id)
                if admin_row.resident_id else None)
    if previous:
        await remove_admin_community_scope(db, admin_row.id, previous.community_id)
    admin_row.platform_user_id = None
    admin_row.resident_id = None


async def next_admin_username(db: AsyncSession, user_id: int) -> str:
    """住户授权账号默认用户名 u{userId 四位补零}，满足最短 3 位，冲突时追加序号。"""
    base = f"u{user_id:04d}"
    candidate = base
    suffix = 2
    while await db.scalar(select(AdminUser.id).where(AdminUser.username == candidate)):
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate
