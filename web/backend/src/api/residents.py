from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.api.utils import get_or_404, paginate
from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ApiError, ok, paginated
from src.db.models import Resident

router = APIRouter(tags=["residents"])


class ResidentIn(BaseModel):
    communityId: int
    name: str
    gender: str = "女"
    phone: str = ""
    identity: str = "业主"
    building: str = ""
    relationship: str = ""
    certification: str = "未认证"
    certificationNo: str = "—"
    level: str = "普通用户"
    status: str = "正常"
    joinedAt: str = "2025-03-20"


def serialize(row: Resident) -> dict:
    return {
        "id": str(row.id),
        "communityId": str(row.community_id),
        "name": row.name,
        "gender": row.gender,
        "phone": row.phone,
        "identity": row.identity_type,
        "identityType": row.identity_type,
        "building": row.building,
        "relationship": row.relationship,
        "certification": row.certification_status,
        "certificationStatus": row.certification_status,
        "certificationNo": row.certification_no,
        "level": row.level,
        "status": row.status,
        "joinedAt": row.joined_at,
    }


@router.get("/residents")
async def list_residents(
    db: DbSession,
    admin: CurrentAdmin,
    communityId: int | None = Query(default=None),
    identity: str | None = Query(default=None),
    certification: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1),
    pageSize: int = Query(default=20),
):
    stmt = select(Resident)
    if communityId:
        stmt = stmt.where(Resident.community_id == communityId)
    if identity and identity != "全部人员":
        stmt = stmt.where(Resident.identity_type == identity)
    if certification:
        stmt = stmt.where(Resident.certification_status == certification)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            Resident.name.ilike(like), Resident.phone.ilike(like),
            Resident.building.ilike(like), Resident.certification_no.ilike(like),
        ))
    stmt = stmt.order_by(Resident.id)
    rows, total = await paginate(db, stmt, page, pageSize)
    return paginated([serialize(row) for row in rows], page, pageSize, total)


@router.get("/residents/summary")
async def resident_summary(db: DbSession, admin: CurrentAdmin, communityId: int = Query(default=1)):
    total = int((await db.scalar(select(func.count()).select_from(Resident).where(Resident.community_id == communityId))) or 0)
    owner = int((await db.scalar(select(func.count()).select_from(Resident).where(
        Resident.community_id == communityId, Resident.identity_type == "业主"))) or 0)
    family = int((await db.scalar(select(func.count()).select_from(Resident).where(
        Resident.community_id == communityId, Resident.identity_type.in_(["家属", "租户"])))) or 0)
    pending = int((await db.scalar(select(func.count()).select_from(Resident).where(
        Resident.community_id == communityId, Resident.certification_status != "已认证"))) or 0)
    return ok({"total": total, "owner": owner, "family": family, "pending": pending})


@router.post("/residents")
async def create_resident(payload: ResidentIn, db: DbSession, admin: CurrentAdmin):
    row = Resident(
        community_id=payload.communityId, name=payload.name, gender=payload.gender, phone=payload.phone,
        identity_type=payload.identity, building=payload.building, relationship=payload.relationship,
        certification_status=payload.certification, certification_no=payload.certificationNo,
        level=payload.level, status=payload.status, joined_at=payload.joinedAt,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize(row), "人员档案已创建")


@router.put("/residents/{resident_id}")
async def update_resident(resident_id: int, payload: ResidentIn, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Resident, resident_id)
    row.name = payload.name
    row.gender = payload.gender
    row.phone = payload.phone
    row.identity_type = payload.identity
    row.building = payload.building
    row.relationship = payload.relationship
    row.certification_status = payload.certification
    row.certification_no = payload.certificationNo
    row.level = payload.level
    row.status = payload.status
    await db.commit()
    return ok(serialize(row), "人员信息已更新")


@router.delete("/residents/{resident_id}")
async def delete_resident(resident_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Resident, resident_id)
    await db.delete(row)
    await db.commit()
    return ok(None, "人员档案已删除")


@router.get("/certifications")
async def certifications(db: DbSession, admin: CurrentAdmin, status: str | None = Query(default="待审核")):
    stmt = select(Resident)
    if status:
        stmt = stmt.where(Resident.certification_status == status)
    rows = list((await db.execute(stmt.order_by(Resident.id))).scalars().all())
    return ok([serialize(row) for row in rows])


@router.post("/certifications/{resident_id}/review")
async def review_certification(resident_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Resident, resident_id)
    decision = payload.get("decision", "APPROVE")
    if decision == "APPROVE":
        row.certification_status = "已认证"
        row.certification_no = payload.get("certificationNo") or row.certification_no
    else:
        if not payload.get("reason"):
            raise ApiError(40001, "驳回原因必填", 400)
        row.certification_status = "认证驳回"
        row.certification_no = "—"
    await db.commit()
    return ok(serialize(row), "认证审核已完成")


@router.get("/verifications")
async def verifications(db: DbSession, admin: CurrentAdmin):
    rows = list((await db.execute(
        select(Resident).where(Resident.certification_status == "待审核").order_by(Resident.id)
    )).scalars().all())
    return ok([serialize(row) for row in rows])
