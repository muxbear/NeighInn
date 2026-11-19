from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update

from src.core.deps import CurrentUser, DbSession
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_CONFLICT,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_NOT_VERIFIED,
    ERR_PARAM,
    ERR_RELATION_BLOCKED,
    ApiError,
    ok,
)
from src.db.models import (
    Community,
    Conversation,
    Friend,
    FriendRequest,
    Item,
    Message,
    User,
)
from src.services import ai_audit_service as ai
from src.services import social_service as social
from src.services.chat_service import (
    mark_conversation_read,
    message_payload,
    send_chat_message,
    unread_count,
)

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


def _require_realname(user: User, action: str) -> None:
    """物品会话沿用原实名校验；好友会话由 social_service 做双认证校验。"""
    if user.realname_status != "VERIFIED":
        raise ApiError(ERR_NOT_VERIFIED, f"{action}需要先完成实名认证", 403)


async def _get_conversation_or_404(
    db: DbSession, conversation_id: int, user: User
) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise ApiError(ERR_NOT_FOUND, "会话不存在", 404)
    if user.id not in (conv.user_a_id, conv.user_b_id):
        raise ApiError(ERR_FORBIDDEN, "无权访问该会话", 403)
    return conv


async def _conversation_row(db: DbSession, conv: Conversation, user: User) -> dict:
    peer_id = social.conversation_peer_id(conv, user.id)
    peer = await db.get(User, peer_id)
    peer_resident = await social.bound_active_resident(db, peer_id)
    peer_community = (
        await db.get(Community, peer_resident.community_id) if peer_resident else None
    )
    read_only_reason = await social.conversation_read_only_reason(db, conv, user.id)
    return {
        "id": str(conv.id),
        "type": conv.type,
        "peerId": str(peer_id),
        "peerName": peer.nickname if peer else "",
        "peerAvatar": (peer.avatar_key if peer else "") or "avatar-person-1",
        "peerVerified": bool(
            peer
            and peer.realname_status == "VERIFIED"
            and peer_resident
            and peer_resident.certification_status == "VERIFIED"
        ),
        "peerCommunity": peer_community.name if peer_community else "",
        "lastMessage": conv.last_message,
        "lastMessageType": conv.last_message_type,
        "lastTime": _time_text(conv.last_message_at or conv.updated_at),
        "unread": await unread_count(db, conv, user.id),
        "itemId": str(conv.item_id) if conv.item_id else None,
        "canSend": read_only_reason is None,
        "readOnlyReason": read_only_reason,
    }


@router.get("/conversations")
async def list_conversations(user: CurrentUser, db: DbSession):
    rows = list((await db.execute(
        select(Conversation)
        .where(or_(Conversation.user_a_id == user.id, Conversation.user_b_id == user.id))
        .order_by(
            func.coalesce(Conversation.last_message_at, Conversation.updated_at).desc(),
            Conversation.id.desc(),
        )
    )).scalars().all())
    result = []
    for row in rows:
        peer_id = social.conversation_peer_id(row, user.id)
        # 好友会话被拉黑后从双方列表隐藏；物品会话保留但只读。
        if row.type == "FRIEND" and await social.has_active_block(db, user.id, peer_id):
            continue
        result.append(await _conversation_row(db, row, user))
    return ok(result)


class CreateConversationIn(BaseModel):
    peerId: int
    itemId: int | None = None


@router.post("/conversations")
async def create_conversation(
    payload: CreateConversationIn, user: CurrentUser, db: DbSession
):
    """物品会话（关联物品）或好友私信（不依赖物品，须为同小区双认证邻居）。"""
    peer = await db.get(User, payload.peerId)
    if not peer:
        raise ApiError(ERR_NOT_FOUND, "对方用户不存在", 404)
    if peer.id == user.id:
        raise ApiError(ERR_PARAM, "不能和自己发起会话", 400)

    if payload.itemId:
        _require_realname(user, "发起会话")
        item = await db.get(Item, payload.itemId)
        if not item or item.seller_id != peer.id:
            raise ApiError(ERR_PARAM, "对方不是该物品的卖家", 400)
        if await social.has_active_block(db, user.id, peer.id):
            raise ApiError(ERR_RELATION_BLOCKED, "你们已互相拉黑，无法发起会话", 403)
        pair_low, pair_high = (
            (user.id, peer.id) if user.id < peer.id else (peer.id, user.id)
        )
        existing = await db.scalar(
            select(Conversation).where(
                Conversation.type == "ITEM",
                Conversation.item_id == payload.itemId,
                or_(
                    and_(
                        Conversation.pair_low_id == pair_low,
                        Conversation.pair_high_id == pair_high,
                    ),
                    and_(
                        Conversation.user_a_id == user.id,
                        Conversation.user_b_id == peer.id,
                    ),
                    and_(
                        Conversation.user_a_id == peer.id,
                        Conversation.user_b_id == user.id,
                    ),
                ),
            ).order_by(Conversation.id)
        )
        if existing:
            existing.pair_low_id = pair_low
            existing.pair_high_id = pair_high
            await db.commit()
            return ok(await _conversation_row(db, existing, user))

        conv = Conversation(
            type="ITEM",
            item_id=payload.itemId,
            user_a_id=user.id,
            user_b_id=peer.id,
            pair_low_id=pair_low,
            pair_high_id=pair_high,
            last_message="",
            last_message_type="TEXT",
            last_seq=0,
            last_read_seq_a=0,
            last_read_seq_b=0,
        )
        db.add(conv)
        await db.commit()
        return ok(await _conversation_row(db, conv, user))

    conv = await social.get_or_create_friend_conversation(db, user, peer.id)
    await db.commit()
    return ok(await _conversation_row(db, conv, user))


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    user: CurrentUser,
    db: DbSession,
    beforeSeq: int | None = None,
    afterSeq: int | None = None,
    limit: int = 30,
):
    conv = await _get_conversation_or_404(db, conversation_id, user)
    limit = min(max(1, limit), 50)
    cleared_at = social.clear_time_for(conv, user.id)
    conditions = [
        Message.conversation_id == conv.id,
        Message.deleted_at.is_(None),
    ]
    if cleared_at:
        conditions.append(Message.created_at > cleared_at)

    if afterSeq is not None:
        conditions.append(Message.seq > max(0, afterSeq))
        rows = list((await db.execute(
            select(Message).where(*conditions).order_by(Message.seq.asc()).limit(limit + 1)
        )).scalars().all())
        has_more_after = len(rows) > limit
        rows = rows[:limit]
        has_more_before = bool(rows and await db.scalar(
            select(Message.id).where(
                *conditions, Message.seq < rows[0].seq
            ).limit(1)
        ))
    else:
        if beforeSeq is not None:
            conditions.append(Message.seq < max(0, beforeSeq))
        rows = list((await db.execute(
            select(Message).where(*conditions).order_by(Message.seq.desc()).limit(limit + 1)
        )).scalars().all())
        has_more_before = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        has_more_after = False

    result = []
    for message in rows:
        sender = await db.get(User, message.sender_id)
        item = message_payload(message, mine=message.sender_id == user.id, sender=sender)
        item["timeText"] = _time_text(message.created_at)
        result.append(item)
    return ok({
        "items": result,
        "hasMoreBefore": has_more_before,
        "hasMoreAfter": has_more_after,
    })


class SendMessageIn(BaseModel):
    content: str = ""
    type: str = "TEXT"
    clientMsgId: str = ""
    image: str = ""
    extra: dict | None = None


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int, payload: SendMessageIn, user: CurrentUser, db: DbSession
):
    """发送消息：client_msg_id 幂等；好友会话双认证/拉黑门禁；敏感词风险提醒。"""
    conv = await _get_conversation_or_404(db, conversation_id, user)
    if conv.type == "ITEM":
        _require_realname(user, "发送私信")
    message, _ = await send_chat_message(
        db,
        conversation=conv,
        sender=user,
        content=payload.content,
        msg_type=payload.type,
        client_msg_id=payload.clientMsgId,
        image=payload.image,
        extra=payload.extra or {},
    )
    await db.commit()
    item = message_payload(message, mine=True, sender=user)
    item["timeText"] = _time_text(message.created_at)
    return ok(item)


class ReadIn(BaseModel):
    lastSeq: int | None = None


@router.post("/conversations/{conversation_id}/read")
async def read_conversation(
    conversation_id: int,
    user: CurrentUser,
    db: DbSession,
    payload: ReadIn | None = None,
):
    conv = await _get_conversation_or_404(db, conversation_id, user)
    requested = int(payload.lastSeq if payload and payload.lastSeq is not None else conv.last_seq)
    last_seq = min(max(0, requested), int(conv.last_seq or 0))
    await mark_conversation_read(db, conv, user.id, last_seq)
    peer_id = social.conversation_peer_id(conv, user.id)
    await db.execute(
        update(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.sender_id == peer_id,
            Message.seq <= last_seq,
            Message.status != "READ",
        )
        .values(status="READ", read_at=datetime.now(UTC).replace(tzinfo=None))
    )
    await db.commit()
    return ok({"success": True, "lastSeq": last_seq})


@router.post("/conversations/read-all")
async def read_all_conversations(user: CurrentUser, db: DbSession):
    convs = list((await db.execute(
        select(Conversation).where(or_(
            Conversation.user_a_id == user.id,
            Conversation.user_b_id == user.id,
        ))
    )).scalars().all())
    now = datetime.now(UTC).replace(tzinfo=None)
    for conv in convs:
        peer_id = social.conversation_peer_id(conv, user.id)
        await mark_conversation_read(db, conv, user.id, conv.last_seq)
        await db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.sender_id == peer_id,
                Message.status != "READ",
            )
            .values(status="READ", read_at=now)
        )
    await db.commit()
    return ok({"success": True})


# ---------------------------------------------------------------- 邻居好友


@router.get("/friends/eligibility")
async def friends_eligibility(user: CurrentUser, db: DbSession):
    """好友资格：不要求已达标，用于前端展示认证引导。"""
    eligibility = await social.get_social_eligibility(db, user)
    return ok(eligibility.as_dict())


@router.get("/friends/blocks")
async def list_blocks(user: CurrentUser, db: DbSession, page: int = 1, pageSize: int = 20):
    return ok(await social.list_blocks(db, user, page=page, page_size=pageSize))


@router.get("/friends")
async def list_friends(
    user: CurrentUser,
    db: DbSession,
    keyword: str = "",
    building: str = "",
    page: int = 1,
    pageSize: int = 50,
):
    """同小区双认证邻居（隐式好友），无需手动申请。"""
    return ok(await social.list_neighbors(
        db, user, keyword=keyword, building=building,
        page=page, page_size=pageSize,
    ))


@router.get("/friends/{peer_id:int}")
async def get_friend(peer_id: int, user: CurrentUser, db: DbSession):
    return ok(await social.get_neighbor(db, user, peer_id))


class RemarkIn(BaseModel):
    remark: str = ""


@router.put("/friends/{peer_id:int}/remark")
async def set_remark(peer_id: int, payload: RemarkIn, user: CurrentUser, db: DbSession):
    result = await social.set_remark(db, user, peer_id, payload.remark)
    await db.commit()
    return ok(result, "备注已更新")


class BlockIn(BaseModel):
    reason: str = ""
    source: str = "CHAT"


@router.post("/friends/{peer_id:int}/block")
async def block_friend(
    peer_id: int, user: CurrentUser, db: DbSession, payload: BlockIn | None = None
):
    data = payload or BlockIn()
    await social.block_user(
        db, user, peer_id, reason=data.reason, source=data.source
    )
    await db.commit()
    return ok({"blocked": True}, "已加入黑名单")


@router.delete("/friends/{peer_id:int}/block")
async def unblock_friend(peer_id: int, user: CurrentUser, db: DbSession):
    await social.unblock_user(db, user, peer_id)
    await db.commit()
    return ok({"blocked": False}, "已解除拉黑")


# ---------------------------------------------------------------- 旧好友申请（兼容）


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
    """旧好友申请入口：新体系默认邻居好友，不再需要申请；保留兼容一个版本。"""
    await social.require_eligible(db, user, "加好友")
    target = await db.scalar(select(User).where(User.nickname == payload.name.strip()))
    if not target:
        raise ApiError(ERR_NOT_FOUND, "未找到该用户", 404)
    if target.id == user.id:
        raise ApiError(ERR_PARAM, "不能添加自己为好友", 400)
    if await social.get_relation(db, user.id, target.id) == social.Relation.FRIEND:
        raise ApiError(ERR_CONFLICT, "你们已经是邻居好友了", 409)
    hit = next((kw for kw in ai.BANNED_KEYWORDS if kw in payload.message), None)
    if hit:
        raise ApiError(ERR_BIZ_RULE, f"验证语包含违禁内容（{hit}）", 422)
    pending = await db.scalar(
        select(FriendRequest).where(
            FriendRequest.from_user_id == user.id,
            FriendRequest.to_user_id == target.id,
            FriendRequest.status == "PENDING",
        ).limit(1)
    )
    if pending:
        raise ApiError(ERR_CONFLICT, "好友申请已发送，请等待对方处理", 409)
    request = FriendRequest(
        from_user_id=user.id, to_user_id=target.id, message=payload.message[:100]
    )
    db.add(request)

    from src.services.notify_service import notify_user

    await notify_user(
        db, target.id, category="INTERACTION", title="新的好友申请",
        description=f"{user.nickname}：{payload.message or '请求加为好友'}",
        icon="user-plus", tag="好友",
    )
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

    count = int(await db.scalar(
        select(func.count()).select_from(Friend).where(
            Friend.user_id == user.id, Friend.status == "ACTIVE"
        )
    ) or 0)
    if count >= settings.friend_max_count:
        raise ApiError(ERR_BIZ_RULE, f"好友数量已达上限 {settings.friend_max_count}", 422)
    request.status = "ACCEPTED"
    request.handled_at = datetime.now(UTC).replace(tzinfo=None)
    for a, b in ((request.from_user_id, request.to_user_id),
                 (request.to_user_id, request.from_user_id)):
        existing = await db.scalar(
            select(Friend).where(Friend.user_id == a, Friend.friend_id == b)
        )
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
    """旧接口：显式好友关系删除；新体系请使用拉黑。"""
    row = await db.scalar(
        select(Friend).where(
            Friend.user_id == user.id,
            Friend.friend_id == friend_id,
            Friend.status == "ACTIVE",
        )
    )
    if not row:
        raise ApiError(ERR_NOT_FOUND, "好友关系不存在", 404)
    row.status = "DELETED"
    await db.commit()
    return ok({"success": True})
