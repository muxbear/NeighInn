"""WebSocket 连接注册中心（单进程）。移动端 ws.service 长连接：
- 鉴权：连接 query 携带 JWT（wss://.../ws?token=...&deviceId=...）；
- 心跳：PING → PONG；
- 下行推送：MSG_PUSH（新消息）、NOTIFY（站内通知）、ORDER_EVENT（订单状态）。

生产多副本时替换为 Redis Pub/Sub 广播（接口不变）。
"""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WsManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}

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

    async def push(self, user_id: int, event: str, payload: dict) -> int:
        """向用户全部在线连接推送 JSON 文本帧；返回送达连接数。"""
        sockets = self._connections.get(user_id) or set()
        delivered = 0
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(json.dumps(
                    {"type": event, "data": payload}, ensure_ascii=False))
                delivered += 1
            except Exception as exc:  # noqa: BLE001 连接随时可能断开，逐个容错
                logger.debug("ws push failed for user %s: %s", user_id, exc)
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)
        return delivered


ws_manager = WsManager()
