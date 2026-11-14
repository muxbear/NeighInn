from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)


class SessionStore:
    """Redis-backed sessions with an in-memory fallback for local development.

    The provided dev Redis instance requires authentication which is not part of the
    supplied configuration, so the API starts with the memory store instead of
    blocking startup. The interface is identical when Redis is available.
    """

    def __init__(self) -> None:
        self._memory: dict[str, tuple[dict[str, Any], float]] = {}
        self._redis = None

    async def init(self) -> None:
        if not settings.redis_url:
            return
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            self._redis = client
            logger.info("Redis session store connected")
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - optional dependency
            logger.warning("Redis unavailable, using in-memory sessions: %s", exc)

    async def set(self, token: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        if self._redis is not None:
            await self._redis.setex(f"ni:admin:session:{token}", ttl_seconds, json.dumps(payload))
            return
        self._memory[token] = (payload, datetime.now(UTC).timestamp() + ttl_seconds)

    async def get(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        if self._redis is not None:
            raw = await self._redis.get(f"ni:admin:session:{token}")
            return json.loads(raw) if raw else None
        item = self._memory.get(token)
        if not item:
            return None
        payload, expires_at = item
        if expires_at < datetime.now(UTC).timestamp():
            self._memory.pop(token, None)
            return None
        return payload

    async def delete(self, token: str | None) -> None:
        if not token:
            return
        if self._redis is not None:
            await self._redis.delete(f"ni:admin:session:{token}")
        self._memory.pop(token, None)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()


session_store = SessionStore()
