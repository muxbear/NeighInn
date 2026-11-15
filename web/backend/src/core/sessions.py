from __future__ import annotations

import logging
import time
from typing import Protocol

from src.core.config import settings

logger = logging.getLogger(__name__)


class SessionStore(Protocol):
    async def init(self) -> None: ...
    async def close(self) -> None: ...
    async def set(self, token: str, data: dict, ttl: int) -> None: ...
    async def get(self, token: str | None) -> dict | None: ...
    async def delete(self, token: str | None) -> None: ...


class MemorySessionStore:
    """进程内会话（开发降级）。生产必须配置 REDIS_URL。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, dict]] = {}

    async def init(self) -> None: ...
    async def close(self) -> None: ...

    async def set(self, token: str, data: dict, ttl: int) -> None:
        self._data[token] = (time.time() + ttl, data)

    async def get(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self._data.get(token)
        if not row:
            return None
        expires_at, data = row
        if expires_at < time.time():
            self._data.pop(token, None)
            return None
        return data

    async def delete(self, token: str | None) -> None:
        if token:
            self._data.pop(token, None)


class RedisSessionStore:
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._client = aioredis.from_url(url, decode_responses=True)

    async def init(self) -> None:
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()

    async def set(self, token: str, data: dict, ttl: int) -> None:
        import json

        await self._client.set(f"ni:admin:session:{token}", json.dumps(data), ex=ttl)

    async def get(self, token: str | None) -> dict | None:
        import json

        if not token:
            return None
        raw = await self._client.get(f"ni:admin:session:{token}")
        return json.loads(raw) if raw else None

    async def delete(self, token: str | None) -> None:
        if token:
            await self._client.delete(f"ni:admin:session:{token}")


class FailoverSessionStore:
    """优先 Redis；初始化失败（未配置/认证失败/不可达）时自动降级到进程内会话。

    保证开发环境 Redis 配错不会导致服务无法启动；生产应修复 REDIS_URL 以恢复多副本会话。
    """

    def __init__(self) -> None:
        self._fallback = MemorySessionStore()
        self._redis: RedisSessionStore | None = None
        self._active: SessionStore = self._fallback

    @property
    def backend_name(self) -> str:
        return "redis" if self._active is self._redis else "memory"

    async def init(self) -> None:
        if not settings.redis_url:
            logger.warning("未配置 REDIS_URL，管理端会话使用进程内内存（重启失效）")
            return
        try:
            redis_store = RedisSessionStore(settings.redis_url)
            await redis_store.init()
        except ImportError:  # pragma: no cover
            logger.warning("redis 依赖不可用，管理端会话降级为进程内内存（重启失效）")
            return
        except Exception as exc:  # noqa: BLE001 - 连接/认证失败均降级，避免服务无法启动
            logger.warning("Redis 会话存储不可用（%s），降级为进程内内存（重启失效）", exc)
            return
        self._redis = redis_store
        self._active = redis_store
        logger.info("管理端会话使用 Redis 存储")

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
        self._active = self._fallback

    async def set(self, token: str, data: dict, ttl: int) -> None:
        await self._active.set(token, data, ttl)

    async def get(self, token: str | None) -> dict | None:
        return await self._active.get(token)

    async def delete(self, token: str | None) -> None:
        await self._active.delete(token)


def build_session_store() -> SessionStore:
    return FailoverSessionStore()


session_store: SessionStore = build_session_store()
