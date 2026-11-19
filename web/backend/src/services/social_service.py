"""邻居好友关系服务。

核心规则（BR-14 / M05-03/M05-04）：
- 只有同时完成实名认证（REALNAME）与住户认证（OWNER_PROOF）的住户可使用好友功能；
- 同一小区内双认证住户默认互为邻居好友，不物化关系；
- 任一方向拉黑即视为关系阻断；
- 备注单独存储，仅 owner 可见。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_NOT_VERIFIED,
    ERR_PARAM,
    ApiError,
)
from src.db.models import (
    Community,
    Conversation,
    FriendBlock,
    FriendRemark,
    Resident,
    User,
)
from src.db.models.common import utcnow


@dataclass
class SocialEligibility:
    eligible: bool
    realname_verified: bool
    owner_verified: bool
    community_id: int | None
    community_name: str
    reason_code: str
    reason_text: str = ""

    def as_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "realnameVerified": self.realname_verified,
            "ownerVerified": self.owner_verified,
            "communityId": str(self.community_id) if self.community_id else None,
            "communityName": self.community_name,
            "reasonCode": self.reason_code,
            "reasonText": self.reason_text,
        }


class Relation:
    FRIEND = "FRIEND"
    SELF = "SELF"
    ME_NOT_ELIGIBLE = "ME_NOT_ELIGIBLE"
    PEER_NOT_ELIGIBLE = "PEER_NOT_ELIGIBLE"
    NOT_SAME_COMMUNITY = "NOT_SAME_COMMUNITY"
    BLOCKED = "BLOCKED"


REASON_TEXT = {
    "REALNAME_REQUIRED": "完成实名认证后，即可使用邻居好友功能",
    "OWNER_PROOF_REQUIRED": "完成住户认证后，即可与同小区邻居聊天",
    "COMMUNITY_INACTIVE": "所在小区暂停服务，好友功能暂不可用",
    "OK": "",
}


async def bound_active_resident(
    db: AsyncSession, user_id: int
) -> Resident | None:
    return await db.scalar(
        select(Resident)
        .where(
            Resident.user_id == user_id,
            Resident.status == "ACTIVE",
            Resident.certification_status == "VERIFIED",
        )
        .order_by(Resident.id.desc())
        .limit(1)
    )


async def get_social_eligibility(
    db: AsyncSession, user: User
) -> SocialEligibility:
    from src.services.auth_service import latest_certification

    latest_realname = await latest_certification(db, user.id, "REALNAME")
    resident = await bound_active_resident(db, user.id)
    latest_owner = await latest_certification(db, user.id, "OWNER_PROOF")
    community = await db.get(Community, resident.community_id) if resident else None
    community_ok = bool(community and community.status == "OPERATING")
    realname_ok = (
        user.status == "ACTIVE"
        and user.realname_status == "VERIFIED"
        and (latest_realname is None or latest_realname.status == "VERIFIED")
    )
    owner_ok = bool(
        resident
        and community_ok
        and (latest_owner is None or latest_owner.status == "VERIFIED")
    )

    if realname_ok and owner_ok:
        reason = "OK"
    elif not realname_ok:
        reason = "REALNAME_REQUIRED"
    elif resident and not community_ok:
        reason = "COMMUNITY_INACTIVE"
    else:
        reason = "OWNER_PROOF_REQUIRED"

    return SocialEligibility(
        eligible=bool(realname_ok and owner_ok),
        realname_verified=bool(realname_ok),
        owner_verified=bool(owner_ok),
        community_id=resident.community_id if owner_ok else None,
        community_name=community.name if community_ok and community else "",
        reason_code=reason,
        reason_text=REASON_TEXT.get(reason, ""),
    )


async def get_social_eligibility_by_id(
    db: AsyncSession, user_id: int
) -> SocialEligibility:
    user = await db.get(User, user_id)
    if not user:
        return SocialEligibility(
            eligible=False,
            realname_verified=False,
            owner_verified=False,
            community_id=None,
            community_name="",
            reason_code="REALNAME_REQUIRED",
            reason_text=REASON_TEXT["REALNAME_REQUIRED"],
        )
    return await get_social_eligibility(db, user)


async def require_eligible(db: AsyncSession, user: User, action: str = "使用好友功能") -> SocialEligibility:
    if not settings.neighbor_friends_enabled:
        raise ApiError(ERR_FORBIDDEN, "邻居好友功能暂未开放", 403)
    eligibility = await get_social_eligibility(db, user)
    if not eligibility.eligible:
        raise ApiError(
            ERR_NOT_VERIFIED,
            f"{action}需要先完成实名认证与住户认证",
            403,
            data=eligibility.as_dict(),
        )
    return eligibility


async def has_active_block(db: AsyncSession, a: int, b: int) -> bool:
    return bool(await db.scalar(
        select(FriendBlock.id)
        .where(
            FriendBlock.status == "ACTIVE",
            or_(
                and_(FriendBlock.blocker_id == a, FriendBlock.blocked_id == b),
                and_(FriendBlock.blocker_id == b, FriendBlock.blocked_id == a),
            ),
        )
        .limit(1)
    ))


async def has_conversation(db: AsyncSession, a: int, b: int) -> bool:
    pair_low, pair_high = (a, b) if a < b else (b, a)
    return bool(await db.scalar(
        select(Conversation.id)
        .where(
            or_(
                and_(
                    Conversation.pair_low_id == pair_low,
                    Conversation.pair_high_id == pair_high,
                ),
                and_(Conversation.user_a_id == a, Conversation.user_b_id == b),
                and_(Conversation.user_a_id == b, Conversation.user_b_id == a),
            )
        )
        .limit(1)
    ))


async def get_relation(db: AsyncSession, me_id: int, peer_id: int) -> str:
    if me_id == peer_id:
        return Relation.SELF
    me = await get_social_eligibility_by_id(db, me_id)
    if not me.eligible:
        return Relation.ME_NOT_ELIGIBLE
    peer = await get_social_eligibility_by_id(db, peer_id)
    if not peer.eligible:
        return Relation.PEER_NOT_ELIGIBLE
    if me.community_id != peer.community_id:
        return Relation.NOT_SAME_COMMUNITY
    if await has_active_block(db, me_id, peer_id):
        return Relation.BLOCKED
    return Relation.FRIEND


def _letter(name: str) -> str:
    if not name:
        return "#"
    ch = name[0].upper()
    return ch if "A" <= ch <= "Z" else "#"


def _neighbor_row(
    resident: Resident,
    user: User,
    community: Community | None,
    remark: str,
) -> dict:
    name = remark or user.nickname
    return {
        "id": str(user.id),
        "userId": str(user.id),
        "name": name,
        "avatar": user.avatar_key or "avatar-person-1",
        "remark": remark,
        "verified": True,
        "community": community.name if community else "",
        "building": resident.building,
        "identityType": resident.identity_type,
        "letter": _letter(name),
    }


async def list_neighbors(
    db: AsyncSession,
    user: User,
    *,
    keyword: str = "",
    building: str = "",
    page: int = 1,
    page_size: int | None = None,
) -> dict:
    eligibility = await require_eligible(db, user)
    page = max(1, page)
    page_size = min(max(1, page_size or settings.neighbor_page_size), 50)

    conditions = [
        Resident.community_id == eligibility.community_id,
        Resident.status == "ACTIVE",
        Resident.certification_status == "VERIFIED",
        User.status == "ACTIVE",
        User.realname_status == "VERIFIED",
        Resident.user_id != user.id,
    ]
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        conditions.append(or_(
            User.nickname.ilike(like),
            Resident.building.ilike(like),
            FriendRemark.remark.ilike(like),
        ))
    if building.strip():
        conditions.append(Resident.building == building.strip())

    blocked = select(FriendBlock.id).where(
        FriendBlock.status == "ACTIVE",
        or_(
            and_(FriendBlock.blocker_id == user.id, FriendBlock.blocked_id == Resident.user_id),
            and_(FriendBlock.blocker_id == Resident.user_id, FriendBlock.blocked_id == user.id),
        ),
    ).exists()
    conditions.append(~blocked)

    total = int(await db.scalar(
        select(func.count(func.distinct(Resident.user_id)))
        .select_from(Resident)
        .join(User, User.id == Resident.user_id)
        .outerjoin(
            FriendRemark,
            and_(FriendRemark.owner_id == user.id, FriendRemark.peer_id == Resident.user_id),
        )
        .where(*conditions)
    ) or 0)

    rows = (await db.execute(
        select(Resident, User, FriendRemark.remark)
        .join(User, User.id == Resident.user_id)
        .outerjoin(
            FriendRemark,
            and_(FriendRemark.owner_id == user.id, FriendRemark.peer_id == Resident.user_id),
        )
        .where(*conditions)
        .order_by(User.nickname, Resident.user_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()

    community = await db.get(Community, eligibility.community_id)
    items = [
        _neighbor_row(resident, peer, community, remark or "")
        for resident, peer, remark in rows
    ]
    return {
        "items": items,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "hasMore": page * page_size < total,
        "eligibility": eligibility.as_dict(),
    }


async def get_neighbor(db: AsyncSession, user: User, peer_id: int) -> dict:
    eligibility = await require_eligible(db, user)
    peer = await db.get(User, peer_id)
    if not peer:
        raise ApiError(ERR_NOT_FOUND, "邻居不存在", 404)
    relation = await get_relation(db, user.id, peer_id)
    if relation == Relation.SELF:
        raise ApiError(ERR_PARAM, "不能查看自己的邻居详情", 400)
    resident = await bound_active_resident(db, peer_id)
    if relation not in (Relation.FRIEND, Relation.BLOCKED) or not resident:
        raise ApiError(ERR_NOT_FOUND, "邻居不存在", 404)
    community = await db.get(Community, resident.community_id)
    remark = await db.scalar(
        select(FriendRemark.remark).where(
            FriendRemark.owner_id == user.id, FriendRemark.peer_id == peer_id
        )
    )
    blocked_by_me = bool(await db.scalar(
        select(FriendBlock.id).where(
            FriendBlock.blocker_id == user.id,
            FriendBlock.blocked_id == peer_id,
            FriendBlock.status == "ACTIVE",
        ).limit(1)
    ))
    return {
        **_neighbor_row(resident, peer, community, remark or ""),
        "relation": relation,
        "blockedByMe": blocked_by_me,
        "blockedMe": relation == Relation.BLOCKED and not blocked_by_me,
        "canMessage": relation == Relation.FRIEND,
        "reasonCode": "OK" if relation == Relation.FRIEND else relation,
        "eligibility": eligibility.as_dict(),
    }


async def list_blocks(db: AsyncSession, user: User, page: int = 1, page_size: int = 20) -> dict:
    page = max(1, page)
    page_size = min(max(1, page_size), 50)
    total = int(await db.scalar(
        select(func.count()).select_from(FriendBlock).where(
            FriendBlock.blocker_id == user.id,
            FriendBlock.status == "ACTIVE",
        )
    ) or 0)
    rows = (await db.execute(
        select(FriendBlock, User)
        .join(User, User.id == FriendBlock.blocked_id)
        .where(FriendBlock.blocker_id == user.id, FriendBlock.status == "ACTIVE")
        .order_by(FriendBlock.created_at.desc(), FriendBlock.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()
    return {
        "items": [
            {
                "userId": str(blocked.id),
                "name": blocked.nickname,
                "avatar": blocked.avatar_key or "avatar-person-1",
                "reason": row.reason,
                "blockedAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
            }
            for row, blocked in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "hasMore": page * page_size < total,
    }


async def block_user(
    db: AsyncSession,
    user: User,
    peer_id: int,
    *,
    reason: str = "",
    source: str = "CHAT",
) -> None:
    if not settings.neighbor_block_enabled:
        raise ApiError(ERR_FORBIDDEN, "拉黑功能暂未开放", 403)
    if peer_id == user.id:
        raise ApiError(ERR_PARAM, "不能拉黑自己", 400)
    peer = await db.get(User, peer_id)
    if not peer or peer.status != "ACTIVE":
        raise ApiError(ERR_NOT_FOUND, "用户不存在", 404)

    relation = await get_relation(db, user.id, peer_id)
    if relation not in (Relation.FRIEND, Relation.BLOCKED) and not await has_conversation(
        db, user.id, peer_id
    ):
        raise ApiError(ERR_NOT_FOUND, "邻居不存在", 404)

    active_count = int(await db.scalar(
        select(func.count()).select_from(FriendBlock).where(
            FriendBlock.blocker_id == user.id, FriendBlock.status == "ACTIVE"
        )
    ) or 0)
    existing = await db.scalar(
        select(FriendBlock).where(
            FriendBlock.blocker_id == user.id,
            FriendBlock.blocked_id == peer_id,
        )
    )
    if not existing and active_count >= settings.neighbor_block_max_count:
        raise ApiError(ERR_BIZ_RULE, "拉黑数量已达上限", 422)

    if existing:
        existing.status = "ACTIVE"
        existing.reason = reason.strip()[:200]
        existing.source = source.strip()[:16] or "CHAT"
        existing.released_at = None
    else:
        resident = await bound_active_resident(db, user.id)
        db.add(FriendBlock(
            blocker_id=user.id,
            blocked_id=peer_id,
            community_id=resident.community_id if resident else None,
            reason=reason.strip()[:200],
            source=source.strip()[:16] or "CHAT",
            status="ACTIVE",
        ))


async def unblock_user(db: AsyncSession, user: User, peer_id: int) -> None:
    row = await db.scalar(
        select(FriendBlock).where(
            FriendBlock.blocker_id == user.id,
            FriendBlock.blocked_id == peer_id,
            FriendBlock.status == "ACTIVE",
        )
    )
    if not row:
        raise ApiError(ERR_NOT_FOUND, "拉黑记录不存在", 404)
    row.status = "RELEASED"
    row.released_at = utcnow()


async def set_remark(db: AsyncSession, user: User, peer_id: int, remark: str) -> dict:
    relation = await get_relation(db, user.id, peer_id)
    if relation != Relation.FRIEND:
        raise ApiError(ERR_NOT_FOUND, "邻居不存在", 404)
    row = await db.scalar(
        select(FriendRemark).where(
            FriendRemark.owner_id == user.id, FriendRemark.peer_id == peer_id
        )
    )
    value = remark.strip()[:64]
    if row:
        row.remark = value
    else:
        db.add(FriendRemark(owner_id=user.id, peer_id=peer_id, remark=value))
    return {"peerId": str(peer_id), "remark": value}


def conversation_peer_id(conversation: Conversation, user_id: int) -> int:
    return conversation.user_b_id if conversation.user_a_id == user_id else conversation.user_a_id


async def get_or_create_friend_conversation(
    db: AsyncSession, user: User, peer_id: int
) -> Conversation:
    if not settings.neighbor_friends_enabled:
        raise ApiError(ERR_FORBIDDEN, "邻居好友功能暂未开放", 403)
    relation = await get_relation(db, user.id, peer_id)
    if relation == Relation.SELF:
        raise ApiError(ERR_PARAM, "不能和自己发起会话", 400)
    if relation == Relation.BLOCKED:
        from src.core.responses import ERR_RELATION_BLOCKED

        raise ApiError(ERR_RELATION_BLOCKED, "你们已互相拉黑，无法发起会话", 403)
    if relation != Relation.FRIEND:
        raise ApiError(ERR_NOT_VERIFIED, "好友私信需先完成双认证并在同一小区", 403)

    pair_low, pair_high = (user.id, peer_id) if user.id < peer_id else (peer_id, user.id)
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.type == "FRIEND",
            Conversation.pair_low_id == pair_low,
            Conversation.pair_high_id == pair_high,
        )
    )
    if conversation:
        return conversation

    # 兼容未回填 pair 的历史会话。
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.type == "FRIEND",
            or_(
                and_(Conversation.user_a_id == user.id, Conversation.user_b_id == peer_id),
                and_(Conversation.user_a_id == peer_id, Conversation.user_b_id == user.id),
            ),
        ).order_by(Conversation.id)
    )
    if conversation:
        conversation.pair_low_id = pair_low
        conversation.pair_high_id = pair_high
        return conversation

    conversation = Conversation(
        type="FRIEND",
        item_id=None,
        user_a_id=user.id,
        user_b_id=peer_id,
        pair_low_id=pair_low,
        pair_high_id=pair_high,
        last_message="",
        last_message_type="TEXT",
        last_seq=0,
        last_read_seq_a=0,
        last_read_seq_b=0,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def conversation_read_only_reason(
    db: AsyncSession, conversation: Conversation, user_id: int
) -> str | None:
    peer_id = conversation_peer_id(conversation, user_id)
    if await has_active_block(db, user_id, peer_id):
        return "BLOCKED"
    if conversation.type == "FRIEND":
        relation = await get_relation(db, user_id, peer_id)
        if relation != Relation.FRIEND:
            return "INELIGIBLE"
    return None


async def assert_can_send(
    db: AsyncSession, conversation: Conversation, sender: User
) -> None:
    if conversation.type == "FRIEND" and not settings.neighbor_friends_enabled:
        raise ApiError(ERR_FORBIDDEN, "邻居好友功能暂未开放", 403)
    peer_id = conversation_peer_id(conversation, sender.id)
    if await has_active_block(db, sender.id, peer_id):
        from src.core.responses import ERR_RELATION_BLOCKED

        raise ApiError(ERR_RELATION_BLOCKED, "你们已互相拉黑，无法发送消息", 403)
    if conversation.type == "FRIEND":
        relation = await get_relation(db, sender.id, peer_id)
        if relation == Relation.BLOCKED:
            from src.core.responses import ERR_RELATION_BLOCKED

            raise ApiError(ERR_RELATION_BLOCKED, "你们已互相拉黑，无法发送消息", 403)
        if relation != Relation.FRIEND:
            raise ApiError(ERR_NOT_VERIFIED, "完成实名认证与住户认证后才能发送邻居消息", 403)


def message_preview(msg_type: str, content: str) -> str:
    if msg_type == "TEXT":
        return content[:120]
    if msg_type == "EMOJI":
        return "[表情]"
    if msg_type == "IMAGE":
        return "[图片]"
    if msg_type == "VIDEO":
        return "[视频]"
    if msg_type == "VOICE":
        return "[语音]"
    if msg_type == "ITEM":
        return "[物品]"
    return content[:120] or "[消息]"


def clear_time_for(conversation: Conversation, user_id: int) -> datetime | None:
    return conversation.cleared_at_a if conversation.user_a_id == user_id else conversation.cleared_at_b
