"""WebSocket 连接注册中心（单进程）。移动端 ws.service 长连接：
- 鉴权：连接 query 携带 JWT（wss://.../ws?token=...&deviceId=...）；
- 心跳：PING → PONG；
- 下行推送：MSG_PUSH（新消息）、NOTIFY（站内通知）、ORDER_EVENT（订单状态）。

统一信封：{"v": 1, "action": "...", "payload": {...}, "ts": ...}。
生产多副本时在 push() 中追加 Redis Pub/Sub 广播（接口不变）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import WebSocket

from src.core.config import settings

logger = logging.getLogger(__name__)


class WsManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}
        self.instance_id = uuid.uuid4().hex
        self._redis = None
        self._pubsub = None
        self._pubsub_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动 Redis Pub/Sub 广播（多副本）；未配置 Redis 时保持单进程模式。"""
        if not settings.redis_url or self._redis is not None:
            return
        try:
            from redis.asyncio import from_url

            self._redis = from_url(settings.redis_url, decode_responses=True)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe("ws:push")
            self._pubsub_task = asyncio.create_task(self._listen_redis())
            logger.info("ws redis pubsub started instance=%s", self.instance_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ws redis pubsub unavailable: %s", exc)
            self._redis = None
            self._pubsub = None

    async def stop(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            await asyncio.gather(self._pubsub_task, return_exceptions=True)
            self._pubsub_task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("ws pubsub close failed: %s", exc)
            self._pubsub = None
        if self._redis is not None:
            try:
                close = getattr(self._redis, "aclose", None) or self._redis.close
                await close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("ws redis close failed: %s", exc)
            self._redis = None

    async def _listen_redis(self) -> None:
        if self._pubsub is None:
            return
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                data = json.loads(message.get("data") or "{}")
                if data.get("instanceId") == self.instance_id:
                    continue
                await self.push_local(
                    int(data["userId"]), str(data["action"]), data.get("payload") or {},
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("ws redis message ignored: %s", exc)

    def connect(self, user_id: int, ws: WebSocket) -> None:
        self._connections.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        sockets = self._connections.get(user_id)
        if not sockets:
            return
        sockets.discard(ws)
        if not sockets:
            self._connections.pop(user_id, None)

    def online(self, user_id: int) -> bool:
        return bool(self._connections.get(user_id))

    async def push(self, user_id: int, action: str, payload: dict) -> int:
        """向本机连接推送，并通过 Redis 广播给其他实例；返回本机送达连接数。"""
        delivered = await self.push_local(user_id, action, payload)
        if self._redis is not None:
            try:
                await self._redis.publish("ws:push", json.dumps({
                    "instanceId": self.instance_id,
                    "userId": user_id,
                    "action": action,
                    "payload": payload,
                }, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                logger.debug("ws redis publish failed: %s", exc)
        return delivered

    async def push_local(self, user_id: int, action: str, payload: dict) -> int:
        sockets = self._connections.get(user_id) or set()
        delivered = 0
        dead: list[WebSocket] = []
        frame = json.dumps(
            {"v": 1, "action": action, "payload": payload, "ts": int(time.time() * 1000)},
            ensure_ascii=False,
        )
        for ws in sockets:
            try:
                await ws.send_text(frame)
                delivered += 1
            except Exception as exc:  # noqa: BLE001 连接随时可能断开，逐个容错
                logger.debug("ws push failed for user %s: %s", user_id, exc)
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)
        return delivered


ws_manager = WsManager()
