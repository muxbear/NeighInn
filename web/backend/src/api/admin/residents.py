from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from starlette.concurrency import run_in_threadpool

from src.api.utils import paginate
from src.core.audit import write_audit, write_outbox
from src.core.config import settings
from src.core.deps import CurrentAdmin, DbSession
from src.core.idempotency import complete_idempotency, guard_idempotency
from src.core.permissions import (
    allowed_community_ids,
    get_permission_codes,
    require_any_permission,
    require_permission,
    resolve_community_scope,
)
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_CONFLICT,
    ERR_DATA_SCOPE,
    ERR_DEPENDENCY,
    ERR_FILE_TOO_LARGE,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.core.security import (
    decrypt_field,
    encrypt_field,
    hash_password,
    hmac_index,
    mask_phone,
)
from src.core.storage import get_minio, presign_download
from src.db.models import (
    AdminUser,
    Certification,
    Community,
    Dispute,
    Item,
    LedgerEntry,
    Order,
    PaymentTransaction,
    PlatformUser,
    Resident,
    Role,
    User,
    WalletAccount,
    Withdrawal,
    admin_user_communities,
    admin_user_roles,
)
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import certification_sm, item_sm
from src.services.admin_account_service import (
    ensure_platform_user_for_resident,
    generate_initial_password,
    next_admin_username,
)
from src.services.notify_service import notify_user

router = APIRouter(tags=["admin:residents"])
logger = logging.getLogger(__name__)

AuditPerm = Depends(require_permission("community:resident:audit"))
ResidentUpdatePerm = Depends(require_permission("community:resident:update"))

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
    # 账号资料（关联 User）：后台编辑档案时可一并维护。
    nickname: str | None = None
    email: str | None = None
    bio: str | None = None
    gender: str = "女"
    phone: str = ""
    identity: str = "业主"
    building: str = ""
    relationship: str = ""
    certification: str = "未认证"
    realnameStatus: str | None = None
    creditScore: int | None = None
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
    if payload.nickname is not None and len(payload.nickname.strip()) > 24:
        raise ApiError(ERR_PARAM, "昵称最多 24 字", 400)
    if payload.email is not None and len(payload.email.strip()) > 128:
        raise ApiError(ERR_PARAM, "邮箱最多 128 字", 400)
    if payload.bio is not None and len(payload.bio.strip()) > 500:
        raise ApiError(ERR_PARAM, "个人描述最多 500 字", 400)


async def _apply_user_profile(db: DbSession, resident: Resident, payload: ResidentIn,
                              *, only_non_empty: bool) -> None:
    """把昵称 / 邮箱 / 个人描述写回关联账号；未绑定账号的档案忽略这些字段。"""
    if not resident.user_id:
        return
    user = await db.get(User, resident.user_id)
    if user is None:
        return
    if payload.nickname is not None and (payload.nickname.strip() or not only_non_empty):
        user.nickname = payload.nickname.strip()[:24]
    if payload.email is not None and (payload.email.strip() or not only_non_empty):
        user.email = payload.email.strip()[:128]
    if payload.bio is not None and (payload.bio.strip() or not only_non_empty):
        user.bio = payload.bio.strip()[:500]


async def _apply_user_status_fields(db: DbSession, resident: Resident,
                                    payload: ResidentIn) -> None:
    """后台直接维护身份认证状态与信用分（不受审核状态机 / 信用流水限制）。"""
    if not resident.user_id:
        return
    user = await db.get(User, resident.user_id)
    if user is None:
        return
    if payload.realnameStatus is not None:
        target = _normalize_choice(
            payload.realnameStatus, CERT_STATUS_ALIASES, "身份认证状态")
        user.realname_status = target
        await _sync_latest_cert_status(db, resident.user_id, "REALNAME", target)
    if payload.creditScore is not None:
        score = int(payload.creditScore)
        if not 0 <= score <= 1000:
            raise ApiError(ERR_PARAM, "信用分需在 0-1000 之间", 400)
        user.credit_score = score
        user.credit_level = _credit_level(score)


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


def _credit_level(score: int) -> str:
    if score >= 90:
        return "极好"
    if score >= 70:
        return "良好"
    if score >= 50:
        return "一般"
    return "待提升"


def _cert_brief(cert: Certification) -> dict:
    return {
        "id": str(cert.id),
        "type": cert.type,
        "status": cert.status,
        "submittedAt": int(cert.submitted_at.timestamp() * 1000) if cert.submitted_at else 0,
    }


async def _latest_certifications(db: DbSession, user_id: int) -> dict[str, Certification]:
    """取用户最近一次实名认证 / 业主认证审核单，供档案页查看认证照片。"""
    rows = list((await db.execute(
        select(Certification).where(
            Certification.user_id == user_id,
            Certification.type.in_(["REALNAME", "OWNER_PROOF"]),
        ).order_by(Certification.submitted_at.desc(), Certification.id.desc())
    )).scalars().all())
    latest: dict[str, Certification] = {}
    for cert in rows:
        latest.setdefault(cert.type, cert)
    return latest


async def _latest_cert(db: DbSession, user_id: int, cert_type: str) -> Certification | None:
    return await db.scalar(
        select(Certification)
        .where(Certification.user_id == user_id, Certification.type == cert_type)
        .order_by(Certification.submitted_at.desc(), Certification.id.desc())
        .limit(1)
    )


async def _sync_latest_cert_status(db: DbSession, user_id: int | None,
                                   cert_type: str, status: str) -> None:
    """后台直改认证状态时同步最近一张审核单，保证档案与认证材料页展示一致。"""
    if not user_id:
        return
    cert = await _latest_cert(db, user_id, cert_type)
    if cert is not None:
        cert.status = status


async def _admin_accounts_map(db: DbSession, residents: list[Resident]) -> dict[int, dict]:
    """批量装配住户的后台身份，避免列表逐行查询。key 为 resident.id。"""
    if not residents:
        return {}
    resident_ids = [row.id for row in residents]
    user_ids = [row.user_id for row in residents if row.user_id]
    conditions = [AdminUser.resident_id.in_(resident_ids)]
    if user_ids:
        conditions.append(AdminUser.platform_user_id.in_(user_ids))
    admins = list((await db.execute(
        select(AdminUser).where(or_(*conditions)))).scalars().all())
    if not admins:
        return {}
    admin_ids = [row.id for row in admins]
    role_rows = (await db.execute(
        select(admin_user_roles.c.admin_user_id, Role.code, Role.name)
        .join(Role, Role.id == admin_user_roles.c.role_id)
        .where(admin_user_roles.c.admin_user_id.in_(admin_ids))
    )).all()
    roles_by_admin: dict[int, list[dict]] = {}
    for admin_id, code, name in role_rows:
        roles_by_admin.setdefault(admin_id, []).append({"code": code, "name": name})
    by_resident: dict[int, AdminUser] = {}
    by_user: dict[int, AdminUser] = {}
    for row in admins:
        if row.resident_id:
            by_resident.setdefault(row.resident_id, row)
        if row.platform_user_id:
            by_user.setdefault(row.platform_user_id, row)
    result: dict[int, dict] = {}
    for resident in residents:
        admin = by_resident.get(resident.id)
        if admin is None and resident.user_id:
            admin = by_user.get(resident.user_id)
        if admin is None:
            continue
        result[resident.id] = {
            "id": str(admin.id),
            "username": admin.username,
            "status": admin.status,
            "source": admin.source or "MANUAL",
            "mustChangePassword": bool(admin.must_change_password),
            "roles": roles_by_admin.get(admin.id, []),
        }
    return result


async def _linked_admin(db: DbSession, resident: Resident) -> AdminUser | None:
    conditions = [AdminUser.resident_id == resident.id]
    if resident.user_id:
        conditions.append(AdminUser.platform_user_id == resident.user_id)
    return await db.scalar(select(AdminUser).where(or_(*conditions)).limit(1))


async def _disable_linked_admin(db: DbSession, resident: Resident) -> bool:
    """住户资格失效时停用关联后台账号并使旧会话失效。"""
    admin = await _linked_admin(db, resident)
    if not admin or admin.status == "DISABLED":
        return False
    admin.status = "DISABLED"
    admin.session_version = int(admin.session_version or 0) + 1
    return True


async def _resident_row(db: DbSession, resident: Resident,
                        admin_account: dict | None = None) -> dict:
    community = await db.get(Community, resident.community_id)
    user = await db.get(User, resident.user_id) if resident.user_id else None
    latest_certs = await _latest_certifications(db, resident.user_id) if resident.user_id else {}
    realname_cert = latest_certs.get("REALNAME")
    owner_cert = latest_certs.get("OWNER_PROOF")
    phone_raw = decrypt_field(resident.phone_enc)
    if not phone_raw and user:
        phone_raw = decrypt_field(user.phone_enc)
    phone = mask_phone(phone_raw) if phone_raw else ""
    return {
        "id": str(resident.id),
        "communityId": str(resident.community_id),
        "communityName": community.name if community else "",
        "userId": str(resident.user_id) if resident.user_id else "",
        "name": resident.name,
        # 档案姓名来自住户认证/后台维护；nickname 为 App 展示昵称，二者分开返回便于前台核对。
        "nickname": user.nickname if user else "",
        "avatarKey": user.avatar_key if user else "",
        "email": user.email if user else "",
        "bio": user.bio if user else "",
        "creditScore": user.credit_score if user else 0,
        "creditLevel": _credit_level(user.credit_score) if user else "",
        "realnameStatus": user.realname_status if user else "UNVERIFIED",
        "realnameCert": _cert_brief(realname_cert) if realname_cert else None,
        "ownerCert": _cert_brief(owner_cert) if owner_cert else None,
        "gender": resident.gender,
        "phone": phone,
        "identity": resident.identity_type,
        "building": resident.building,
        "relationship": resident.relationship,
        "certification": resident.certification_status,
        "certificationNo": resident.certification_no,
        "level": resident.level,
        "status": resident.status,
        "joinedAt": resident.joined_at.strftime("%Y-%m-%d") if resident.joined_at else "",
        "adminAccount": admin_account,
    }


# ---------------------------------------------------------------- 业主档案（查询）

@router.get("/residents",
            dependencies=[Depends(require_permission("community:resident:view"))])
async def list_residents(
    admin: CurrentAdmin, db: DbSession,
    communityId: int | None = Query(default=None),
    identity: str | None = Query(default=None),
    certification: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    scope = await resolve_community_scope(db, admin, communityId)
    stmt = select(Resident)
    if isinstance(scope, int):
        stmt = stmt.where(Resident.community_id == scope)
    elif isinstance(scope, set):
        if not scope:
            return paginated([], page, pageSize, 0)
        stmt = stmt.where(Resident.community_id.in_(scope))
    if identity and identity != "全部人员":
        stmt = stmt.where(Resident.identity_type == identity)
    if certification:
        stmt = stmt.where(Resident.certification_status == certification)
    if keyword:
        stmt = stmt.outerjoin(User, Resident.user_id == User.id).where(or_(
            Resident.name.ilike(f"%{keyword}%"),
            User.nickname.ilike(f"%{keyword}%"),
            Resident.building.ilike(f"%{keyword}%"),
            Resident.certification_no.ilike(f"%{keyword}%"),
        ))
    rows, total = await paginate(db, stmt.order_by(Resident.id.desc()), page, pageSize)
    admin_accounts = await _admin_accounts_map(db, rows)
    return paginated(
        [await _resident_row(db, row, admin_accounts.get(row.id)) for row in rows],
        page, pageSize, total,
    )


@router.get("/residents/summary",
            dependencies=[Depends(require_permission("community:resident:view"))])
async def resident_summary(admin: CurrentAdmin, db: DbSession,
                           communityId: int | None = Query(default=None)):
    scope = await resolve_community_scope(db, admin, communityId)
    scope_conditions = []
    if isinstance(scope, int):
        scope_conditions.append(Resident.community_id == scope)
    elif isinstance(scope, set):
        if not scope:
            return ok({"total": 0, "owner": 0, "family": 0, "pending": 0})
        scope_conditions.append(Resident.community_id.in_(scope))

    async def _count(*conditions) -> int:
        return int((await db.scalar(
            select(func.count()).select_from(Resident).where(
                *scope_conditions, *conditions))) or 0)

    return ok({
        "total": await _count(),
        "owner": await _count(Resident.identity_type == "业主"),
        "family": await _count(Resident.identity_type.in_(["家属", "租户"])),
        "pending": await _count(
            Resident.certification_status.in_(["PENDING", "UNVERIFIED"])),
    })


@router.get("/residents/{resident_id}",
            dependencies=[Depends(require_permission("community:resident:view"))])
async def resident_detail(resident_id: int, admin: CurrentAdmin, db: DbSession):
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    await resolve_community_scope(db, admin, resident.community_id)
    admin_accounts = await _admin_accounts_map(db, [resident])
    return ok(await _resident_row(db, resident, admin_accounts.get(resident.id)))


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
    await resolve_community_scope(db, admin, community.id)

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
    await _apply_user_profile(db, resident, payload, only_non_empty=True)
    await _apply_user_status_fields(db, resident, payload)
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
    await resolve_community_scope(db, admin, resident.community_id)
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
        # 后台管理员可直接修正业主认证状态（不再受审核状态机迁移限制）。
        resident.certification_status = _normalize_choice(
            payload.certification, CERT_STATUS_ALIASES, "业主认证状态")
        await _sync_latest_cert_status(
            db, resident.user_id, "OWNER_PROOF", resident.certification_status)
    if "certificationNo" in fields:
        resident.certification_no = payload.certificationNo.strip()
    if "joinedAt" in fields and payload.joinedAt:
        resident.joined_at = _parse_joined_at(payload.joinedAt)

    _validate_profile_text(payload)
    await _apply_user_profile(db, resident, payload, only_non_empty=False)
    await _apply_user_status_fields(db, resident, payload)
    if resident.certification_status == "VERIFIED" and not resident.certification_no:
        resident.certification_no = f"YZ{resident.id:08d}"
    if resident.status != "ACTIVE" or resident.certification_status in ("FROZEN", "REVOKED"):
        await _disable_linked_admin(db, resident)
    await write_audit(db, request, actor=admin, action="resident.update",
                      resource_type="resident", resource_id=resident.id,
                      before=before, after=await _resident_row(db, resident))
    await db.commit()
    return ok(await _resident_row(db, resident), "人员信息已更新")


# ---------------------------------------------------------------- 删除档案（可选注销移动端账号）

CANCELLED_NICKNAME = "已注销用户"


async def _assert_account_cancel_permission(db: DbSession, admin: CurrentAdmin) -> None:
    """注销移动端账号比删除档案更敏感：需额外具备「编辑用户」权限。"""
    if admin.is_super_admin:
        return
    if "system:user:update" not in set(await get_permission_codes(db, admin)):
        raise ApiError(ERR_FORBIDDEN, "无权限注销移动端账号", 403)


async def _account_cancel_blockers(
    db: DbSession, user_id: int, exclude_resident_ids: set[int]
) -> list[str]:
    """注销前置校验：无其他社区档案、无后台身份、无交易/资金/纠纷数据。

    认证审核单、私信等历史记录保留并脱敏展示（BR-10：历史记录留存归档）。
    """
    blockers: list[str] = []
    other_resident_stmt = select(Resident.id).where(Resident.user_id == user_id)
    if exclude_resident_ids:
        other_resident_stmt = other_resident_stmt.where(
            Resident.id.notin_(exclude_resident_ids))
    if await db.scalar(other_resident_stmt.limit(1)) is not None:
        blockers.append("该账号在其他社区仍有住户档案")
    if await db.scalar(
        select(AdminUser.id).where(AdminUser.platform_user_id == user_id).limit(1)
    ) is not None:
        blockers.append("该账号仍关联后台身份")
    if await db.scalar(
        select(WalletAccount.id).where(
            WalletAccount.user_id == user_id,
            or_(
                WalletAccount.balance_cents > 0,
                WalletAccount.escrow_cents > 0,
                WalletAccount.withdrawable_cents > 0,
            ),
        ).limit(1)
    ) is not None:
        blockers.append("钱包仍有余额或托管资金")

    checks = (
        ("存在发布物品", select(Item.id).where(Item.seller_id == user_id)),
        ("存在交易订单", select(Order.id).where(
            or_(Order.buyer_id == user_id, Order.seller_id == user_id))),
        ("存在资金流水", select(PaymentTransaction.id).where(
            PaymentTransaction.user_id == user_id)),
        ("存在账本记录", select(LedgerEntry.id).where(
            LedgerEntry.account == f"USER:{user_id}")),
        ("存在提现记录", select(Withdrawal.id).where(Withdrawal.user_id == user_id)),
        ("存在纠纷记录", select(Dispute.id).where(
            or_(Dispute.initiator_id == user_id, Dispute.respondent_id == user_id))),
    )
    for label, stmt in checks:
        if await db.scalar(stmt.limit(1)) is not None:
            blockers.append(label)
    return blockers


async def _cancel_platform_account(
    db: DbSession, request: Request, admin: CurrentAdmin, user: User,
    *, reason: str,
) -> None:
    """注销并匿名化移动端账号，释放手机号供重新注册（BR-10）。

    账号不做物理删除：订单、账本、审计等历史仍通过原 user_id 关联；
    手机号密文与哈希清空后用户无法登录，原手机号可注册新账号。
    """
    before = {
        "status": user.status,
        "phone": mask_phone(decrypt_field(user.phone_enc)),
        "nickname": user.nickname,
    }
    user.status = "CANCELLED"
    user.phone_enc = ""
    user.phone_hash = hmac_index(f"cancelled:{user.id}:{uuid4().hex}")
    user.nickname = CANCELLED_NICKNAME
    user.avatar_key = ""
    user.email = ""
    user.bio = ""
    user.gender = ""
    user.realname_status = "UNVERIFIED"
    user.settings_json = {}
    user.intent_community_id = None
    user.onboarding_status = "COMPLETED"
    await write_audit(
        db, request, actor=admin, action="user.cancel",
        resource_type="user", resource_id=user.id,
        before=before,
        after={"status": "CANCELLED", "phoneFreed": True, "reason": reason},
    )


async def _cancel_account_for_residents(
    db: DbSession, request: Request, admin: CurrentAdmin, user_id: int,
    *, exclude_resident_ids: set[int], resident_names: list[str],
) -> bool:
    """按规则注销账号；返回是否真正执行。不满足条件时抛 422，阻止整次删除。"""
    user = await db.get(User, user_id)
    if user is None or user.status == "CANCELLED":
        return False
    if user.status != "ACTIVE":
        raise ApiError(ERR_BIZ_RULE, "移动端账号已冻结/停用，不能注销", 422)
    blockers = await _account_cancel_blockers(db, user.id, exclude_resident_ids)
    if blockers:
        names = "、".join(resident_names) or "该住户"
        raise ApiError(
            ERR_BIZ_RULE,
            f"无法同时注销“{names}”的移动端账号：{'；'.join(blockers)}。"
            "请仅删除档案，或先处理上述业务数据",
            422,
        )
    await _cancel_platform_account(
        db, request, admin, user, reason="删除社区人员档案时注销")
    return True


@router.delete("/residents/{resident_id}",
               dependencies=[Depends(require_permission("community:resident:update"))])
async def delete_resident(resident_id: int, request: Request,
                          admin: CurrentAdmin, db: DbSession,
                          cancelAccount: bool = Query(default=False)):
    """删除人员档案；默认保留移动端账号，可选同时注销该账号并释放手机号。

    - 默认：仅删除 residents 档案，已关联的认证审核单保留历史，仅解除档案引用；
    - cancelAccount=true：注销关联 platform_users 账号（匿名化、清空手机号），
      要求该账号无其他社区档案、无后台身份、无发布/交易/资金/纠纷数据。
    """
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    await resolve_community_scope(db, admin, resident.community_id)
    if await _linked_admin(db, resident):
        raise ApiError(
            ERR_BIZ_RULE,
            "该住户已开通后台身份，请先在「社区业主」页解除授权后再删除档案",
            422,
        )
    if cancelAccount:
        await _assert_account_cancel_permission(db, admin)

    # 审计快照必须在注销/删除前生成，保留注销前的手机号、昵称等字段。
    before = await _resident_row(db, resident)
    cancelled = False
    if cancelAccount and resident.user_id:
        cancelled = await _cancel_account_for_residents(
            db, request, admin, resident.user_id,
            exclude_resident_ids={resident.id},
            resident_names=[resident.name],
        )

    certs = (await db.execute(
        select(Certification).where(Certification.resident_id == resident.id)
    )).scalars().all()
    for cert in certs:
        cert.resident_id = None
    await db.delete(resident)
    await write_audit(db, request, actor=admin, action="resident.delete",
                      resource_type="resident", resource_id=resident_id,
                      before=before,
                      after={"accountCancelled": cancelled} if cancelled else None)
    await db.commit()
    if cancelled:
        message = "人员档案已删除，移动端账号已注销（手机号可重新注册）"
    elif cancelAccount and not resident.user_id:
        message = "人员档案已删除（该档案未绑定移动端账号）"
    elif cancelAccount:
        message = "人员档案已删除（移动端账号此前已注销）"
    else:
        message = "人员档案已删除"
    return ok({"id": str(resident_id), "accountCancelled": cancelled}, message)


class ResidentBatchDeleteIn(BaseModel):
    ids: list[int] = []
    cancelAccounts: bool = False


@router.post("/residents/batch-delete",
             dependencies=[Depends(require_permission("community:resident:update"))])
async def batch_delete_residents(payload: ResidentBatchDeleteIn, request: Request,
                                 admin: CurrentAdmin, db: DbSession):
    """批量删除人员档案；默认保留移动端账号，可选同时注销关联账号。

    勾选 cancelAccounts 时先校验全部关联账号，任一不满足条件则整批不执行。
    """
    ids = sorted({int(item) for item in payload.ids})
    if not ids:
        raise ApiError(ERR_PARAM, "请选择要删除的人员档案", 400)
    residents = list((await db.execute(
        select(Resident).where(Resident.id.in_(ids)))).scalars().all())
    if not residents:
        raise ApiError(ERR_NOT_FOUND, "人员档案不存在", 404)
    for resident in residents:
        await resolve_community_scope(db, admin, resident.community_id)
    linked = [resident.name for resident in residents if await _linked_admin(db, resident)]
    if linked:
        raise ApiError(
            ERR_BIZ_RULE,
            f"以下住户已开通后台身份，请先解除授权：{', '.join(linked)}",
            422,
        )
    if payload.cancelAccounts:
        await _assert_account_cancel_permission(db, admin)

    # 审计快照必须在注销/删除前生成，保留注销前的手机号、昵称等字段。
    before = [await _resident_row(db, resident) for resident in residents]
    resident_ids = {resident.id for resident in residents}
    residents_by_user: dict[int, list[Resident]] = {}
    for resident in residents:
        if resident.user_id:
            residents_by_user.setdefault(resident.user_id, []).append(resident)

    cancelled_user_ids: set[int] = set()
    if payload.cancelAccounts:
        # 先整体校验，避免批量中途失败导致部分账号被注销。
        for user_id, group in residents_by_user.items():
            user = await db.get(User, user_id)
            if user is None or user.status == "CANCELLED":
                continue
            if user.status != "ACTIVE":
                raise ApiError(ERR_BIZ_RULE, "移动端账号已冻结/停用，不能注销", 422)
            blockers = await _account_cancel_blockers(db, user_id, resident_ids)
            if blockers:
                names = "、".join(resident.name for resident in group)
                raise ApiError(
                    ERR_BIZ_RULE,
                    f"无法同时注销“{names}”的移动端账号：{'；'.join(blockers)}。"
                    "请仅删除档案，或先处理上述业务数据",
                    422,
                )
        for user_id, group in residents_by_user.items():
            user = await db.get(User, user_id)
            if user is None or user.status == "CANCELLED":
                continue
            await _cancel_platform_account(
                db, request, admin, user,
                reason=f"批量删除社区人员档案时注销（{group[0].name} 等）")
            cancelled_user_ids.add(user_id)

    for resident in residents:
        certs = (await db.execute(
            select(Certification).where(Certification.resident_id == resident.id)
        )).scalars().all()
        for cert in certs:
            cert.resident_id = None
        await db.delete(resident)
    audit_ids = ",".join(str(resident.id) for resident in residents)
    if len(audit_ids) > 64:
        audit_ids = f"{residents[0].id}+{len(residents) - 1}"
    after = {"cancelledAccounts": len(cancelled_user_ids)} if cancelled_user_ids else None
    await write_audit(db, request, actor=admin, action="resident.batch-delete",
                      resource_type="resident", resource_id=audit_ids,
                      before={"residents": before}, after=after)
    await db.commit()
    if cancelled_user_ids:
        message = (f"已删除 {len(residents)} 份人员档案，"
                   f"已注销 {len(cancelled_user_ids)} 个移动端账号")
    else:
        message = f"已删除 {len(residents)} 份人员档案"
    return ok({"deleted": len(residents),
               "cancelledAccounts": len(cancelled_user_ids)}, message)


# ---------------------------------------------------------------- 认证材料维护（后台直改）

MAX_CERT_MATERIAL_BYTES = 10 * 1024 * 1024
CERT_MATERIAL_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
CERT_MATERIAL_TYPES = {
    "REALNAME": CERT_MATERIAL_IMAGE_TYPES,
    "OWNER_PROOF": CERT_MATERIAL_IMAGE_TYPES | {"application/pdf"},
}
CERT_MATERIAL_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "application/pdf": ".pdf",
}
RESIDENT_CERT_LABEL = {"REALNAME": "身份认证", "OWNER_PROOF": "业主认证"}
IDENTITY_CODES = {"业主": "owner", "租户": "tenant", "家属": "family", "商务人员": "business"}


def _normalize_cert_type(raw: str) -> str:
    value = (raw or "").strip().upper()
    if value not in CERT_MATERIAL_TYPES:
        raise ApiError(ERR_PARAM, "认证类型不合法", 400)
    return value


def _detect_cert_material_type(head: bytes) -> str:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return ""


async def _get_resident_or_404(db: DbSession, resident_id: int) -> Resident:
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    return resident


async def _get_or_create_resident_cert(db: DbSession, resident: Resident,
                                       cert_type: str) -> Certification:
    """取最近一张认证单；没有时补建一张，便于后台直接维护历史人员的证件材料。"""
    if not resident.user_id:
        raise ApiError(ERR_PARAM, "该人员档案未绑定账号，无法维护认证材料", 400)
    cert = await _latest_cert(db, resident.user_id, cert_type)
    if cert is not None:
        return cert
    user = await db.get(User, resident.user_id)
    if user is None:
        raise ApiError(ERR_PARAM, "关联账号不存在，无法维护认证材料", 400)
    status = (user.realname_status if cert_type == "REALNAME"
              else resident.certification_status) or "UNVERIFIED"
    cert = Certification(
        user_id=resident.user_id,
        resident_id=resident.id,
        community_id=resident.community_id if cert_type == "OWNER_PROOF" else None,
        type=cert_type,
        identity=IDENTITY_CODES.get(resident.identity_type, "owner"),
        materials=[],
        status=status,
        submitted_at=utcnow(),
    )
    db.add(cert)
    await db.flush()
    return cert


@router.get("/residents/{resident_id}/certifications/{cert_type}/materials",
            dependencies=[ResidentUpdatePerm])
async def resident_cert_materials(resident_id: int, cert_type: str,
                                  admin: CurrentAdmin, db: DbSession):
    resident = await _get_resident_or_404(db, resident_id)
    await resolve_community_scope(db, admin, resident.community_id)
    cert_type = _normalize_cert_type(cert_type)
    cert = await _latest_cert(db, resident.user_id, cert_type) if resident.user_id else None
    if cert is None:
        return ok({
            "id": "", "type": cert_type, "typeLabel": RESIDENT_CERT_LABEL[cert_type],
            "status": "", "submittedAt": 0, "materials": [],
        })
    return ok(await _cert_detail(db, cert))


@router.post("/residents/{resident_id}/certifications/{cert_type}/materials",
             dependencies=[ResidentUpdatePerm])
async def upload_resident_cert_material(resident_id: int, cert_type: str, request: Request,
                                        admin: CurrentAdmin, db: DbSession,
                                        file: Annotated[UploadFile, File()]):
    """后台直传认证照片/证件（私有桶）；自动补建认证单并记审计。"""
    resident = await _get_resident_or_404(db, resident_id)
    await resolve_community_scope(db, admin, resident.community_id)
    cert_type = _normalize_cert_type(cert_type)
    cert = await _get_or_create_resident_cert(db, resident, cert_type)

    content = await file.read()
    if not content:
        raise ApiError(ERR_PARAM, "上传文件为空", 400)
    if len(content) > MAX_CERT_MATERIAL_BYTES:
        raise ApiError(ERR_FILE_TOO_LARGE, "单个文件不能超过 10MB", 413)
    allowed = CERT_MATERIAL_TYPES[cert_type]
    detected = _detect_cert_material_type(content[:16])
    if detected not in allowed:
        message = ("仅支持 JPG / PNG / WebP 图片" if cert_type == "REALNAME"
                   else "仅支持 JPG / PNG / WebP 图片或 PDF 文件")
        raise ApiError(ERR_PARAM, message, 400)

    client = get_minio()
    if client is None:
        raise ApiError(ERR_DEPENDENCY, "对象存储未配置，暂无法上传材料", 503)
    bucket = settings.minio_bucket_private
    object_key = f"certifications/admin/{cert.id}/{uuid4().hex}{CERT_MATERIAL_EXT[detected]}"
    try:
        if hasattr(client, "bucket_exists"):
            exists = await run_in_threadpool(client.bucket_exists, bucket)
            if not exists:
                await run_in_threadpool(client.make_bucket, bucket)
        await run_in_threadpool(
            client.put_object, bucket, object_key,
            io.BytesIO(content), len(content), content_type=detected,
        )
    except Exception as exc:  # 对象存储异常统一转依赖不可用
        logger.warning("认证材料上传失败：%s", exc)
        raise ApiError(ERR_DEPENDENCY, "认证材料上传失败，请稍后重试", 503) from exc

    before = list(cert.materials or [])
    cert.materials = [*before, object_key]
    await write_audit(db, request, actor=admin, action="certification.material.upload",
                      resource_type="certification", resource_id=cert.id,
                      before={"materials": before}, after={"materials": cert.materials})
    await db.commit()
    return ok(await _cert_detail(db, cert), "认证材料已上传")


@router.delete("/residents/{resident_id}/certifications/{cert_type}/materials",
               dependencies=[ResidentUpdatePerm])
async def delete_resident_cert_material(resident_id: int, cert_type: str, request: Request,
                                        admin: CurrentAdmin, db: DbSession,
                                        objectKey: str = Query(...)):
    """从认证单移除材料引用（对象保留在私有桶供审计追溯）。"""
    resident = await _get_resident_or_404(db, resident_id)
    await resolve_community_scope(db, admin, resident.community_id)
    cert_type = _normalize_cert_type(cert_type)
    cert = await _latest_cert(db, resident.user_id, cert_type) if resident.user_id else None
    if cert is None:
        raise ApiError(ERR_NOT_FOUND, "该人员暂无认证材料", 404)
    before = list(cert.materials or [])
    if objectKey not in before:
        raise ApiError(ERR_NOT_FOUND, "认证材料不存在", 404)
    cert.materials = [key for key in before if key != objectKey]
    await write_audit(db, request, actor=admin, action="certification.material.delete",
                      resource_type="certification", resource_id=cert.id,
                      before={"materials": before}, after={"materials": cert.materials})
    await db.commit()
    return ok(await _cert_detail(db, cert), "认证材料已删除")


# ---------------------------------------------------------------- 认证审核队列（W02）

def _cert_community_conditions(scope: int | None | set[int]) -> list:
    """认证审核单的社区过滤条件。

    住户认证（OWNER_PROOF）直接按 ``community_id`` 归属；实名认证（REALNAME）
    不绑定小区，按申请人是否在该社区存在住户档案归属。这样后台选择小区后，
    住户认证按目标小区收窄，同时不会把该小区住户的实名认证队列整体过滤为空。
    调用方需自行处理空集合（返回空列表），本函数对空集合不生成恒假条件。
    """
    if scope is None:
        return []
    community_ids = [scope] if isinstance(scope, int) else list(scope)
    if not community_ids:
        return []
    resident_user_ids = select(Resident.user_id).where(
        Resident.community_id.in_(community_ids),
        Resident.user_id.is_not(None),
    )
    return [or_(
        Certification.community_id.in_(community_ids),
        and_(Certification.type == "REALNAME",
             Certification.user_id.in_(resident_user_ids)),
    )]


@router.get("/certifications", dependencies=[AuditPerm])
async def list_certifications(
    admin: CurrentAdmin, db: DbSession,
    type: str | None = Query(default=None),
    status: str | None = Query(default="PENDING"),
    communityId: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    scope = await resolve_community_scope(db, admin, communityId)
    if isinstance(scope, set) and not scope:
        return paginated([], page, pageSize, 0)
    stmt = select(Certification).where(*_cert_community_conditions(scope))
    if type:
        stmt = stmt.where(Certification.type == type)
    if status:
        stmt = stmt.where(Certification.status == status)
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
    scope = await resolve_community_scope(db, admin, communityId)
    if isinstance(scope, set) and not scope:
        return ok({
            "pending": 0, "pendingRealname": 0, "pendingOwner": 0,
            "supplement": 0, "todayReviewed": 0, "oldestPendingAt": 0,
        })
    base_conditions = _cert_community_conditions(scope)

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
    await _assert_cert_scope(db, admin, cert)
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


async def _assert_cert_scope(db: DbSession, admin: AdminUser, cert: Certification) -> None:
    if cert.community_id is not None:
        await resolve_community_scope(db, admin, cert.community_id)
        return
    allowed = await allowed_community_ids(db, admin)
    if allowed is None:
        return
    # 实名认证不绑定小区：申请人在允许社区内有住户档案时，社区管理员可查看/审核。
    if cert.type == "REALNAME" and cert.user_id and allowed:
        in_scope = await db.scalar(
            select(Resident.id).where(
                Resident.user_id == cert.user_id,
                Resident.community_id.in_(list(allowed)),
            ).limit(1)
        )
        if in_scope is not None:
            return
    raise ApiError(ERR_DATA_SCOPE, "数据范围越界", 403)


@router.post("/certifications/{certification_id}/approve",
             dependencies=[AuditPerm])
async def approve_certification(
    certification_id: int, request: Request, admin: CurrentAdmin, db: DbSession,
):
    """W02-02 通过：业主证明通过后账号与小区强绑定（BR-02）；实名通过更新实名状态。
    审核动作写审计（W01-03），并向申请人发送站内通知（M01-04）。"""
    cert = await _get_cert_or_404(db, certification_id)
    await _assert_cert_scope(db, admin, cert)
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
        # 注册时预建的未认证档案以认证单申报的身份为准（业主/租户/家属）。
        resident.identity_type = IDENTITY_MAP.get(cert.identity, resident.identity_type or "业主")
        if not resident.name and user:
            resident.name = user.nickname
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
    await _assert_cert_scope(db, admin, cert)
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
    await _assert_cert_scope(db, admin, cert)
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
    await _assert_cert_scope(db, admin, cert)
    community_id = payload.get("communityId")
    community = await db.get(Community, int(community_id)) if community_id else None
    if not community:
        raise ApiError(ERR_PARAM, "目标小区不存在", 400)
    await resolve_community_scope(db, admin, community.id)
    cert.community_id = community.id
    await db.commit()
    return ok(await _cert_row(db, cert), "认定小区已纠正")


@router.get("/verifications", dependencies=[AuditPerm])
async def list_verifications(admin: CurrentAdmin, db: DbSession):
    scope = await resolve_community_scope(db, admin, None)
    if isinstance(scope, set) and not scope:
        return ok([])
    stmt = select(Certification).where(
        Certification.status == "PENDING", *_cert_community_conditions(scope))
    rows, _ = await paginate(db, stmt.order_by(Certification.id), 1, 50)
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
    await resolve_community_scope(db, admin, resident.community_id)
    if resident.certification_status == "FROZEN":
        raise ApiError(ERR_BIZ_RULE, "该人员已处于冻结状态", 422)

    resident.certification_status = certification_sm.fire(
        resident.certification_status, E.CertificationStatus.FROZEN)
    cert = await _latest_owner_cert(db, resident)
    if cert and cert.status == "VERIFIED":
        cert.status = E.CertificationStatus.FROZEN
    await _disable_linked_admin(db, resident)

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
    await resolve_community_scope(db, admin, resident.community_id)
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
    await resolve_community_scope(db, admin, resident.community_id)
    resident.certification_status = certification_sm.fire(
        resident.certification_status, E.CertificationStatus.REVOKED)
    resident.certification_no = ""
    cert = await _latest_owner_cert(db, resident)
    if cert and cert.status in ("VERIFIED", "FROZEN"):
        cert.status = E.CertificationStatus.REVOKED
    await _disable_linked_admin(db, resident)
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


# ---------------------------------------------------------------- 住户后台身份授权

class ResidentAdminGrantIn(BaseModel):
    roleIds: list[int] = []
    username: str = ""
    reason: str = ""


async def _admin_account_brief(db: DbSession, admin: AdminUser) -> dict:
    roles = (await db.execute(
        select(Role.id, Role.code, Role.name)
        .join(admin_user_roles, admin_user_roles.c.role_id == Role.id)
        .where(admin_user_roles.c.admin_user_id == admin.id)
    )).all()
    communities = (await db.execute(
        select(Community.id, Community.name)
        .join(admin_user_communities,
              admin_user_communities.c.community_id == Community.id)
        .where(admin_user_communities.c.admin_user_id == admin.id)
    )).all()
    return {
        "id": str(admin.id),
        "username": admin.username,
        "realName": admin.real_name,
        "status": admin.status,
        "source": admin.source or "MANUAL",
        "mustChangePassword": bool(admin.must_change_password),
        "roles": [{"id": str(rid), "code": code, "name": name}
                  for rid, code, name in roles],
        "communities": [{"id": str(cid), "name": name} for cid, name in communities],
        "lastLoginAt": int(admin.last_login_at.timestamp() * 1000) if admin.last_login_at else 0,
    }


async def _resident_grant_state(db: DbSession, resident: Resident) -> tuple[bool, str, AdminUser | None]:
    if resident.status != "ACTIVE":
        return False, "住户已停用或已离开，不能授予后台权限", None
    if resident.certification_status != "VERIFIED":
        return False, "住户认证未通过，不能授予后台权限", None
    user = await db.get(PlatformUser, resident.user_id) if resident.user_id else None
    if user and user.status != "ACTIVE":
        return False, "关联的移动端账号不可用", None
    if not user and not (resident.phone_enc or resident.phone_hash):
        return False, "住户缺少手机号，无法创建移动端账号", None
    admin = await _linked_admin(db, resident)
    return True, "", admin


@router.get("/resident-admin-roles",
            dependencies=[Depends(require_permission("community:resident:admin-grant"))])
async def resident_admin_roles(admin: CurrentAdmin, db: DbSession):
    """可授予住户的角色白名单：启用 + OWN_COMMUNITY + 显式可授予。"""
    rows = list((await db.execute(
        select(Role).where(
            Role.status == "ACTIVE",
            Role.assignable_to_resident.is_(True),
            Role.data_scope == "OWN_COMMUNITY",
            Role.code != "super_admin",
        ).order_by(Role.id)
    )).scalars().all())
    return ok([
        {"id": str(row.id), "code": row.code, "name": row.name,
         "description": row.description, "dataScope": row.data_scope}
        for row in rows
    ])


@router.get(
    "/residents/{resident_id}/admin-account",
    dependencies=[Depends(require_any_permission(
        "community:resident:view", "community:resident:admin-grant"))],
)
async def resident_admin_account(resident_id: int, admin: CurrentAdmin, db: DbSession):
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    await resolve_community_scope(db, admin, resident.community_id)
    eligible, reason, admin_row = await _resident_grant_state(db, resident)
    return ok({
        "residentId": str(resident.id),
        "userId": str(resident.user_id) if resident.user_id else "",
        "eligible": eligible,
        "eligibleReason": reason,
        "account": await _admin_account_brief(db, admin_row) if admin_row else None,
    })


@router.post(
    "/residents/{resident_id}/admin-account",
    dependencies=[Depends(require_permission("community:resident:admin-grant"))],
)
async def grant_resident_admin(resident_id: int, payload: ResidentAdminGrantIn,
                               request: Request, admin: CurrentAdmin, db: DbSession):
    """住户授权/调整后台角色；初始密码仅在首次授权时返回一次。"""
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    await resolve_community_scope(db, admin, resident.community_id)
    eligible, reason, existing = await _resident_grant_state(db, resident)
    if not eligible:
        raise ApiError(ERR_BIZ_RULE, reason, 422)
    role_ids = sorted({int(item) for item in payload.roleIds})
    if not role_ids:
        raise ApiError(ERR_PARAM, "请选择要授予的角色", 400)
    roles = list((await db.execute(
        select(Role).where(Role.id.in_(role_ids)))).scalars().all())
    if len(roles) != len(role_ids):
        raise ApiError(ERR_PARAM, "角色不存在", 400)
    for role in roles:
        if (role.status != "ACTIVE" or not role.assignable_to_resident
                or role.data_scope != "OWN_COMMUNITY" or role.code == "super_admin"):
            raise ApiError(ERR_BIZ_RULE, f"角色「{role.name}」不允许授予社区住户", 422)

    idem = await guard_idempotency(db, request, {
        "residentId": resident_id, "roleIds": role_ids,
        "username": payload.username.strip(),
    })
    if idem and idem.status == "COMPLETED":
        cached = dict((idem.response_json or {}).get("data") or {})
        cached["initialPassword"] = None
        cached["replay"] = True
        return ok(cached, "后台权限已开通")

    user, user_created = await ensure_platform_user_for_resident(db, resident)
    if not user or user.status != "ACTIVE":
        raise ApiError(ERR_BIZ_RULE, "关联的移动端账号不可用", 422)
    # 住户原先没有 user_id、但按手机号匹配到平台账号时，需重新检查后台身份。
    existing = await db.scalar(
        select(AdminUser).where(AdminUser.platform_user_id == user.id))

    initial_password: str | None = None
    if existing:
        if existing.source != "RESIDENT":
            raise ApiError(
                ERR_CONFLICT,
                "该住户的移动端账号已绑定手工后台账号，请到「用户管理」调整",
                409,
            )
        admin_row = existing
        adjusted = True
    else:
        username = payload.username.strip() or await next_admin_username(db, user.id)
        if len(username) < 3:
            raise ApiError(ERR_PARAM, "登录账号至少 3 位", 400)
        if await db.scalar(select(AdminUser.id).where(AdminUser.username == username)):
            raise ApiError(ERR_CONFLICT, "登录账号已存在", 409)
        initial_password = generate_initial_password()
        admin_row = AdminUser(
            username=username,
            password_hash=hash_password(initial_password),
            real_name=resident.name,
            phone_enc="",
            email="",
            avatar_text=resident.name[:1],
            source="RESIDENT",
            resident_id=resident.id,
            platform_user_id=user.id,
            status="ACTIVE",
            must_change_password=True,
        )
        db.add(admin_row)
        await db.flush()
        adjusted = False

    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(admin_user_roles).where(
        admin_user_roles.c.admin_user_id == admin_row.id))
    from sqlalchemy import insert as sa_insert
    await db.execute(sa_insert(admin_user_roles), [
        {"admin_user_id": admin_row.id, "role_id": role_id} for role_id in role_ids
    ])
    await db.execute(sa_delete(admin_user_communities).where(
        admin_user_communities.c.admin_user_id == admin_row.id))
    await db.execute(sa_insert(admin_user_communities), [
        {"admin_user_id": admin_row.id, "community_id": resident.community_id}
    ])
    admin_row.resident_id = resident.id
    admin_row.platform_user_id = user.id
    admin_row.status = "ACTIVE"
    admin_row.session_version = int(admin_row.session_version or 0) + (0 if initial_password else 1)

    account = await _admin_account_brief(db, admin_row)
    data = {
        "admin": account,
        "initialPassword": initial_password,
        "replay": False,
        "adjusted": adjusted,
        "linkedUserCreated": user_created,
    }
    await write_audit(db, request, actor=admin, action="resident.admin.grant",
                      resource_type="resident", resource_id=resident.id,
                      before=None,
                      after={"residentId": resident.id, "userId": user.id,
                             "adminId": admin_row.id, "roleIds": role_ids,
                             "communityIds": [resident.community_id],
                             "source": "RESIDENT"})
    await write_outbox(db, event_type="ResidentAdminGranted",
                       aggregate_type="resident", aggregate_id=resident.id,
                       payload={"residentId": resident.id, "userId": user.id,
                                "adminId": admin_row.id, "roleIds": role_ids})
    safe_data = {**data, "initialPassword": None}
    await complete_idempotency(db, idem, safe_data)
    await db.commit()
    return ok(data, "后台权限已开通" if not adjusted else "后台角色已调整")


@router.post(
    "/residents/{resident_id}/admin-account/revoke",
    dependencies=[Depends(require_permission("community:resident:admin-revoke"))],
)
async def revoke_resident_admin(resident_id: int, request: Request,
                                admin: CurrentAdmin, db: DbSession):
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    await resolve_community_scope(db, admin, resident.community_id)
    admin_row = await _linked_admin(db, resident)
    if not admin_row:
        raise ApiError(ERR_NOT_FOUND, "该住户尚未开通后台身份", 404)
    if admin_row.source != "RESIDENT":
        raise ApiError(
            ERR_BIZ_RULE,
            "该住户关联的是手工后台账号，请到「用户管理」处理",
            422,
        )
    idem = await guard_idempotency(db, request, {"residentId": resident_id})
    if idem and idem.status == "COMPLETED":
        cached = dict((idem.response_json or {}).get("data") or {})
        cached["replay"] = True
        return ok(cached, "后台权限已解除")
    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(admin_user_roles).where(
        admin_user_roles.c.admin_user_id == admin_row.id))
    await db.execute(sa_delete(admin_user_communities).where(
        admin_user_communities.c.admin_user_id == admin_row.id))
    admin_row.status = "DISABLED"
    admin_row.must_change_password = True
    admin_row.session_version = int(admin_row.session_version or 0) + 1
    data = {"adminId": str(admin_row.id), "status": "DISABLED", "replay": False}
    await write_audit(db, request, actor=admin, action="resident.admin.revoke",
                      resource_type="resident", resource_id=resident.id,
                      before={"adminId": admin_row.id, "status": "ACTIVE"},
                      after={"adminId": admin_row.id, "status": "DISABLED"})
    await write_outbox(db, event_type="ResidentAdminRevoked",
                       aggregate_type="resident", aggregate_id=resident.id,
                       payload={"residentId": resident.id, "adminId": admin_row.id})
    await complete_idempotency(db, idem, data)
    await db.commit()
    return ok(data, "后台权限已解除")


@router.post(
    "/residents/{resident_id}/admin-account/reset-password",
    dependencies=[Depends(require_permission("community:resident:admin-grant"))],
)
async def reset_resident_admin_password(resident_id: int, request: Request,
                                        admin: CurrentAdmin, db: DbSession):
    resident = await db.get(Resident, resident_id)
    if not resident:
        raise ApiError(ERR_NOT_FOUND, "人员不存在", 404)
    await resolve_community_scope(db, admin, resident.community_id)
    admin_row = await _linked_admin(db, resident)
    if not admin_row:
        raise ApiError(ERR_NOT_FOUND, "该住户尚未开通后台身份", 404)
    if admin_row.source != "RESIDENT":
        raise ApiError(ERR_BIZ_RULE, "请到「用户管理」重置该账号密码", 422)
    idem = await guard_idempotency(db, request, {"residentId": resident_id})
    if idem and idem.status == "COMPLETED":
        cached = dict((idem.response_json or {}).get("data") or {})
        cached["initialPassword"] = None
        cached["replay"] = True
        return ok(cached, "初始密码已重置")
    new_password = generate_initial_password()
    admin_row.password_hash = hash_password(new_password)
    admin_row.must_change_password = True
    admin_row.failed_attempts = 0
    admin_row.locked_until = None
    admin_row.session_version = int(admin_row.session_version or 0) + 1
    data = {
        "adminId": str(admin_row.id),
        "username": admin_row.username,
        "initialPassword": new_password,
        "replay": False,
    }
    await write_audit(db, request, actor=admin, action="resident.admin.reset-password",
                      resource_type="resident", resource_id=resident.id,
                      before=None, after={"adminId": admin_row.id, "reset": True})
    await complete_idempotency(db, idem, {**data, "initialPassword": None})
    await db.commit()
    return ok(data, "初始密码已重置，请一次性告知住户")


@router.get("/residents/{resident_id}/penalties",
            dependencies=[Depends(require_permission("community:resident:view"))])
async def resident_penalties(resident_id: int, admin: CurrentAdmin, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("GET /residents/{id}/penalties（W07 用户处置，Phase 2）")
