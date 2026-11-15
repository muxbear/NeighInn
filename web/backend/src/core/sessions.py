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


def build_session_store() -> SessionStore:
    if settings.redis_url:
        try:
            return RedisSessionStore(settings.redis_url)
        except ImportError:  # pragma: no cover
            logger.warning("redis 依赖不可用，管理端会话降级为进程内内存（重启失效）")
    else:
        logger.warning("未配置 REDIS_URL，管理端会话使用进程内内存（重启失效）")
    return MemorySessionStore()


session_store: SessionStore = build_session_store()
