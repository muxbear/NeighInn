"""IM 消息共享服务：HTTP 与 WebSocket 两个入口共用发送逻辑。

- client_msg_id 幂等；
- 好友会话按双认证/同小区/未拉黑门禁；
- 会话内 seq 单调递增；
- 内容安全审核；
- 落库后向对方在线连接推送 MSG_PUSH（action/payload 信封）。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_IDEMPOTENT_CONFLICT,
    ERR_PARAM,
    ERR_RATE_LIMIT,
    ApiError,
)
from src.core.ws_manager import ws_manager
from src.db.models import Conversation, Message, User
from src.db.models.common import utcnow
from src.services import ai_audit_service as ai
from src.services.social_service import (
    assert_can_send,
    conversation_peer_id,
    message_preview,
)

# 客户端可发送的消息类型；SYSTEM/ITEM 由服务端内部生成，禁止客户端伪造。
ALLOWED_MESSAGE_TYPES = {"TEXT", "EMOJI", "IMAGE", "VIDEO", "VOICE"}

# 单进程滑动窗口限流；多实例可替换为 Redis 实现。
_RATE_BUCKETS: dict[int, list[float]] = {}


def _check_rate_limit(user_id: int) -> None:
    limit = max(1, settings.neighbor_message_rate_per_minute)
    now = time.monotonic()
    bucket = [stamp for stamp in _RATE_BUCKETS.get(user_id, []) if now - stamp < 60]
    if len(bucket) >= limit:
        raise ApiError(ERR_RATE_LIMIT, "发送太频繁，请稍后再试", 429)
    bucket.append(now)
    _RATE_BUCKETS[user_id] = bucket


def message_payload(message: Message, *, mine: bool, sender: User) -> dict:
    return {
        "id": str(message.id),
        "clientMsgId": message.client_msg_id or None,
        "conversationId": str(message.conversation_id),
        "seq": message.seq,
        "senderId": str(message.sender_id),
        "senderName": sender.nickname if sender else "",
        "senderAvatar": (sender.avatar_key if sender else "") or "avatar-person-1",
        "type": message.type,
        "content": message.content,
        "extra": message.extra or {},
        "image": message.image_key or None,
        "createdAt": int(message.created_at.timestamp() * 1000) if message.created_at else 0,
        "status": message.status,
        "mine": mine,
        "riskFlag": message.risk_flag or None,
    }


def _time_text(dt: datetime | None) -> str:
    if not dt:
        return ""
    delta = datetime.now(UTC).replace(tzinfo=None) - dt.replace(tzinfo=None)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    return dt.strftime("%m-%d")


async def send_chat_message(
    db: AsyncSession,
    *,
    conversation: Conversation,
    sender: User,
    content: str,
    msg_type: str = "TEXT",
    client_msg_id: str = "",
    image: str = "",
    extra: dict | None = None,
    push: bool = True,
) -> tuple[Message, bool]:
    """返回 (message, created)。created=False 表示幂等命中返回既有消息。"""
    msg_type = (msg_type or "TEXT").upper()
    if msg_type not in ALLOWED_MESSAGE_TYPES:
        raise ApiError(ERR_PARAM, "不支持的消息类型", 400)
    if msg_type == "EMOJI" and not settings.neighbor_emoji_enabled:
        raise ApiError(ERR_PARAM, "表情消息暂未开放", 400)

    content = (content or "").strip()
    client_msg_id = (client_msg_id or "").strip()[:64]
    if msg_type == "TEXT" and not content:
        raise ApiError(ERR_PARAM, "消息内容不能为空", 400)
    if msg_type == "EMOJI" and not content:
        raise ApiError(ERR_PARAM, "表情消息缺少表情标识", 400)
    max_length = max(1, settings.neighbor_message_max_length)
    if len(content) > max_length:
        raise ApiError(ERR_PARAM, f"消息最长 {max_length} 字", 400)
    if len(content) > 0 and msg_type in {"TEXT", "EMOJI"}:
        hit = next((kw for kw in ai.BANNED_KEYWORDS if kw in content), None)
        if hit:
            raise ApiError(
                ERR_BIZ_RULE,
                f"消息包含违禁内容（{hit}），已被内容安全审核拦截",
                422,
            )

    if client_msg_id:
        existing = await db.scalar(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.sender_id == sender.id,
                Message.client_msg_id == client_msg_id,
            ).limit(1)
        )
        if existing:
            if existing.content != content or existing.type != msg_type:
                raise ApiError(
                    ERR_IDEMPOTENT_CONFLICT,
                    "同一 clientMsgId 对应了不同的消息内容",
                    409,
                )
            return existing, False

    _check_rate_limit(sender.id)
    await assert_can_send(db, conversation, sender)

    # 行锁保证同一会话并发发送时 seq 唯一且递增。
    locked = await db.scalar(
        select(Conversation).where(Conversation.id == conversation.id).with_for_update()
    )
    if locked is not None:
        conversation = locked

    risk = ""
    if content and msg_type in {"TEXT", "EMOJI"}:
        risk = next(
            (p for p in ai.SENSITIVE_PATTERNS if p in content.lower() or p in content),
            "",
        )

    now = utcnow()
    conversation.last_seq = int(conversation.last_seq or 0) + 1
    conversation.last_message = message_preview(msg_type, content)
    conversation.last_message_type = msg_type
    conversation.last_sender_id = sender.id
    conversation.last_message_at = now
    conversation.updated_at = now

    message = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        client_msg_id=client_msg_id,
        type=msg_type,
        content=content,
        image_key=image,
        extra=extra or {},
        status="SENT",
        audit_status="PASSED",
        risk_flag=risk,
        seq=conversation.last_seq,
        created_at=now,
    )
    db.add(message)
    await db.flush()

    if push:
        peer_id = conversation_peer_id(conversation, sender.id)
        await ws_manager.push(peer_id, "MSG_PUSH", {
            "conversationId": str(conversation.id),
            "message": message_payload(message, mine=False, sender=sender),
        })
    return message, True


async def mark_conversation_read(
    db: AsyncSession, conversation: Conversation, user_id: int, last_seq: int
) -> int:
    """更新已读游标，返回最终游标值；游标不超过会话当前最大 seq。"""
    target = min(max(0, last_seq), int(conversation.last_seq or 0))
    if conversation.user_a_id == user_id:
        current = int(conversation.last_read_seq_a or 0)
        conversation.last_read_seq_a = max(current, target)
        final = conversation.last_read_seq_a
    else:
        current = int(conversation.last_read_seq_b or 0)
        conversation.last_read_seq_b = max(current, target)
        final = conversation.last_read_seq_b
    return final


async def unread_count(db: AsyncSession, conversation: Conversation, user_id: int) -> int:
    peer_id = conversation_peer_id(conversation, user_id)
    my_read = (
        conversation.last_read_seq_a
        if conversation.user_a_id == user_id
        else conversation.last_read_seq_b
    )
    from sqlalchemy import func

    return int(await db.scalar(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_id == peer_id,
            Message.seq > int(my_read or 0),
            Message.deleted_at.is_(None),
        )
    ) or 0)
