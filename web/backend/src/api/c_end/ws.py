from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.core.responses import ApiError
from src.core.security import decode_token
from src.core.ws_manager import ws_manager
from src.db.base import SessionLocal
from src.db.models import Conversation, User
from src.services.chat_service import (
    mark_conversation_read,
    message_payload,
    send_chat_message,
)

router = APIRouter(tags=["c:ws"])
logger = logging.getLogger(__name__)


def _frame(action: str, payload: dict) -> str:
    return json.dumps(
        {"v": 1, "action": action, "payload": payload},
        ensure_ascii=False,
    )


@router.websocket("/ws")
async def websocket_channel(ws: WebSocket):
    """移动端长连接（详设 10.3 / ws.service）：
    - 鉴权：query token（JWT accessToken）；
    - 上行：PING / MSG_READ / MSG_SEND / MSG_ACK；
    - 下行：PONG / MSG_PUSH / MSG_ACK / MSG_READ / NOTIFY / ORDER_EVENT；
    - 断线重连与离线消息拉取由端侧负责（HTTP 兜底）。
    """
    token = ws.query_params.get("token", "")
    user_id = decode_token(token)
    if not user_id:
        await ws.close(code=4401)
        return
    await ws.accept()
    ws_manager.connect(user_id, ws)
    await ws.send_text(_frame("PONG", {"connected": True}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            # 新协议 action/payload；兼容旧协议 type/data 一个版本。
            action = frame.get("action") or frame.get("type")
            payload = frame.get("payload")
            if payload is None:
                payload = frame.get("data") or {}
            if not isinstance(payload, dict):
                payload = {}
            if action == "PING":
                await ws.send_text(_frame("PONG", {"ts": payload.get("ts", 0)}))
            elif action == "MSG_READ":
                await _mark_read(user_id, payload)
            elif action == "MSG_SEND":
                await _handle_send(ws, user_id, payload)
            elif action == "MSG_ACK":
                pass  # 客户端确认收到推送（当前无需处理）
            else:
                await ws.send_text(_frame("ERROR", {
                    "code": 40001, "message": "不支持的消息帧", "action": action,
                }))
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(user_id, ws)


async def _mark_read(user_id: int, data: dict) -> None:
    try:
        conversation_id = int(data.get("conversationId", 0) or 0)
    except (TypeError, ValueError):
        return
    if not conversation_id:
        return
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conversation_id)
        if not conv or user_id not in (conv.user_a_id, conv.user_b_id):
            return
        last_seq = int(data.get("lastSeq", conv.last_seq) or 0)
        final_seq = await mark_conversation_read(db, conv, user_id, last_seq)
        await db.commit()
        peer_id = conv.user_b_id if conv.user_a_id == user_id else conv.user_a_id
        await ws_manager.push(peer_id, "MSG_READ", {
            "conversationId": str(conv.id),
            "peerLastReadSeq": final_seq,
        })


async def _handle_send(ws: WebSocket, user_id: int, data: dict) -> None:
    client_msg_id = str(data.get("clientMsgId", "") or "")
    try:
        conversation_id = int(data.get("conversationId", 0) or 0)
    except (TypeError, ValueError):
        await ws.send_text(_frame("ERROR", {
            "code": 40001, "message": "会话 ID 不合法", "clientMsgId": client_msg_id,
        }))
        return
    if not conversation_id:
        await ws.send_text(_frame("ERROR", {
            "code": 40001, "message": "缺少会话 ID", "clientMsgId": client_msg_id,
        }))
        return

    async with SessionLocal() as db:
        conv = await db.get(Conversation, conversation_id)
        sender = await db.get(User, user_id)
        if not conv or not sender or user_id not in (conv.user_a_id, conv.user_b_id):
            await ws.send_text(_frame("ERROR", {
                "code": 40301, "message": "无权访问该会话", "clientMsgId": client_msg_id,
            }))
            return
        try:
            message, _created = await send_chat_message(
                db,
                conversation=conv,
                sender=sender,
                content=str(data.get("content", "")),
                msg_type=str(data.get("type", "TEXT")),
                client_msg_id=client_msg_id,
                image=str(data.get("image", "")),
                extra=data.get("extra") if isinstance(data.get("extra"), dict) else {},
            )
            await db.commit()
            await ws.send_text(_frame("MSG_ACK", {
                "clientMsgId": client_msg_id,
                "messageId": str(message.id),
                "seq": message.seq,
                "createdAt": int(message.created_at.timestamp() * 1000)
                if message.created_at else 0,
                "message": message_payload(message, mine=True, sender=sender),
            }))
        except ApiError as exc:
            await db.rollback()
            await ws.send_text(_frame("ERROR", {
                "code": exc.code,
                "message": exc.message,
                "clientMsgId": client_msg_id,
            }))
        except Exception as exc:  # noqa: BLE001 WS 通道错误不中断连接
            await db.rollback()
            logger.warning("ws MSG_SEND failed: %s", exc)
            await ws.send_text(_frame("ERROR", {
                "code": 50000, "message": "消息发送失败", "clientMsgId": client_msg_id,
            }))
