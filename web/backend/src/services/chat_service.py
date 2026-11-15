"""IM 消息共享服务：HTTP 与 WebSocket 两个入口共用发送逻辑。
client_msg_id 幂等；内容安全审核；落库后向对方在线连接推送 MSG_PUSH。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.responses import ERR_BIZ_RULE, ERR_PARAM, ApiError
from src.core.ws_manager import ws_manager
from src.db.models import Conversation, Message, User
from src.services import ai_audit_service as ai


async def send_chat_message(
    db: AsyncSession,
    *,
    conversation: Conversation,
    sender: User,
    content: str,
    msg_type: str = "TEXT",
    client_msg_id: str = "",
    image: str = "",
    push: bool = True,
) -> tuple[Message, bool]:
    """返回 (message, created)。created=False 表示幂等命中返回既有消息。"""
    if client_msg_id:
        existing = await db.scalar(
            select(Message).where(Message.conversation_id == conversation.id,
                                  Message.sender_id == sender.id,
                                  Message.client_msg_id == client_msg_id).limit(1))
        if existing:
            return existing, False

    content = content.strip()
    if msg_type == "TEXT" and not content:
        raise ApiError(ERR_PARAM, "消息内容不能为空", 400)
    if len(content) > 500:
        raise ApiError(ERR_PARAM, "消息最长 500 字", 400)

    hit = next((kw for kw in ai.BANNED_KEYWORDS if kw in content), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"消息包含违禁内容（{hit}），已被内容安全审核拦截", 422)
    risk = next((p for p in ai.SENSITIVE_PATTERNS if p in content.lower() or p in content), None)

    conversation.last_seq += 1
    conversation.last_message = content[:120] or "[图片]"
    message = Message(
        conversation_id=conversation.id, sender_id=sender.id,
        client_msg_id=client_msg_id[:64], type=msg_type,
        content=content, image_key=image, status="SENT",
        audit_status="PASSED", risk_flag=risk or "", seq=conversation.last_seq,
    )
    db.add(message)
    await db.flush()

    if push:
        peer_id = (conversation.user_b_id if conversation.user_a_id == sender.id
                   else conversation.user_a_id)
        await ws_manager.push(peer_id, "MSG_PUSH", {
            "conversationId": str(conversation.id),
            "message": {
                "id": str(message.id), "senderId": str(sender.id),
                "senderName": sender.nickname, "type": message.type,
                "content": message.content, "seq": message.seq,
            },
        })
    return message, True
