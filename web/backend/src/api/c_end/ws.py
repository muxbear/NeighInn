from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.core.security import decode_token
from src.core.ws_manager import ws_manager
from src.db.base import SessionLocal
from src.db.models import Conversation

router = APIRouter(tags=["c:ws"])
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_channel(ws: WebSocket):
    """移动端长连接（详设 10.3 / ws.service）：
    - 鉴权：query token（JWT accessToken）；
    - 上行：PING / MSG_READ / MSG_SEND / MSG_ACK；下行：PONG / MSG_PUSH / NOTIFY / ORDER_EVENT；
    - 断线重连与离线消息拉取由端侧负责（HTTP 兜底）。"""
    token = ws.query_params.get("token", "")
    user_id = decode_token(token)
    if not user_id:
        await ws.close(code=4401)
        return
    await ws.accept()
    ws_manager.connect(user_id, ws)
    await ws.send_text(json.dumps({"type": "PONG", "data": {"connected": True}},
                                  ensure_ascii=False))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            frame_type = frame.get("type")
            data = frame.get("data") or {}
            if frame_type == "PING":
                await ws.send_text(json.dumps({"type": "PONG", "data": {}}, ensure_ascii=False))
            elif frame_type == "MSG_READ":
                await _mark_read(user_id, data)
            elif frame_type == "MSG_SEND":
                await _handle_send(user_id, data)
            elif frame_type == "MSG_ACK":
                pass  # 客户端确认收到推送（当前无需处理）
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(user_id, ws)


async def _mark_read(user_id: int, data: dict) -> None:
    from sqlalchemy import update

    from src.db.models import Message

    conversation_id = int(data.get("conversationId", 0) or 0)
    if not conversation_id:
        return
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conversation_id)
        if not conv or user_id not in (conv.user_a_id, conv.user_b_id):
            return
        peer_id = conv.user_b_id if conv.user_a_id == user_id else conv.user_a_id
        await db.execute(
            update(Message)
            .where(Message.conversation_id == conv.id, Message.sender_id == peer_id,
                   Message.status != "READ")
            .values(status="READ"))
        await db.commit()


async def _handle_send(user_id: int, data: dict) -> None:
    from src.db.models import User
    from src.services.chat_service import send_chat_message

    conversation_id = int(data.get("conversationId", 0) or 0)
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conversation_id)
        sender = await db.get(User, user_id)
        if not conv or not sender or user_id not in (conv.user_a_id, conv.user_b_id):
            return
        try:
            await send_chat_message(
                db, conversation=conv, sender=sender,
                content=str(data.get("content", "")),
                msg_type=str(data.get("type", "TEXT")),
                client_msg_id=str(data.get("clientMsgId", "")),
                image=str(data.get("image", "")))
            await db.commit()
        except Exception as exc:  # noqa: BLE001 WS 通道错误不中断连接，回执由客户端 ACK 处理
            await db.rollback()
            logger.warning("ws MSG_SEND failed: %s", exc)
