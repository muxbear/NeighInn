from __future__ import annotations

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
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.core.security import decrypt_field, mask_phone
from src.core.storage import presign_download
from src.db.models import Certification, Community, Item, Resident, User
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import certification_sm, item_sm
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:residents"])

AuditPerm = Depends(require_permission("community:resident:audit"))

IDENTITY_MAP = {"owner": "业主", "tenant": "租户", "family": "家属", "business": "商务人员"}


# ---------------------------------------------------------------- 序列化

async def _cert_row(db: DbSession, cert: Certification) -> dict:
    user = await db.get(User, cert.user_id)
    community = await db.get(Community, cert.community_id) if cert.community_id else None
    phone = decrypt_field(user.phone_enc) if user else ""
    return {
        "id": str(cert.id),
        "type": cert.type,
        "identity": cert.identity,
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
        },
        "community": {"id": str(cert.community_id), "name": community.name if community else ""},
    }


async def _cert_detail(db: DbSession, cert: Certification) -> dict:
    row = await _cert_row(db, cert)
    # 材料：对象键 + 10 分钟签名 URL（MinIO 不可用时仅返回键，W02-02 查看原图另行授权审计）
    row["materials"] = [
        {"objectKey": key, "signedUrl": presign_download(key)} for key in (cert.materials or [])
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


# ---------------------------------------------------------------- 认证审核队列（W02）

@router.get("/certifications")
async def list_certifications(
    admin: CurrentAdmin, db: DbSession,
    type: str | None = Query(default=None),
    status: str | None = Query(default="PENDING"),
    communityId: int | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Certification)
    if type:
        stmt = stmt.where(Certification.type == type)
    if status:
        stmt = stmt.where(Certification.status == status)
    if communityId:
        stmt = stmt.where(Certification.community_id == communityId)
    rows, total = await paginate(db, stmt.order_by(Certification.id), page, pageSize)
    return paginated([await _cert_row(db, row) for row in rows], page, pageSize, total)


@router.get("/certifications/{certification_id}")
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
        description="实名认证已通过" if cert.type == "REALNAME" else "业主证明已通过，已绑定小区",
        icon="shield", tag="认证",
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
            icon="lock", tag="认证",
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
            icon="unlock", tag="认证",
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
            icon="shield-off", tag="认证",
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
