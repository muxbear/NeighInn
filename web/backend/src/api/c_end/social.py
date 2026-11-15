from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update

from src.core.deps import CurrentUser, DbSession
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_CONFLICT,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
)
from src.db.models import Conversation, Friend, FriendRequest, Item, Message, User
from src.services import ai_audit_service as ai
from src.services.auth_service import bound_resident

router = APIRouter(tags=["c:social"])


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


async def _require_verified(db: DbSession, user: User, action: str) -> None:
    """BR-14：好友与私信功能仅限已实名用户。"""
    if user.realname_status != "VERIFIED":
        raise ApiError(ERR_FORBIDDEN, f"{action}需要先完成实名认证", 403)


async def _are_friends(db: DbSession, a: int, b: int) -> bool:
    return bool(await db.scalar(
        select(Friend.id).where(Friend.user_id == a, Friend.friend_id == b,
                                Friend.status == "ACTIVE").limit(1)))


async def _get_conversation_or_404(db: DbSession, conversation_id: int,
                                   user: User) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise ApiError(ERR_NOT_FOUND, "会话不存在", 404)
    if user.id not in (conv.user_a_id, conv.user_b_id):
        raise ApiError(ERR_FORBIDDEN, "无权访问该会话", 403)
    return conv


async def _conversation_row(db: DbSession, conv: Conversation, user: User) -> dict:
    peer_id = conv.user_b_id if conv.user_a_id == user.id else conv.user_a_id
    peer = await db.get(User, peer_id)
    unread = int((await db.execute(select(func.count())
                                   .select_from(Message)
                                   .where(Message.conversation_id == conv.id,
                                          Message.sender_id == peer_id,
                                          Message.status != "READ"))).scalar() or 0)
    return {
        "id": str(conv.id),
        "peerId": str(peer_id),
        "peerName": peer.nickname if peer else "",
        "peerAvatar": (peer.avatar_key if peer else "") or "avatar-person-1",
        "peerVerified": bool(peer and peer.realname_status == "VERIFIED"),
        "lastMessage": conv.last_message,
        "lastTime": _time_text(conv.updated_at),
        "unread": unread,
        "itemId": str(conv.item_id) if conv.item_id else None,
        "type": conv.type,
    }


@router.get("/conversations")
async def list_conversations(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(Conversation)
        .where(or_(Conversation.user_a_id == user.id, Conversation.user_b_id == user.id))
        .order_by(Conversation.updated_at.desc()))).scalars().all())
    return ok([await _conversation_row(db, row, user) for row in rows])


class CreateConversationIn(BaseModel):
    peerId: int
    itemId: int | None = None


@router.post("/conversations")
async def create_conversation(payload: CreateConversationIn, user: CurrentUser, db: DbSession):
    """物品会话（关联物品）或好友私信（不依赖物品，须互为好友，BR-14）。"""
    await _require_verified(db, user, "发起会话")
    peer = await db.get(User, payload.peerId)
    if not peer:
        raise ApiError(ERR_NOT_FOUND, "对方用户不存在", 404)
    if peer.id == user.id:
        raise ApiError(ERR_PARAM, "不能和自己发起会话", 400)

    conv_type = "ITEM" if payload.itemId else "FRIEND"
    if conv_type == "ITEM":
        item = await db.get(Item, payload.itemId)
        if not item or item.seller_id != peer.id:
            raise ApiError(ERR_PARAM, "对方不是该物品的卖家", 400)
    else:
        if not await _are_friends(db, user.id, peer.id):
            raise ApiError(ERR_FORBIDDEN, "好友私信需先互为好友", 403)

    existing = await db.scalar(
        select(Conversation).where(
            Conversation.type == conv_type,
            Conversation.item_id == payload.itemId,
            ((Conversation.user_a_id == user.id) & (Conversation.user_b_id == peer.id))
            | ((Conversation.user_a_id == peer.id) & (Conversation.user_b_id == user.id)),
        ))
    if existing:
        return ok(await _conversation_row(db, existing, user))

    conv = Conversation(type=conv_type, item_id=payload.itemId,
                        user_a_id=user.id, user_b_id=peer.id)
    db.add(conv)
    await db.flush()
    await db.commit()
    return ok(await _conversation_row(db, conv, user))


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: int, user: CurrentUser, db: DbSession):
    conv = await _get_conversation_or_404(db, conversation_id, user)
    rows = list((await db.execute(
        select(Message).where(Message.conversation_id == conv.id)
        .order_by(Message.seq, Message.id))).scalars().all())
    result = []
    for message in rows:
        sender = await db.get(User, message.sender_id)
        result.append({
            "id": str(message.id),
            "clientMsgId": message.client_msg_id or None,
            "conversationId": str(conv.id),
            "senderId": str(message.sender_id),
            "senderName": sender.nickname if sender else "",
            "type": message.type,
            "content": message.content,
            "image": message.image_key or None,
            "createdAt": int(message.created_at.timestamp() * 1000) if message.created_at else 0,
            "timeText": _time_text(message.created_at),
            "status": message.status,
            "mine": message.sender_id == user.id,
            "riskFlag": message.risk_flag or None,
        })
    return ok(result)


class SendMessageIn(BaseModel):
    content: str = ""
    type: str = "TEXT"
    clientMsgId: str = ""
    image: str = ""


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, payload: SendMessageIn,
                       user: CurrentUser, db: DbSession):
    """发送消息：client_msg_id 幂等（断线重发不重复）；敏感词/外链命中展示风险提醒（M05-05）。"""
    await _require_verified(db, user, "发送私信")
    conv = await _get_conversation_or_404(db, conversation_id, user)
    from src.services.chat_service import send_chat_message

    message, _ = await send_chat_message(
        db, conversation=conv, sender=user, content=payload.content,
        msg_type=payload.type, client_msg_id=payload.clientMsgId, image=payload.image)
    await db.commit()
    return ok(await _message_row(db, message, conv, user))


async def _message_row(db: DbSession, message: Message, conv: Conversation, user: User) -> dict:
    sender = await db.get(User, message.sender_id)
    return {
        "id": str(message.id),
        "clientMsgId": message.client_msg_id or None,
        "conversationId": str(conv.id),
        "senderId": str(message.sender_id),
        "senderName": sender.nickname if sender else "",
        "type": message.type,
        "content": message.content,
        "image": message.image_key or None,
        "createdAt": int(message.created_at.timestamp() * 1000) if message.created_at else 0,
        "timeText": _time_text(message.created_at),
        "status": message.status,
        "mine": message.sender_id == user.id,
        "riskFlag": message.risk_flag or None,
    }


@router.post("/conversations/{conversation_id}/read")
async def read_conversation(conversation_id: int, user: CurrentUser, db: DbSession):
    conv = await _get_conversation_or_404(db, conversation_id, user)
    peer_id = conv.user_b_id if conv.user_a_id == user.id else conv.user_a_id
    await db.execute(
        update(Message)
        .where(Message.conversation_id == conv.id, Message.sender_id == peer_id,
               Message.status != "READ")
        .values(status="READ"))
    await db.commit()
    return ok({"success": True})


@router.post("/conversations/read-all")
async def read_all_conversations(user: CurrentUser, db: DbSession):
    convs = list((await db.execute(
        select(Conversation).where(or_(Conversation.user_a_id == user.id,
                                       Conversation.user_b_id == user.id)))).scalars().all())
    for conv in convs:
        peer_id = conv.user_b_id if conv.user_a_id == user.id else conv.user_a_id
        await db.execute(
            update(Message)
            .where(Message.conversation_id == conv.id, Message.sender_id == peer_id,
                   Message.status != "READ")
            .values(status="READ"))
    await db.commit()
    return ok({"success": True})


# ---------------------------------------------------------------- 好友（BR-14）

def _letter(name: str) -> str:
    if not name:
        return "#"
    ch = name[0].upper()
    return ch if "A" <= ch <= "Z" else "#"


@router.get("/friends")
async def list_friends(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(Friend).where(Friend.user_id == user.id, Friend.status == "ACTIVE")
        .order_by(Friend.id))).scalars().all())
    result = []
    for row in rows:
        friend = await db.get(User, row.friend_id)
        resident = await bound_resident(db, row.friend_id)
        from src.db.models import Community

        community = await db.get(Community, resident.community_id) if resident else None
        result.append({
            "id": str(row.friend_id),
            "name": row.remark or (friend.nickname if friend else ""),
            "avatar": (friend.avatar_key if friend else "") or "avatar-person-1",
            "verified": bool(friend and friend.realname_status == "VERIFIED"),
            "community": community.name if community else "",
            "letter": _letter(row.remark or (friend.nickname if friend else "")),
        })
    return ok(result)


@router.get("/friends/requests")
async def friend_requests(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(FriendRequest).where(FriendRequest.to_user_id == user.id)
        .order_by(FriendRequest.id.desc()).limit(50))).scalars().all())
    result = []
    for row in rows:
        sender = await db.get(User, row.from_user_id)
        result.append({
            "id": str(row.id),
            "name": sender.nickname if sender else "",
            "avatar": (sender.avatar_key if sender else "") or "avatar-person-1",
            "message": row.message,
            "time": _time_text(row.created_at),
            "status": row.status,
        })
    return ok(result)


class FriendRequestIn(BaseModel):
    name: str
    message: str = ""


@router.post("/friends/requests")
async def send_friend_request(payload: FriendRequestIn, user: CurrentUser, db: DbSession):
    """好友申请（M05-03/BR-14）：仅限已实名用户互加；验证语过内容安全审核；
    上限默认 500（可配置）。"""
    await _require_verified(db, user, "加好友")
    target = await db.scalar(select(User).where(User.nickname == payload.name.strip()))
    if not target:
        raise ApiError(ERR_NOT_FOUND, "未找到该用户", 404)
    if target.id == user.id:
        raise ApiError(ERR_PARAM, "不能添加自己为好友", 400)
    if target.realname_status != "VERIFIED":
        raise ApiError(ERR_BIZ_RULE, "对方尚未完成实名认证，暂不能加好友", 422)
    if await _are_friends(db, user.id, target.id):
        raise ApiError(ERR_CONFLICT, "你们已经是好友了", 409)
    hit = next((kw for kw in ai.BANNED_KEYWORDS if kw in payload.message), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"验证语包含违禁内容（{hit}）", 422)
    pending = await db.scalar(
        select(FriendRequest).where(FriendRequest.from_user_id == user.id,
                                    FriendRequest.to_user_id == target.id,
                                    FriendRequest.status == "PENDING").limit(1))
    if pending:
        raise ApiError(ERR_CONFLICT, "好友申请已发送，请等待对方处理", 409)
    request = FriendRequest(from_user_id=user.id, to_user_id=target.id,
                            message=payload.message[:100])
    db.add(request)

    from src.services.notify_service import notify_user

    await notify_user(db, target.id, category="INTERACTION", title="新的好友申请",
                      description=f"{user.nickname}：{payload.message or '请求加为好友'}",
                      icon="user-plus", tag="好友")
    await db.commit()
    return ok({"id": str(request.id), "status": "PENDING"}, "好友申请已发送")


@router.post("/friends/requests/{request_id}/accept")
async def accept_friend_request(request_id: int, user: CurrentUser, db: DbSession):
    request = await db.get(FriendRequest, request_id)
    if not request or request.to_user_id != user.id:
        raise ApiError(ERR_NOT_FOUND, "申请不存在", 404)
    if request.status != "PENDING":
        raise ApiError(ERR_CONFLICT, "申请已处理", 409)
    from src.core.config import settings

    count = int((await db.scalar(
        select(func.count()).select_from(Friend)
        .where(Friend.user_id == user.id, Friend.status == "ACTIVE"))) or 0)
    if count >= settings.friend_max_count:
        raise ApiError(ERR_BIZ_RULE, f"好友数量已达上限 {settings.friend_max_count}", 422)
    request.status = "ACCEPTED"
    request.handled_at = datetime.now(UTC).replace(tzinfo=None)
    for a, b in ((request.from_user_id, request.to_user_id),
                 (request.to_user_id, request.from_user_id)):
        existing = await db.scalar(select(Friend).where(Friend.user_id == a, Friend.friend_id == b))
        if existing:
            existing.status = "ACTIVE"
        else:
            db.add(Friend(user_id=a, friend_id=b, status="ACTIVE"))
    await db.commit()
    return ok({"success": True}, "已同意，现在可以互发私信了")


@router.post("/friends/requests/{request_id}/reject")
async def reject_friend_request(request_id: int, user: CurrentUser, db: DbSession):
    request = await db.get(FriendRequest, request_id)
    if not request or request.to_user_id != user.id:
        raise ApiError(ERR_NOT_FOUND, "申请不存在", 404)
    if request.status != "PENDING":
        raise ApiError(ERR_CONFLICT, "申请已处理", 409)
    request.status = "REJECTED"
    request.handled_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    return ok({"success": True})


@router.delete("/friends/{friend_id}")
async def delete_friend(friend_id: int, user: CurrentUser, db: DbSession):
    row = await db.scalar(select(Friend).where(Friend.user_id == user.id,
                                               Friend.friend_id == friend_id,
                                               Friend.status == "ACTIVE"))
    if not row:
        raise ApiError(ERR_NOT_FOUND, "好友关系不存在", 404)
    row.status = "DELETED"
    await db.commit()
    return ok({"success": True})
