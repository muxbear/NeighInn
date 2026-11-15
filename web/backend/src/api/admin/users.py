from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.core.security import decrypt_field, hmac_index, mask_phone
from src.db.models import (
    Certification,
    Friend,
    Item,
    Order,
    Resident,
    User,
    UserPenalty,
)
from src.domain import enums as E
from src.domain.state import item_sm
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:users"])

# W07 用户管理（C 端业主账号）。红线：禁止在此修改实名信息/认证状态，
# 认证必须走「住户认证」流程以保证审计链（详设 4.7.6）。


async def _row(db: DbSession, user: User) -> dict:
    resident = await db.scalar(
        select(Resident).where(Resident.user_id == user.id).order_by(Resident.id.desc()).limit(1))
    community_name = ""
    if resident:
        from src.db.models import Community

        community = await db.get(Community, resident.community_id)
        community_name = community.name if community else ""
    phone = decrypt_field(user.phone_enc)
    return {
        "id": str(user.id), "nickname": user.nickname, "phone": mask_phone(phone),
        "status": user.status, "realnameStatus": user.realname_status,
        "creditScore": user.credit_score, "creditLevel": user.credit_level,
        "communityName": community_name,
        "onboardingStatus": user.onboarding_status or "COMPLETED",
        "residentId": str(resident.id) if resident else "",
        "identityType": resident.identity_type if resident else "",
        "certificationStatus": resident.certification_status if resident else "UNVERIFIED",
        "registeredAt": int(user.registered_at.timestamp() * 1000) if user.registered_at else 0,
        "lastActiveAt": int(user.last_active_at.timestamp() * 1000) if user.last_active_at else 0,
    }


@router.get("/users",
            dependencies=[Depends(require_permission("system:user:view"))])
async def list_users(admin: CurrentAdmin, db: DbSession,
                     keyword: str | None = Query(default=None),
                     status: str | None = Query(default=None),
                     page: int = Query(default=1), pageSize: int = Query(default=20)):
    """用户检索：昵称模糊 + 手机号精确（哈希匹配，不明文索引）。"""
    stmt = select(User)
    if status:
        stmt = stmt.where(User.status == status)
    if keyword:
        keyword = keyword.strip()
        if keyword.isdigit() and len(keyword) == 11:
            stmt = stmt.where(User.phone_hash == hmac_index(keyword))
        else:
            stmt = stmt.where(User.nickname.ilike(f"%{keyword}%"))
    rows, total = await paginate(db, stmt.order_by(User.id.desc()), page, pageSize)
    return paginated([await _row(db, row) for row in rows], page, pageSize, total)


@router.get("/users/{user_id}",
            dependencies=[Depends(require_permission("system:user:view"))])
async def user_detail(user_id: int, admin: CurrentAdmin, db: DbSession):
    """用户 360°（W07-01）：脱敏信息、认证状态、绑定小区、信用、发布/交易/好友统计、处置记录。"""
    user = await db.get(User, user_id)
    if not user:
        raise ApiError(ERR_NOT_FOUND, "用户不存在", 404)
    row = await _row(db, user)
    row["publishCount"] = int((await db.scalar(
        select(func.count()).select_from(Item).where(Item.seller_id == user.id))) or 0)
    row["orderCount"] = int((await db.scalar(
        select(func.count()).select_from(Order).where(
            or_(Order.buyer_id == user.id, Order.seller_id == user.id)))) or 0)
    row["friendCount"] = int((await db.scalar(
        select(func.count()).select_from(Friend).where(
            Friend.user_id == user.id, Friend.status == "ACTIVE"))) or 0)
    row["penalties"] = [await _penalty_row(db, p) for p in (await db.execute(
        select(UserPenalty).where(UserPenalty.user_id == user.id)
        .order_by(UserPenalty.id.desc()))).scalars().all()]
    certs = list((await db.execute(
        select(Certification).where(Certification.user_id == user.id)
        .order_by(Certification.id.desc()))).scalars().all())
    row["certifications"] = [
        {"id": str(cert.id), "type": cert.type, "status": cert.status,
         "rejectReason": cert.reject_reason, "rejectCount": cert.reject_count,
         "submittedAt": int(cert.submitted_at.timestamp() * 1000) if cert.submitted_at else 0}
        for cert in certs
    ]
    return ok(row)


@router.patch("/users/{user_id}/status",
              dependencies=[Depends(require_permission("system:user:update"))])
async def toggle_user_status(user_id: int, payload: dict, request: Request,
                             admin: CurrentAdmin, db: DbSession):
    """停用/启用账号（FROZEN 联动封禁语义；下架物品请走处置 BAN）。"""
    user = await db.get(User, user_id)
    if not user:
        raise ApiError(ERR_NOT_FOUND, "用户不存在", 404)
    status = payload.get("status", "")
    if status not in ("ACTIVE", "FROZEN"):
        raise ApiError(ERR_PARAM, "状态不合法", 400)
    before = {"status": user.status}
    user.status = status
    await write_audit(db, request, actor=admin, action="user.status",
                      resource_type="user", resource_id=user.id,
                      before=before, after={"status": status})
    await db.commit()
    return ok(await _row(db, user), "账号状态已更新")


async def _penalty_row(db: DbSession, penalty: UserPenalty) -> dict:
    operator_name = ""
    if penalty.operator_id:
        from src.db.models import AdminUser

        operator = await db.get(AdminUser, penalty.operator_id)
        operator_name = operator.real_name if operator else ""
    return {
        "id": str(penalty.id), "type": penalty.type, "reason": penalty.reason,
        "status": penalty.status,
        "startAt": int(penalty.start_at.timestamp() * 1000) if penalty.start_at else 0,
        "endAt": int(penalty.end_at.timestamp() * 1000) if penalty.end_at else 0,
        "operator": operator_name,
    }


class PenaltyIn(BaseModel):
    type: str  # WARNING / MUTE / PUBLISH_LIMIT / TRADE_LIMIT / BAN
    reason: str
    endAt: int | None = None  # 毫秒时间戳，空为不限期


@router.post("/users/{user_id}/penalties",
             dependencies=[Depends(require_permission("system:user:penalty"))])
async def create_penalty(user_id: int, payload: PenaltyIn, request: Request,
                         admin: CurrentAdmin, db: DbSession):
    """用户处置（W07-02）：必填原因并留痕；封禁自动下架在售物品（W02-04 联动）。"""
    user = await db.get(User, user_id)
    if not user:
        raise ApiError(ERR_NOT_FOUND, "用户不存在", 404)
    if payload.type not in (E.PenaltyType.WARNING, E.PenaltyType.MUTE,
                            E.PenaltyType.PUBLISH_LIMIT, E.PenaltyType.TRADE_LIMIT,
                            E.PenaltyType.BAN):
        raise ApiError(ERR_PARAM, "处置类型不合法", 400)
    if len(payload.reason.strip()) < 5:
        raise ApiError(ERR_PARAM, "处置原因必填（不少于 5 个字）", 400)

    end_at = None
    if payload.endAt:
        from datetime import datetime

        end_at = datetime.fromtimestamp(payload.endAt / 1000)
    penalty = UserPenalty(user_id=user_id, type=payload.type,
                          reason=payload.reason.strip(), operator_id=admin.id,
                          end_at=end_at, status="ACTIVE")
    db.add(penalty)

    removed = 0
    if payload.type == E.PenaltyType.BAN:
        user.status = "FROZEN"
        items = list((await db.execute(
            select(Item).where(Item.seller_id == user_id,
                               Item.status == E.ItemStatus.ON_SALE))).scalars().all())
        for item in items:
            item.status = item_sm.fire(item.status, E.ItemStatus.OFF_SHELF)
            removed += 1

    await notify_user(db, user_id, category="COMMUNITY",
                      title="账号处置通知",
                      description=f"因违规处理：{payload.reason.strip()}"[:120],
                      icon="shield", tag="处置")
    await write_audit(db, request, actor=admin, action="user.penalty",
                      resource_type="user", resource_id=user_id,
                      before=None, after={"type": payload.type,
                                          "reason": payload.reason.strip(),
                                          "itemsOffShelves": removed})
    await db.commit()
    return ok(await _penalty_row(db, penalty),
              f"处置已生效{('，' + str(removed) + ' 件在售物品已下架') if removed else ''}")


@router.get("/users/{user_id}/penalties",
            dependencies=[Depends(require_permission("system:user:view"))])
async def list_penalties(user_id: int, admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(UserPenalty).where(UserPenalty.user_id == user_id)
        .order_by(UserPenalty.id.desc()))).scalars().all())
    return ok([await _penalty_row(db, row) for row in rows])


@router.post("/users/{user_id}/penalties/{penalty_id}/revoke",
             dependencies=[Depends(require_permission("system:user:penalty"))])
async def revoke_penalty(user_id: int, penalty_id: int, request: Request,
                         admin: CurrentAdmin, db: DbSession):
    penalty = await db.get(UserPenalty, penalty_id)
    if not penalty or penalty.user_id != user_id:
        raise ApiError(ERR_NOT_FOUND, "处置记录不存在", 404)
    if penalty.status != "ACTIVE":
        raise ApiError(ERR_PARAM, "处置已解除", 400)
    penalty.status = "REVOKED"
    # 若解除的是封禁且无其他封禁，恢复账号
    user = await db.get(User, user_id)
    if user and penalty.type == E.PenaltyType.BAN:
        active_bans = await db.scalar(
            select(UserPenalty.id).where(UserPenalty.user_id == user_id,
                                         UserPenalty.type == E.PenaltyType.BAN,
                                         UserPenalty.status == "ACTIVE").limit(1))
        if not active_bans:
            user.status = "ACTIVE"
    await write_audit(db, request, actor=admin, action="user.penalty.revoke",
                      resource_type="user", resource_id=user_id,
                      before={"penaltyId": penalty_id, "type": penalty.type},
                      after={"status": "REVOKED"})
    await db.commit()
    return ok(await _penalty_row(db, penalty), "处置已解除")
