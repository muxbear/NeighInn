from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.api.utils import paginate
from src.core.audit import write_audit, write_outbox
from src.core.deps import CurrentAdmin, DbSession
from src.core.idempotency import complete_idempotency, guard_idempotency
from src.core.permissions import require_permission
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_CONFLICT,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.core.security import decrypt_field, encrypt_field, hmac_index, mask_phone
from src.core.storage import presign_download
from src.db.models import Certification, Community, Item, Resident, User
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import certification_sm, item_sm
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:residents"])

AuditPerm = Depends(require_permission("community:resident:audit"))

IDENTITY_MAP = {"owner": "业主", "tenant": "租户", "family": "家属", "business": "商务人员"}
TYPE_LABEL = {"REALNAME": "实名认证", "OWNER_PROOF": "住户认证"}

# 档案编辑沿用页面中文标签，服务端统一转换为领域编码（SRS 8.3 统一契约）。
IDENTITY_ALIASES = {
    **{label: label for label in IDENTITY_MAP.values()},
    **IDENTITY_MAP,
}
CERT_STATUS_ALIASES = {
    "未认证": "UNVERIFIED", "UNVERIFIED": "UNVERIFIED",
    "待审核": "PENDING", "审核中": "PENDING", "PENDING": "PENDING",
    "已认证": "VERIFIED", "认证通过": "VERIFIED", "VERIFIED": "VERIFIED",
    "认证驳回": "REJECTED", "已驳回": "REJECTED", "REJECTED": "REJECTED",
    "待补充": "SUPPLEMENT", "SUPPLEMENT": "SUPPLEMENT",
    "已冻结": "FROZEN", "已冻结认证": "FROZEN", "FROZEN": "FROZEN",
    "已撤销": "REVOKED", "REVOKED": "REVOKED",
}
CERT_STATUS_LABEL = {
    "UNVERIFIED": "未认证", "PENDING": "待审核", "VERIFIED": "已认证",
    "REJECTED": "认证驳回", "SUPPLEMENT": "待补充",
    "FROZEN": "已冻结", "REVOKED": "已撤销",
}
RESIDENT_STATUS_ALIASES = {
    "正常": "ACTIVE", "ACTIVE": "ACTIVE",
    "已停用": "FROZEN", "停用": "FROZEN", "已冻结": "FROZEN", "FROZEN": "FROZEN",
    "已离开": "LEFT", "LEFT": "LEFT",
}
GENDERS = {"男", "女", ""}
LEVELS = {"普通用户", "活跃用户", "社区达人", "重点关怀"}
PHONE_PATTERN = re.compile(r"^1\d{10}$")


class ResidentIn(BaseModel):
    communityId: int | None = None
    name: str = ""
    gender: str = "女"
    phone: str = ""
    identity: str = "业主"
    building: str = ""
    relationship: str = ""
    certification: str = "未认证"
    certificationNo: str = ""
    level: str = "普通用户"
    status: str = "正常"
    joinedAt: str | None = None


def _normalize_choice(raw: str, aliases: dict[str, str], field: str) -> str:
    value = (raw or "").strip()
    resolved = aliases.get(value) or aliases.get(value.upper())
    if not resolved:
        raise ApiError(ERR_PARAM, f"{field}不合法", 400)
    return resolved


def _normalize_phone(raw: str, *, allow_masked: bool) -> str | None:
    """返回 None 表示未提交有效手机号（编辑时传入脱敏号码视为不修改）。"""
    value = (raw or "").strip()
    if allow_masked and "*" in value:
        return None
    if not value:
        return ""
    if not PHONE_PATTERN.match(value):
        raise ApiError(ERR_PARAM, "手机号格式不正确（11 位大陆手机号）", 400)
    return value


def _parse_joined_at(raw: str | None) -> datetime:
    if not raw:
        return utcnow()
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError as exc:
        raise ApiError(ERR_PARAM, "加入时间格式不正确（YYYY-MM-DD）", 400) from exc


def _validate_profile_text(payload: ResidentIn) -> None:
    if len(payload.building.strip()) > 128:
        raise ApiError(ERR_PARAM, "房屋 / 商铺最多 128 字", 400)
    if len(payload.relationship.strip()) > 64:
        raise ApiError(ERR_PARAM, "与房屋关系最多 64 字", 400)
    if len(payload.certificationNo.strip()) > 32:
        raise ApiError(ERR_PARAM, "认证编号最多 32 字", 400)


# ---------------------------------------------------------------- 序列化

async def _cert_row(db: DbSession, cert: Certification) -> dict:
    user = await db.get(User, cert.user_id)
    community = await db.get(Community, cert.community_id) if cert.community_id else None
    phone = decrypt_field(user.phone_enc) if user else ""
    return {
        "id": str(cert.id),
        "type": cert.type,
        "typeLabel": TYPE_LABEL.get(cert.type, cert.type),
        "identity": cert.identity,
        "identityLabel": IDENTITY_MAP.get(cert.identity, cert.identity),
        "status": cert.status,
        "rejectCount": cert.reject_count,
        "rejectReason": cert.reject_reason,
        "traceId": cert.trace_id,
        "version": cert.version,
        "submittedAt": int(cert.submitted_at.timestamp() * 1000) if cert.submitted_at else 0,
        "reviewedAt": int(cert.reviewed_at.timestamp() * 1000) if cert.reviewed_at else 0,
        "user": {
            "id": str(cert.user_id),
            "nickname": user.nickname if user else "",
            "phone": mask_phone(phone),
            "realnameStatus": user.realname_status if user else "UNVERIFIED",
        },
        "community": {"id": str(cert.community_id), "name": community.name if community else ""},
    }


async def _cert_detail(db: DbSession, cert: Certification) -> dict:
    row = await _cert_row(db, cert)
    # 材料：对象键 + 10 分钟签名 URL（MinIO 不可用时仅返回键，W02-02 查看原图另行授权审计）
    if cert.type == "REALNAME":
        labels = ["身份证人像面", "身份证国徽面"]
    else:
        labels = [f"证明材料 {index + 1}" for index in range(len(cert.materials or []))]
    row["materials"] = [
        {
            "objectKey": key,
            "signedUrl": presign_download(key),
            "label": labels[index] if index < len(labels) else f"补充材料 {index + 1}",
        }
        for index, key in enumerate(cert.materials or [])
    ]
    row["autoResult"] = cert.auto_result or {}
    return row


async def _resident_row(db: DbSession, resident: Resident) -> dict:
    community = await db.get(Community, resident.community_id)
    return {
        "id": str(resident.id),
        "communityId": str(resident.community_id),
        "communityName": community.name if community else "",
        "userId": str(resident.user_id) if resident.user_id else "",
        "name": resident.name,
        "gender": resident.gender,
        "phone": mask_phone(decrypt_field(resident.phone_enc)),
        "identity": resident.identity_type,
        "building": resident.building,
        "relationship": resident.relationship,
        "certification": resident.certification_status,
        "certificationNo": resident.certification_no,
        "level": resident.level,
        "status": resident.status,
        "joinedAt": resident.joined_at.strftime("%Y-%m-%d") if resident.joined_at else "",
    }


# ---------------------------------------------------------------- 业主档案（查询）

@router.get("/residents")
async def list_residents(
    admin: CurrentAdmin, db: DbSession,
    communityId: int | None = Query(default=None),
    identity: str | None = Query(default=None),
    certification: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Resident)
    if communityId:
        stmt = stmt.where(Resident.community_id == communityId)
    if identity and identity != "全部人员":
        stmt = stmt.where(Resident.identity_type == identity)
    if certification:
        stmt = stmt.where(Resident.certification_status == certification)
    if keyword:
        stmt = stmt.where(or_(Resident.name.ilike(f"%{keyword}%"),
                              Resident.building.ilike(f"%{keyword}%"),
                              Resident.certification_no.ilike(f"%{keyword}%")))
    rows, total = await paginate(db, stmt.order_by(Resident.id.desc()), page, pageSize)
    return paginated([await _resident_row(db, row) for row in rows], page, pageSize, total)


@router.get("/residents/summary")
async def resident_summary(admin: CurrentAdmin, db: DbSession,
                           communityId: int = Query(default=1)):
    async def _count(*conditions) -> int:
        return int((await db.scalar(
            select(func.count()).select_from(Resident).where(*conditions))) or 0)

    return ok({
        "total": await _count(Resident.community_id == communityId),
        "owner": await _count(Resident.community_id == communityId,
                              Resident.identity_type == "业主"),
        "family": await _count(Resident.community_id == communityId,
                               Resident.identity_type.in_(["家属", "租户"])),
        "pending": await _count(Resident.community_id == communityId,
                                Resident.certification_status.in_(["PENDING", "UNVERIFIED"])),
    })


@router.get("/residents/{resident_id}")
async def resident_detail(resident_id: int, admin: CurrentAdmin, db: DbSession):
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    return ok(await _resident_row(db, resident))


# ---------------------------------------------------------------- 业主档案（新增 / 编辑 / 删除）

async def _assert_unique_phone(db: DbSession, community_id: int, phone_hash: str,
                               exclude_id: int | None = None) -> None:
    """同一社区内手机号唯一，避免同一住户重复建档（后台详设 5.6.1）。"""
    if not phone_hash:
        return
    stmt = select(Resident.id).where(
        Resident.community_id == community_id, Resident.phone_hash == phone_hash)
    if exclude_id is not None:
        stmt = stmt.where(Resident.id != exclude_id)
    if await db.scalar(stmt):
        raise ApiError(ERR_CONFLICT, "该手机号在本社区已存在人员档案", 409)


async def _match_user_id(db: DbSession, phone_hash: str) -> int | None:
    if not phone_hash:
        return None
    return await db.scalar(select(User.id).where(User.phone_hash == phone_hash))


@router.post("/residents",
             dependencies=[Depends(require_permission("community:resident:create"))])
async def create_resident(payload: ResidentIn, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    name = payload.name.strip()
    if not name:
        raise ApiError(ERR_PARAM, "人员姓名必填", 400)
    if len(name) > 64:
        raise ApiError(ERR_PARAM, "人员姓名最多 64 字", 400)
    if not payload.communityId:
        raise ApiError(ERR_PARAM, "请选择所属社区", 400)
    community = await db.get(Community, payload.communityId)
    if not community:
        raise ApiError(ERR_PARAM, "所属社区不存在", 400)

    gender = payload.gender.strip()
    if gender not in GENDERS:
        raise ApiError(ERR_PARAM, "性别不合法", 400)
    identity = _normalize_choice(payload.identity, IDENTITY_ALIASES, "身份类型")
    cert_status = _normalize_choice(payload.certification, CERT_STATUS_ALIASES, "认证状态")
    status = _normalize_choice(payload.status, RESIDENT_STATUS_ALIASES, "账号状态")
    level = payload.level.strip() or "普通用户"
    if level not in LEVELS:
        raise ApiError(ERR_PARAM, "用户级别不合法", 400)
    _validate_profile_text(payload)

    phone = _normalize_phone(payload.phone, allow_masked=False) or ""
    phone_hash = hmac_index(phone) if phone else ""
    await _assert_unique_phone(db, community.id, phone_hash)

    resident = Resident(
        user_id=await _match_user_id(db, phone_hash),
        community_id=community.id, name=name, gender=gender,
        phone_enc=encrypt_field(phone), phone_hash=phone_hash,
        identity_type=identity, building=payload.building.strip(),
        relationship=payload.relationship.strip(),
        certification_status=cert_status,
        certification_no=payload.certificationNo.strip(),
        level=level, status=status, joined_at=_parse_joined_at(payload.joinedAt),
    )
    db.add(resident)
    await db.flush()
    if resident.certification_status == "VERIFIED" and not resident.certification_no:
        resident.certification_no = f"YZ{resident.id:08d}"
    await write_audit(db, request, actor=admin, action="resident.create",
                      resource_type="resident", resource_id=resident.id,
                      before=None, after=await _resident_row(db, resident))
    await db.commit()
    return ok(await _resident_row(db, resident), "人员档案已创建")


@router.put("/residents/{resident_id}",
            dependencies=[Depends(require_permission("community:resident:update"))])
async def update_resident(resident_id: int, payload: ResidentIn, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    fields = payload.model_fields_set
    before = await _resident_row(db, resident)

    if "communityId" in fields and payload.communityId \
            and payload.communityId != resident.community_id:
        raise ApiError(ERR_PARAM, "人员档案不可跨社区迁移，请在目标社区新建档案", 400)

    if "name" in fields:
        name = payload.name.strip()
        if not name:
            raise ApiError(ERR_PARAM, "人员姓名必填", 400)
        if len(name) > 64:
            raise ApiError(ERR_PARAM, "人员姓名最多 64 字", 400)
        resident.name = name

    if "gender" in fields:
        gender = payload.gender.strip()
        if gender not in GENDERS:
            raise ApiError(ERR_PARAM, "性别不合法", 400)
        resident.gender = gender

    if "phone" in fields:
        phone = _normalize_phone(payload.phone, allow_masked=True)
        if phone is not None and phone != decrypt_field(resident.phone_enc):
            phone_hash = hmac_index(phone) if phone else ""
            await _assert_unique_phone(db, resident.community_id, phone_hash,
                                       exclude_id=resident.id)
            resident.phone_enc = encrypt_field(phone)
            resident.phone_hash = phone_hash
            if resident.user_id is None:
                resident.user_id = await _match_user_id(db, phone_hash)

    if "identity" in fields:
        resident.identity_type = _normalize_choice(
            payload.identity, IDENTITY_ALIASES, "身份类型")
    if "building" in fields:
        resident.building = payload.building.strip()
    if "relationship" in fields:
        resident.relationship = payload.relationship.strip()
    if "level" in fields:
        level = payload.level.strip()
        if level and level not in LEVELS:
            raise ApiError(ERR_PARAM, "用户级别不合法", 400)
        resident.level = level or resident.level
    if "status" in fields and payload.status.strip():
        resident.status = _normalize_choice(
            payload.status, RESIDENT_STATUS_ALIASES, "账号状态")
    if "certification" in fields and payload.certification.strip():
        target = _normalize_choice(payload.certification, CERT_STATUS_ALIASES, "认证状态")
        current = CERT_STATUS_ALIASES.get(resident.certification_status,
                                          resident.certification_status)
        if target != current:
            if not certification_sm.can_fire(current, target):
                current_label = CERT_STATUS_LABEL.get(current, current)
                raise ApiError(
                    ERR_BIZ_RULE,
                    f"认证状态不能从「{current_label}」直接改为"
                    f"「{CERT_STATUS_LABEL.get(target, target)}」，请通过认证审核流程处理",
                    422,
                )
            resident.certification_status = certification_sm.fire(current, target)
        else:
            resident.certification_status = current
    if "certificationNo" in fields:
        resident.certification_no = payload.certificationNo.strip()
    if "joinedAt" in fields and payload.joinedAt:
        resident.joined_at = _parse_joined_at(payload.joinedAt)

    _validate_profile_text(payload)
    if resident.certification_status == "VERIFIED" and not resident.certification_no:
        resident.certification_no = f"YZ{resident.id:08d}"
    await write_audit(db, request, actor=admin, action="resident.update",
                      resource_type="resident", resource_id=resident.id,
                      before=before, after=await _resident_row(db, resident))
    await db.commit()
    return ok(await _resident_row(db, resident), "人员信息已更新")


@router.delete("/residents/{resident_id}",
               dependencies=[Depends(require_permission("community:resident:update"))])
async def delete_resident(resident_id: int, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    """删除人员档案；已关联的认证审核单保留历史，仅解除档案引用。"""
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    before = await _resident_row(db, resident)
    certs = (await db.execute(
        select(Certification).where(Certification.resident_id == resident.id)
    )).scalars().all()
    for cert in certs:
        cert.resident_id = None
    await db.delete(resident)
    await write_audit(db, request, actor=admin, action="resident.delete",
                      resource_type="resident", resource_id=resident_id,
                      before=before, after=None)
    await db.commit()
    return ok({"id": str(resident_id)}, "人员档案已删除")


# ---------------------------------------------------------------- 认证审核队列（W02）

@router.get("/certifications", dependencies=[AuditPerm])
async def list_certifications(
    admin: CurrentAdmin, db: DbSession,
    type: str | None = Query(default=None),
    status: str | None = Query(default="PENDING"),
    communityId: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Certification)
    if type:
        stmt = stmt.where(Certification.type == type)
    if status:
        stmt = stmt.where(Certification.status == status)
    if communityId:
        stmt = stmt.where(Certification.community_id == communityId)
    keyword = (keyword or "").strip()
    if keyword:
        stmt = stmt.join(User, User.id == Certification.user_id)
        if keyword.isdigit() and len(keyword) == 11:
            stmt = stmt.where(User.phone_hash == hmac_index(keyword))
        else:
            stmt = stmt.where(or_(
                User.nickname.ilike(f"%{keyword}%"),
                Certification.trace_id.ilike(f"%{keyword}%"),
            ))
    rows, total = await paginate(
        db,
        stmt.order_by(Certification.submitted_at.desc(), Certification.id.desc()),
        page, pageSize,
    )
    return paginated([await _cert_row(db, row) for row in rows], page, pageSize, total)


@router.get("/certifications/summary", dependencies=[AuditPerm])
async def certification_summary(
    admin: CurrentAdmin, db: DbSession,
    communityId: int | None = Query(default=None),
):
    base_conditions = []
    if communityId:
        base_conditions.append(Certification.community_id == communityId)

    async def _count(*conditions) -> int:
        return int((await db.scalar(
            select(func.count()).select_from(Certification).where(*conditions))) or 0)

    pending = await _count(Certification.status == "PENDING", *base_conditions)
    pending_realname = await _count(
        Certification.status == "PENDING", Certification.type == "REALNAME", *base_conditions)
    pending_owner = await _count(
        Certification.status == "PENDING", Certification.type == "OWNER_PROOF", *base_conditions)
    supplement = await _count(Certification.status == "SUPPLEMENT", *base_conditions)
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_reviewed = int((await db.scalar(
        select(func.count()).select_from(Certification).where(
            Certification.reviewed_at >= today_start, *base_conditions))) or 0)
    oldest = await db.scalar(
        select(func.min(Certification.submitted_at)).where(
            Certification.status == "PENDING", *base_conditions))
    return ok({
        "pending": pending,
        "pendingRealname": pending_realname,
        "pendingOwner": pending_owner,
        "supplement": supplement,
        "todayReviewed": today_reviewed,
        "oldestPendingAt": int(oldest.timestamp() * 1000) if oldest else 0,
    })


@router.get("/certifications/{certification_id}", dependencies=[AuditPerm])
async def certification_detail(certification_id: int, admin: CurrentAdmin, db: DbSession):
    cert = await db.get(Certification, certification_id)
    if not cert:
        raise ApiError(ERR_NOT_FOUND, "审核单不存在", 404)
    return ok(await _cert_detail(db, cert))


class RejectIn(BaseModel):
    reason: str


class NoteIn(BaseModel):
    note: str = ""


async def _get_cert_or_404(db: DbSession, certification_id: int) -> Certification:
    cert = await db.get(Certification, certification_id)
    if not cert:
        raise ApiError(ERR_NOT_FOUND, "审核单不存在", 404)
    return cert


@router.post("/certifications/{certification_id}/approve",
             dependencies=[AuditPerm])
async def approve_certification(
    certification_id: int, request: Request, admin: CurrentAdmin, db: DbSession,
):
    """W02-02 通过：业主证明通过后账号与小区强绑定（BR-02）；实名通过更新实名状态。
    审核动作写审计（W01-03），并向申请人发送站内通知（M01-04）。"""
    cert = await _get_cert_or_404(db, certification_id)
    idem = await guard_idempotency(db, request, {"id": certification_id, "action": "approve"})
    if idem and idem.status == "COMPLETED":
        return ok(idem.response_json["data"])

    before = {"status": cert.status}
    cert.status = certification_sm.fire(cert.status, E.CertificationStatus.VERIFIED)
    cert.reviewer_id = admin.id
    cert.reviewed_at = utcnow()

    user = await db.get(User, cert.user_id)
    if cert.type == "REALNAME" and user:
        user.realname_status = "VERIFIED"
    if cert.type == "OWNER_PROOF" and cert.community_id:
        resident = await db.scalar(select(Resident).where(
            Resident.user_id == cert.user_id, Resident.community_id == cert.community_id))
        if not resident:
            resident = Resident(
                user_id=cert.user_id, community_id=cert.community_id,
                name=user.nickname if user else "", gender="",
                identity_type=IDENTITY_MAP.get(cert.identity, "业主"),
            )
            db.add(resident)
            await db.flush()
        resident.certification_status = "VERIFIED"
        resident.certification_no = f"YZ{cert.id:08d}"
        resident.joined_at = resident.joined_at or utcnow()
        resident.status = "ACTIVE"
        cert.resident_id = resident.id

    await notify_user(
        db, cert.user_id, category="COMMUNITY", title="认证审核通过",
        description="实名认证已通过" if cert.type == "REALNAME" else "住户认证已通过，已绑定小区",
        icon="shield", tag="认证", route={"type": "certification"},
    )
    await write_audit(
        db, request, actor=admin, action=f"certification.{cert.type.lower()}.approve",
        resource_type="certification", resource_id=cert.id,
        before=before, after={"status": cert.status},
    )
    await write_outbox(db, event_type="CertificationApproved",
                       aggregate_type="certification", aggregate_id=cert.id,
                       payload={"type": cert.type, "userId": cert.user_id,
                                "communityId": cert.community_id})
    data = await _cert_row(db, cert)
    await complete_idempotency(db, idem, data)
    await db.commit()
    return ok(data, "审核已通过")


@router.post("/certifications/{certification_id}/reject",
             dependencies=[AuditPerm])
async def reject_certification(
    certification_id: int, payload: RejectIn, request: Request,
    admin: CurrentAdmin, db: DbSession,
):
    """W02-02 驳回：原因必填（≥10 字，详设 5.6.2 守卫），累计 3 次转人工（M01-05）。"""
    reason = payload.reason.strip()
    if len(reason) < 10:
        raise ApiError(ERR_PARAM, "驳回原因必填，且不少于 10 个字", 400)
    cert = await _get_cert_or_404(db, certification_id)
    idem = await guard_idempotency(db, request, {"id": certification_id, "action": "reject",
                                                 "reason": reason})
    if idem and idem.status == "COMPLETED":
        return ok(idem.response_json["data"])

    before = {"status": cert.status, "rejectCount": cert.reject_count}
    cert.status = certification_sm.fire(cert.status, E.CertificationStatus.REJECTED)
    cert.reject_reason = reason
    cert.reject_count += 1
    cert.reviewer_id = admin.id
    cert.reviewed_at = utcnow()

    await notify_user(
        db, cert.user_id, category="COMMUNITY", title="认证审核被驳回",
        description=reason, icon="shield-alert", tag="认证",
        route={"type": "certification"},
    )
    await write_audit(
        db, request, actor=admin, action=f"certification.{cert.type.lower()}.reject",
        resource_type="certification", resource_id=cert.id,
        before=before, after={"status": cert.status, "reason": reason,
                              "rejectCount": cert.reject_count},
    )
    data = await _cert_row(db, cert)
    await complete_idempotency(db, idem, data)
    await db.commit()
    return ok(data, "已驳回并通知申请人")


@router.post("/certifications/{certification_id}/request-materials",
             dependencies=[AuditPerm])
async def request_materials(
    certification_id: int, payload: NoteIn, request: Request,
    admin: CurrentAdmin, db: DbSession,
):
    """要求补充材料（W02-02）：状态转 SUPPLEMENT，通知申请人补齐后重新进入队列。"""
    cert = await _get_cert_or_404(db, certification_id)
    before = {"status": cert.status}
    cert.status = certification_sm.fire(cert.status, E.CertificationStatus.SUPPLEMENT)
    cert.reviewer_id = admin.id
    cert.review_note = payload.note
    cert.reviewed_at = utcnow()
    await notify_user(
        db, cert.user_id, category="COMMUNITY", title="认证材料需补充",
        description=payload.note or "请按要求补充证明材料后重新提交", icon="file", tag="认证",
        route={"type": "certification"},
    )
    await write_audit(db, request, actor=admin, action="certification.request-materials",
                      resource_type="certification", resource_id=cert.id,
                      before=before, after={"status": cert.status})
    await db.commit()
    return ok(await _cert_row(db, cert), "已要求补充材料")


@router.post("/certifications/{certification_id}/correct-community",
             dependencies=[AuditPerm])
async def correct_community(certification_id: int, payload: dict, admin: CurrentAdmin, db: DbSession):
    """认定小区与自选不一致时人工纠正（W02-02）。"""
    cert = await _get_cert_or_404(db, certification_id)
    community_id = payload.get("communityId")
    community = await db.get(Community, int(community_id)) if community_id else None
    if not community:
        raise ApiError(ERR_PARAM, "目标小区不存在", 400)
    cert.community_id = community.id
    await db.commit()
    return ok(await _cert_row(db, cert), "认定小区已纠正")


@router.get("/verifications")
async def list_verifications(admin: CurrentAdmin, db: DbSession):
    rows, _ = await paginate(
        db, select(Certification).where(Certification.status == "PENDING")
        .order_by(Certification.id), 1, 50)
    return ok([await _cert_row(db, row) for row in rows])


# ---------------------------------------------------------------- 冻结 / 解冻 / 撤销（W02-04）

async def _off_shelf_user_items(db: DbSession, user_id: int) -> int:
    """冻结/撤销联动：该用户全部在售物品自动下架（W02-04）。返回下架数量。"""
    rows = list((await db.execute(
        select(Item).where(Item.seller_id == user_id, Item.status == E.ItemStatus.ON_SALE)
    )).scalars().all())
    for item in rows:
        item.status = item_sm.fire(item.status, E.ItemStatus.OFF_SHELF)
    return len(rows)


async def _latest_owner_cert(db: DbSession, resident: Resident) -> Certification | None:
    if not resident.user_id:
        return None
    return await db.scalar(
        select(Certification)
        .where(Certification.user_id == resident.user_id,
               Certification.community_id == resident.community_id,
               Certification.type == "OWNER_PROOF")
        .order_by(Certification.id.desc()).limit(1))


@router.post("/residents/{resident_id}/freeze",
             dependencies=[Depends(require_permission("community:resident:freeze"))])
async def freeze_resident(resident_id: int, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    """冻结业主资格（W02-04）：认证状态转冻结，名下全部在售物品自动下架。"""
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    if resident.certification_status == "FROZEN":
        raise ApiError(ERR_BIZ_RULE, "该人员已处于冻结状态", 422)

    resident.certification_status = certification_sm.fire(
        resident.certification_status, E.CertificationStatus.FROZEN)
    cert = await _latest_owner_cert(db, resident)
    if cert and cert.status == "VERIFIED":
        cert.status = E.CertificationStatus.FROZEN

    removed = await _off_shelf_user_items(db, resident.user_id) if resident.user_id else 0
    if resident.user_id:
        await notify_user(
            db, resident.user_id, category="COMMUNITY", title="业主资格已被冻结",
            description="因违规处理，您的业主资格已被冻结，在售物品已自动下架。如有疑问请联系客服。",
            icon="lock", tag="认证", route={"type": "certification"},
        )
    await write_audit(db, request, actor=admin, action="resident.freeze",
                      resource_type="resident", resource_id=resident.id,
                      before={"certification": "VERIFIED"},
                      after={"certification": "FROZEN", "itemsOffShelves": removed})
    await db.commit()
    return ok({"certification": "FROZEN", "itemsOffShelves": removed},
              f"已冻结，{removed} 件在售物品自动下架")


@router.post("/residents/{resident_id}/unfreeze",
             dependencies=[Depends(require_permission("community:resident:freeze"))])
async def unfreeze_resident(resident_id: int, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    resident.certification_status = certification_sm.fire(
        resident.certification_status, E.CertificationStatus.VERIFIED)
    cert = await _latest_owner_cert(db, resident)
    if cert and cert.status == "FROZEN":
        cert.status = E.CertificationStatus.VERIFIED
    if resident.user_id:
        await notify_user(
            db, resident.user_id, category="COMMUNITY", title="业主资格已恢复",
            description="您的业主资格已解冻，下架物品需手动重新上架。",
            icon="unlock", tag="认证", route={"type": "certification"},
        )
    await write_audit(db, request, actor=admin, action="resident.unfreeze",
                      resource_type="resident", resource_id=resident.id,
                      before={"certification": "FROZEN"}, after={"certification": "VERIFIED"})
    await db.commit()
    return ok({"certification": "VERIFIED"}, "已解冻，物品需手动重新上架")


@router.post("/residents/{resident_id}/revoke",
             dependencies=[Depends(require_permission("community:resident:revoke"))])
async def revoke_certification(resident_id: int, request: Request,
                               admin: CurrentAdmin, db: DbSession):
    """撤销认证（W02-04）：证明材料造假、投诉坐实等场景。不可恢复，需重新提交认证。"""
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    resident.certification_status = certification_sm.fire(
        resident.certification_status, E.CertificationStatus.REVOKED)
    resident.certification_no = ""
    cert = await _latest_owner_cert(db, resident)
    if cert and cert.status in ("VERIFIED", "FROZEN"):
        cert.status = E.CertificationStatus.REVOKED
    removed = await _off_shelf_user_items(db, resident.user_id) if resident.user_id else 0
    if resident.user_id:
        await notify_user(
            db, resident.user_id, category="COMMUNITY", title="业主认证已被撤销",
            description="经核实，您的业主认证已被撤销，如需继续发布请重新提交认证材料。",
            icon="shield-off", tag="认证", route={"type": "certification"},
        )
    await write_audit(db, request, actor=admin, action="resident.revoke",
                      resource_type="resident", resource_id=resident.id,
                      before={"certification": "VERIFIED"},
                      after={"certification": "REVOKED", "itemsOffShelves": removed})
    await db.commit()
    return ok({"certification": "REVOKED", "itemsOffShelves": removed},
              "认证已撤销，需重新提交材料认证")


@router.get("/residents/{resident_id}/penalties")
async def resident_penalties(resident_id: int, admin: CurrentAdmin, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("GET /residents/{id}/penalties（W07 用户处置，Phase 2）")
