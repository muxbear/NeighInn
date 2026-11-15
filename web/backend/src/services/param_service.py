"""参数服务（W04-05）：后台参数配置 → 运行时读取 → 移动端 AppConfig 下发。

读取链：parameter_keys(code) → parameter_items(status=启用) 最新值；
进程内缓存 30s，参数「发布」时失效（publish 动作写审计并清缓存）。
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ParameterItem, ParameterKey

_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 30.0


def invalidate_cache() -> None:
    _cache.clear()


async def get_param(db: AsyncSession, key_code: str, default: str) -> str:
    """读取参数项当前生效值；不存在或停用返回 default。"""
    cached = _cache.get(key_code)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    key = await db.scalar(select(ParameterKey).where(ParameterKey.code == key_code,
                                                     ParameterKey.status == "启用"))
    value = default
    if key:
        item = await db.scalar(
            select(ParameterItem)
            .where(ParameterItem.parameter_key_id == key.id,
                   ParameterItem.status == "启用")
            .order_by(ParameterItem.updated_at.desc())
            .limit(1))
        if item:
            value = item.value
    _cache[key_code] = (time.time(), value)
    return value


async def get_int(db: AsyncSession, key_code: str, default: int) -> int:
    try:
        return int(await get_param(db, key_code, str(default)))
    except ValueError:
        return default


async def get_float(db: AsyncSession, key_code: str, default: float) -> float:
    try:
        return float(await get_param(db, key_code, str(default)))
    except ValueError:
        return default


async def get_bool(db: AsyncSession, key_code: str, default: bool) -> bool:
    return (await get_param(db, key_code, "true" if default else "false")).lower() == "true"


async def app_config_bundle(db: AsyncSession) -> dict:
    """移动端 AppConfig（mobile/models/app.model.ts）。"""
    return {
        "nearbyRadiusKm": await get_float(db, "community.nearby.radius_km", 3.0),
        "maxCommunities": await get_int(db, "community.nearby.max_count", 10),
        "maxItemImages": await get_int(db, "item.photos.max", 12),
        "minItemImages": await get_int(db, "item.photos.min", 3),
        "maxLifeImages": 9,
        "maxVideoSeconds": 60,
        "payTimeoutMinutes": await get_int(db, "order.pay.timeout_minutes", 30),
        "appointmentAutoCancelHours": await get_int(db, "order.confirm.timeout_hours", 48),
        "supportPhone": "400-800-2026",
    }
