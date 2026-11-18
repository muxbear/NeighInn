"""管理员账号与角色权限管理（W01-02）。
参数配置/字典/审计见 system.py；资源页面管理（sys_pages）Phase 2 后续。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import ERR_BIZ_RULE, ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.core.security import decrypt_field, encrypt_field, hash_password, mask_phone
from src.db.models import (
    AdminUser,
    Community,
    Permission,
    Role,
    admin_user_communities,
    admin_user_roles,
    role_permissions,
)
from src.db.models.common import ensure_utc, utcnow

router = APIRouter(tags=["admin:system:accounts"])

RolePerm = Depends(require_permission("system:role:view"))
RoleManagePerm = Depends(require_permission("system:role:grant"))
AdminUserManagePerm = Depends(require_permission("system:admin-user:update"))


# ---------------------------------------------------------------- 角色（W01-02）

async def _role_row(db: AsyncSession, role: Role) -> dict:
    members = int((await db.scalar(
        select(func.count()).select_from(admin_user_roles)
        .where(admin_user_roles.c.role_id == role.id))) or 0)
    return {
        "id": str(role.id), "name": role.name, "code": role.code,
        "description": role.description, "builtin": role.is_builtin,
        "dataScope": role.data_scope, "status": role.status,
        "members": members, "version": role.version,
    }


@router.get("/roles", dependencies=[RolePerm])
async def list_roles(admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(select(Role).order_by(Role.id))).scalars().all())
    return ok([await _role_row(db, row) for row in rows])


class RoleIn(BaseModel):
    name: str
    code: str | None = None
    description: str = ""
    dataScope: str = "OWN_COMMUNITY"


@router.post("/roles", dependencies=[Depends(require_permission("system:role:create"))])
async def create_role(payload: RoleIn, request: Request, admin: CurrentAdmin, db: DbSession):
    code = payload.code or payload.name.strip().lower().replace(" ", "_")
    if await db.scalar(select(Role.id).where(Role.code == code)):
        raise ApiError(40901, "角色编码已存在", 409)
    role = Role(name=payload.name.strip(), code=code, description=payload.description,
                data_scope=payload.dataScope)
    db.add(role)
    await db.flush()
    await write_audit(db, request, actor=admin, action="role.create",
                      resource_type="role", resource_id=role.id,
                      before=None, after={"code": code})
    await db.commit()
    return ok(await _role_row(db, role), "角色已创建")


@router.put("/roles/{role_id}", dependencies=[Depends(require_permission("system:role:update"))])
async def update_role(role_id: int, payload: RoleIn, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    role = await db.get(Role, role_id)
    if not role:
        raise ApiError(ERR_NOT_FOUND, "角色不存在", 404)
    if role.code == "super_admin" and payload.dataScope != "ALL":
        raise ApiError(ERR_BIZ_RULE, "超级管理员数据范围不可修改", 422)
    before = {"name": role.name, "description": role.description, "dataScope": role.data_scope}
    role.name = payload.name.strip() or role.name
    role.description = payload.description
    role.data_scope = payload.dataScope
    role.version += 1
    await write_audit(db, request, actor=admin, action="role.update",
                      resource_type="role", resource_id=role.id,
                      before=before, after=_role_snapshot(role))
    await db.commit()
    return ok(await _role_row(db, role), "角色已更新")


def _role_snapshot(role: Role) -> dict:
    return {"name": role.name, "description": role.description, "dataScope": role.data_scope}


@router.delete("/roles/{role_id}", dependencies=[Depends(require_permission("system:role:delete"))])
async def delete_role(role_id: int, request: Request, admin: CurrentAdmin, db: DbSession):
    """内置角色不可删除；删除后历史授权记录保留可追溯（详设 6.3 注）。"""
    role = await db.get(Role, role_id)
    if not role:
        raise ApiError(ERR_NOT_FOUND, "角色不存在", 404)
    if role.is_builtin:
        raise ApiError(ERR_BIZ_RULE, "内置角色不可删除", 422)
    members = await db.scalar(
        select(func.count()).select_from(admin_user_roles)
        .where(admin_user_roles.c.role_id == role_id))
    if members:
        raise ApiError(ERR_BIZ_RULE, "角色仍有成员，请先移除成员", 422)
    await db.execute(delete(role_permissions).where(role_permissions.c.role_id == role_id))
    await db.delete(role)
    await write_audit(db, request, actor=admin, action="role.delete",
                      resource_type="role", resource_id=role_id,
                      before=_role_snapshot(role), after=None)
    await db.commit()
    return ok(None, "角色已删除")


@router.get("/roles/{role_id}/permissions", dependencies=[RolePerm])
async def role_permissions_list(role_id: int, admin: CurrentAdmin, db: DbSession):
    role = await db.get(Role, role_id)
    if not role:
        raise ApiError(ERR_NOT_FOUND, "角色不存在", 404)
    rows = await db.execute(
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == role_id))
    return ok({"role": await _role_row(db, role), "permissions": list(rows.scalars().all())})


class GrantIn(BaseModel):
    permissions: list[str]


@router.put("/roles/{role_id}/permissions", dependencies=[RoleManagePerm])
async def update_role_permissions(role_id: int, payload: GrantIn,
                                  request: Request, admin: CurrentAdmin, db: DbSession):
    """事务内更新 + 审计；超级管理员权限不可修改（详设 4.7.9）。"""
    role = await db.get(Role, role_id)
    if not role:
        raise ApiError(ERR_NOT_FOUND, "角色不存在", 404)
    if role.code == "super_admin":
        raise ApiError(ERR_BIZ_RULE, "超级管理员权限不可修改", 422)
    codes = sorted(set(payload.permissions))
    known = set((await db.execute(
        select(Permission.code).where(Permission.code.in_(codes)))).scalars().all())
    unknown = sorted(set(codes) - known)
    if unknown:
        raise ApiError(ERR_PARAM, f"权限码不存在：{', '.join(unknown[:3])}", 400)
    before = list((await db.execute(
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == role_id))).scalars().all())
    await db.execute(delete(role_permissions).where(role_permissions.c.role_id == role_id))
    if codes:
        permission_ids = {code: pid for code, pid in (await db.execute(
            select(Permission.code, Permission.id)
            .where(Permission.code.in_(codes)))).all()}
        from sqlalchemy import insert

        await db.execute(insert(role_permissions), [
            {"role_id": role_id, "permission_id": permission_ids[code]} for code in codes])
    role.version += 1
    await write_audit(db, request, actor=admin, action="role.grant",
                      resource_type="role", resource_id=role_id,
                      before={"permissions": before}, after={"permissions": codes})
    await db.commit()
    return ok({"permissions": codes, "version": role.version}, "权限配置已保存")


@router.get("/permissions/tree", dependencies=[RolePerm])
async def permission_tree(admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(Permission).where(Permission.status == "ACTIVE")
        .order_by(Permission.sort))).scalars().all())
    groups: dict[str, list[dict]] = {}
    for row in rows:
        group = row.code.split(":")[0] if ":" in row.code else "其他"
        groups.setdefault(group, []).append({
            "code": row.code, "name": row.name, "type": row.type, "route": row.route})
    return ok([{"label": label, "items": items} for label, items in groups.items()])


# ---------------------------------------------------------------- 管理员账号

class AdminUserIn(BaseModel):
    username: str
    password: str = ""
    realName: str
    phone: str = ""
    email: str = ""
    roleIds: list[int] = []
    communityIds: list[int] = []
    status: str = "ACTIVE"


async def _admin_row(db: AsyncSession, row: AdminUser) -> dict:
    roles = (await db.execute(
        select(Role.id, Role.code, Role.name)
        .join(admin_user_roles, admin_user_roles.c.role_id == Role.id)
        .where(admin_user_roles.c.admin_user_id == row.id))).all()
    community_ids = list((await db.execute(
        select(admin_user_communities.c.community_id)
        .where(admin_user_communities.c.admin_user_id == row.id))).scalars().all())
    communities: list[dict] = []
    if community_ids:
        community_rows = (await db.execute(
            select(Community.id, Community.name)
            .where(Community.id.in_(community_ids))
            .order_by(Community.id))).all()
        by_id = {cid: name for cid, name in community_rows}
        communities = [{"id": str(cid), "name": by_id.get(cid, "")}
                       for cid in community_ids if cid in by_id]
    locked_until = ensure_utc(row.locked_until)
    phone = decrypt_field(row.phone_enc) if row.phone_enc else ""
    return {
        "id": str(row.id), "username": row.username, "realName": row.real_name,
        "phone": mask_phone(phone) if phone else "",
        "email": row.email, "status": row.status,
        "isSuperAdmin": row.is_super_admin,
        "twoFactorEnabled": row.two_factor_enabled,
        "roles": [{"id": str(rid), "code": code, "name": name}
                  for rid, code, name in roles],
        "roleIds": [str(rid) for rid, _, _ in roles],
        "communities": communities,
        "communityIds": [str(cid) for cid in community_ids],
        "locked": bool(locked_until and locked_until > utcnow()),
        "lockedUntil": int(locked_until.timestamp() * 1000) if locked_until else 0,
        "failedAttempts": int(row.failed_attempts or 0),
        "lastLoginAt": int(row.last_login_at.timestamp() * 1000) if row.last_login_at else 0,
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
    }


def _validate_admin_password(password: str) -> None:
    """后台账号密码策略：≥12 位，且大小写字母/数字/符号至少三类。"""
    if len(password) < 12:
        raise ApiError(ERR_PARAM, "密码最短 12 位（三类字符）", 400)
    kinds = sum(bool(re.search(pattern, password))
                for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if kinds < 3:
        raise ApiError(ERR_PARAM, "密码需包含大小写字母、数字、符号中的至少三类", 400)


async def _admin_count(db: AsyncSession, stmt) -> int:
    return int((await db.scalar(
        select(func.count()).select_from(stmt.subquery()))) or 0)


@router.get("/admin-users", dependencies=[Depends(require_permission("system:admin-user:view"))])
async def list_admin_users(admin: CurrentAdmin, db: DbSession,
                           keyword: str | None = Query(default=None),
                           status: str | None = Query(default=None),
                           page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(AdminUser)
    if keyword:
        stmt = stmt.where(or_(AdminUser.username.ilike(f"%{keyword}%"),
                              AdminUser.real_name.ilike(f"%{keyword}%")))
    if status in ("ACTIVE", "DISABLED"):
        stmt = stmt.where(AdminUser.status == status)
    rows, total = await paginate(db, stmt.order_by(AdminUser.id), page, pageSize)
    now = utcnow()
    stats = {
        "total": total,
        "active": await _admin_count(db, stmt.where(AdminUser.status == "ACTIVE")),
        "disabled": await _admin_count(db, stmt.where(AdminUser.status == "DISABLED")),
        "locked": await _admin_count(db, stmt.where(
            AdminUser.locked_until.is_not(None), AdminUser.locked_until > now)),
    }
    payload = paginated([await _admin_row(db, row) for row in rows], page, pageSize, total)
    payload["data"]["stats"] = stats
    return payload


@router.post("/admin-users", dependencies=[Depends(require_permission("system:admin-user:create"))])
async def create_admin_user(payload: AdminUserIn, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    if len(payload.username.strip()) < 3:
        raise ApiError(ERR_PARAM, "用户名至少 3 位", 400)
    _validate_admin_password(payload.password)
    if await db.scalar(select(AdminUser).where(AdminUser.username == payload.username.strip())):
        raise ApiError(40901, "用户名已存在", 409)
    real_name = payload.realName.strip()
    row = AdminUser(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        real_name=real_name,
        phone_enc=encrypt_field(payload.phone.strip()),
        email=payload.email,
        avatar_text=real_name[:1],
        status="ACTIVE" if payload.status not in ("ACTIVE", "DISABLED") else payload.status,
    )
    db.add(row)
    await db.flush()
    await _assign_roles_and_communities(db, row, payload.roleIds, payload.communityIds)
    await write_audit(db, request, actor=admin, action="admin-user.create",
                      resource_type="admin_user", resource_id=row.id,
                      before=None, after={"username": row.username,
                                          "roleIds": payload.roleIds})
    await db.commit()
    return ok(await _admin_row(db, row), "管理员已创建")


async def _assign_roles_and_communities(db: AsyncSession, row: AdminUser,
                                        role_ids: list[int], community_ids: list[int]) -> None:
    from sqlalchemy import insert

    await db.execute(delete(admin_user_roles).where(admin_user_roles.c.admin_user_id == row.id))
    await db.execute(delete(admin_user_communities)
                     .where(admin_user_communities.c.admin_user_id == row.id))
    if role_ids:
        await db.execute(insert(admin_user_roles), [
            {"admin_user_id": row.id, "role_id": rid} for rid in role_ids])
    if community_ids:
        await db.execute(insert(admin_user_communities), [
            {"admin_user_id": row.id, "community_id": cid} for cid in community_ids])


@router.put("/admin-users/{admin_id}", dependencies=[AdminUserManagePerm])
async def update_admin_user(admin_id: int, payload: AdminUserIn,
                            request: Request, admin: CurrentAdmin, db: DbSession):
    row = await db.get(AdminUser, admin_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "管理员不存在", 404)
    if row.is_super_admin:
        raise ApiError(ERR_BIZ_RULE, "超级管理员仅可自助修改，不支持他人编辑", 422)
    before = {"realName": row.real_name, "email": row.email, "status": row.status}
    row.real_name = payload.realName.strip() or row.real_name
    row.email = payload.email
    # 列表返回脱敏手机号；留空表示不修改，避免编辑时误清空。
    if payload.phone.strip():
        row.phone_enc = encrypt_field(payload.phone.strip())
    row.avatar_text = row.real_name[:1]
    if payload.status in ("ACTIVE", "DISABLED"):
        row.status = payload.status
    await _assign_roles_and_communities(db, row, payload.roleIds, payload.communityIds)
    await write_audit(db, request, actor=admin, action="admin-user.update",
                      resource_type="admin_user", resource_id=row.id,
                      before=before,
                      after={"realName": row.real_name, "roleIds": payload.roleIds,
                             "communityIds": payload.communityIds,
                             "status": row.status})
    await db.commit()
    return ok(await _admin_row(db, row), "管理员已更新")


@router.patch("/admin-users/{admin_id}/status", dependencies=[AdminUserManagePerm])
async def toggle_admin_user(admin_id: int, payload: dict, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    """超级管理员不可停用；系统至少保留 1 个可用超管（详设 8.1.2）。"""
    row = await db.get(AdminUser, admin_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "管理员不存在", 404)
    status = payload.get("status", "")
    if status not in ("ACTIVE", "DISABLED"):
        raise ApiError(ERR_PARAM, "状态不合法", 400)
    if row.id == admin.id and status == "DISABLED":
        raise ApiError(ERR_BIZ_RULE, "不能停用当前登录账号", 422)
    if row.is_super_admin and status == "DISABLED":
        active_supers = int((await db.scalar(
            select(func.count()).select_from(AdminUser).where(
                AdminUser.is_super_admin.is_(True), AdminUser.status == "ACTIVE"))) or 0)
        if active_supers <= 1:
            raise ApiError(ERR_BIZ_RULE, "系统至少保留 1 个可用超级管理员", 422)
    before = {"status": row.status}
    row.status = status
    await write_audit(db, request, actor=admin, action="admin-user.status",
                      resource_type="admin_user", resource_id=row.id,
                      before=before, after={"status": status})
    await db.commit()
    return ok(await _admin_row(db, row), "状态已更新")


@router.post("/admin-users/{admin_id}/reset-password", dependencies=[AdminUserManagePerm])
async def reset_admin_password(admin_id: int, payload: dict, request: Request,
                               admin: CurrentAdmin, db: DbSession):
    row = await db.get(AdminUser, admin_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "管理员不存在", 404)
    new_password = str(payload.get("password", ""))
    _validate_admin_password(new_password)
    row.password_hash = hash_password(new_password)
    row.failed_attempts = 0
    row.locked_until = None
    await write_audit(db, request, actor=admin, action="admin-user.reset-password",
                      resource_type="admin_user", resource_id=row.id,
                      before=None, after={"reset": True})
    await db.commit()
    return ok(await _admin_row(db, row), "密码已重置")


@router.post("/admin-users/{admin_id}/unlock", dependencies=[AdminUserManagePerm])
async def unlock_admin_user(admin_id: int, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    """解除登录失败锁定（连续失败 5 次锁定 15 分钟）；不影响账号启停状态。"""
    row = await db.get(AdminUser, admin_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "管理员不存在", 404)
    before = {"failedAttempts": row.failed_attempts,
              "lockedUntil": int(row.locked_until.timestamp() * 1000) if row.locked_until else 0}
    row.failed_attempts = 0
    row.locked_until = None
    await write_audit(db, request, actor=admin, action="admin-user.unlock",
                      resource_type="admin_user", resource_id=row.id,
                      before=before, after={"failedAttempts": 0, "lockedUntil": 0})
    await db.commit()
    return ok(await _admin_row(db, row), "账号已解锁")


@router.delete("/admin-users/{admin_id}", dependencies=[AdminUserManagePerm])
async def delete_admin_user(admin_id: int, request: Request,
                            admin: CurrentAdmin, db: DbSession):
    """物理删除后台管理员账号；超级管理员与当前登录账号不可删除。"""
    row = await db.get(AdminUser, admin_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "管理员不存在", 404)
    if row.is_super_admin:
        raise ApiError(ERR_BIZ_RULE, "超级管理员不可删除", 422)
    if row.id == admin.id:
        raise ApiError(ERR_BIZ_RULE, "不能删除当前登录账号", 422)
    before = {"username": row.username, "realName": row.real_name, "email": row.email}
    await db.execute(delete(admin_user_roles)
                     .where(admin_user_roles.c.admin_user_id == row.id))
    await db.execute(delete(admin_user_communities)
                     .where(admin_user_communities.c.admin_user_id == row.id))
    await db.delete(row)
    await write_audit(db, request, actor=admin, action="admin-user.delete",
                      resource_type="admin_user", resource_id=admin_id,
                      before=before, after=None)
    await db.commit()
    return ok(None, "管理员已删除")


class BatchDeleteIn(BaseModel):
    ids: list[int] = []


@router.post("/admin-users/batch-delete", dependencies=[AdminUserManagePerm])
async def batch_delete_admin_users(payload: BatchDeleteIn, request: Request,
                                   admin: CurrentAdmin, db: DbSession):
    """批量物理删除后台管理员账号；含超级管理员或当前登录账号时整批拒绝。"""
    ids = sorted({int(item) for item in payload.ids})
    if not ids:
        raise ApiError(ERR_PARAM, "请选择要删除的账号", 400)
    rows = list((await db.execute(
        select(AdminUser).where(AdminUser.id.in_(ids)))).scalars().all())
    if not rows:
        raise ApiError(ERR_NOT_FOUND, "账号不存在", 404)
    supers = [row.username for row in rows if row.is_super_admin]
    if supers:
        raise ApiError(ERR_BIZ_RULE, f"超级管理员不可删除：{', '.join(supers)}", 422)
    if any(row.id == admin.id for row in rows):
        raise ApiError(ERR_BIZ_RULE, "不能删除当前登录账号", 422)
    await db.execute(delete(admin_user_roles)
                     .where(admin_user_roles.c.admin_user_id.in_(ids)))
    await db.execute(delete(admin_user_communities)
                     .where(admin_user_communities.c.admin_user_id.in_(ids)))
    for row in rows:
        await db.delete(row)
    await write_audit(db, request, actor=admin, action="admin-user.batch-delete",
                      resource_type="admin_user", resource_id=",".join(str(i) for i in ids),
                      before={"accounts": [{"id": row.id, "username": row.username}
                                           for row in rows]},
                      after=None)
    await db.commit()
    return ok({"deleted": len(rows)}, f"已删除 {len(rows)} 个管理员账号")
