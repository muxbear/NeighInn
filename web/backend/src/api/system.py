from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import delete, or_, select

from src.api.utils import camelize, get_or_404, model_dict, paginate
from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ApiError, ok, paginated
from src.db.models import (
    AuditLog,
    PageResource,
    ParameterItem,
    ParameterKey,
    Permission,
    PlatformUser,
    Role,
    SysPage,
    role_permissions,
)

router = APIRouter(tags=["system"])


class RoleIn(BaseModel):
    name: str
    code: str | None = None
    description: str = ""
    data_scope: str = "OWN_COMMUNITY"
    status: str = "ACTIVE"


class UserIn(BaseModel):
    accountType: str = "社区居民"
    name: str
    phone: str = ""
    identity: str = ""
    communityName: str = ""
    roleName: str = ""
    status: str = "正常"


def serialize_user(row: PlatformUser) -> dict:
    return {
        "id": str(row.id), "accountType": row.account_type, "name": row.name, "phone": row.phone,
        "identity": row.identity, "communityName": row.community_name, "roleName": row.role_name,
        "status": row.status, "lastActive": row.last_active_label,
    }


def serialize_role(row: Role) -> dict:
    return {
        "id": str(row.id), "name": row.name, "code": row.code, "description": row.description,
        "members": row.members, "builtin": row.is_builtin, "status": row.status,
        "dataScope": row.data_scope, "version": row.version,
    }


@router.get("/users")
async def list_users(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(PlatformUser)
    if status:
        stmt = stmt.where(PlatformUser.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(PlatformUser.name.ilike(like), PlatformUser.phone.ilike(like),
                              PlatformUser.community_name.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(PlatformUser.id), page, pageSize)
    return paginated([serialize_user(row) for row in rows], page, pageSize, total)


@router.post("/users")
async def create_user(payload: UserIn, db: DbSession, admin: CurrentAdmin):
    row = PlatformUser(
        account_type=payload.accountType, name=payload.name, phone=payload.phone,
        identity=payload.identity, community_name=payload.communityName,
        role_name=payload.roleName, status=payload.status, last_active_label="刚刚",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_user(row), "用户已创建")


@router.put("/users/{user_id}")
async def update_user(user_id: int, payload: UserIn, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, PlatformUser, user_id)
    row.account_type = payload.accountType
    row.name = payload.name
    row.phone = payload.phone
    row.identity = payload.identity
    row.community_name = payload.communityName
    row.role_name = payload.roleName
    row.status = payload.status
    await db.commit()
    return ok(serialize_user(row), "用户已更新")


@router.patch("/users/{user_id}/status")
async def toggle_user(user_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, PlatformUser, user_id)
    row.status = payload.get("status", "已停用" if row.status == "正常" else "正常")
    await db.commit()
    return ok(serialize_user(row), "用户状态已更新")


@router.get("/roles")
async def list_roles(db: DbSession, admin: CurrentAdmin):
    rows = list((await db.execute(select(Role).order_by(Role.id))).scalars().all())
    return ok([serialize_role(row) for row in rows])


@router.post("/roles")
async def create_role(payload: RoleIn, db: DbSession, admin: CurrentAdmin):
    code = payload.code or re.sub(r"\s+", "_", payload.name.strip().lower())
    if await db.scalar(select(Role.id).where(Role.code == code)):
        raise ApiError(40901, "角色编码已存在", 409)
    row = Role(name=payload.name, code=code, description=payload.description, data_scope=payload.data_scope)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_role(row), "角色已创建")


@router.put("/roles/{role_id}")
async def update_role(role_id: int, payload: RoleIn, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Role, role_id)
    row.name = payload.name
    row.description = payload.description
    row.data_scope = payload.data_scope
    row.status = payload.status
    await db.commit()
    return ok(serialize_role(row), "角色已更新")


@router.delete("/roles/{role_id}")
async def delete_role(role_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Role, role_id)
    if row.is_builtin:
        raise ApiError(42201, "内置角色不可删除", 422)
    await db.execute(delete(role_permissions).where(role_permissions.c.role_id == role_id))
    await db.delete(row)
    await db.commit()
    return ok(None, "角色已删除")


@router.get("/roles/{role_id}/permissions")
async def role_permissions_list(role_id: int, db: DbSession, admin: CurrentAdmin):
    role = await get_or_404(db, Role, role_id)
    rows = await db.execute(
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == role_id)
    )
    return ok({"role": serialize_role(role), "permissions": list(rows.scalars().all())})


@router.put("/roles/{role_id}/permissions")
async def update_role_permissions(role_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    role = await get_or_404(db, Role, role_id)
    if role.code == "super_admin":
        raise ApiError(42201, "超级管理员权限不可修改", 422)
    codes = payload.get("permissions", [])
    rows = await db.execute(select(Permission).where(Permission.code.in_(codes)))
    permission_ids = [row.id for row in rows.scalars().all()]
    await db.execute(delete(role_permissions).where(role_permissions.c.role_id == role_id))
    for permission_id in permission_ids:
        await db.execute(
            role_permissions.insert().values(role_id=role_id, permission_id=permission_id)
        )
    role.version += 1
    await db.commit()
    return ok({"permissions": codes, "version": role.version}, "权限配置已保存")


@router.get("/permissions/tree")
async def permission_tree(db: DbSession, admin: CurrentAdmin):
    rows = list((await db.execute(select(Permission).order_by(Permission.sort))).scalars().all())
    groups: dict[str, list[dict]] = {}
    for row in rows:
        group = row.code.split(":")[0] if ":" in row.code else "其他"
        groups.setdefault(group, []).append({
            "code": row.code, "name": row.name, "type": row.type, "route": row.route,
        })
    return ok([{"label": label, "items": items} for label, items in groups.items()])


@router.get("/pages/tree")
async def pages_tree(db: DbSession, admin: CurrentAdmin):
    pages = list((await db.execute(select(SysPage).order_by(SysPage.sort, SysPage.id))).scalars().all())
    resources = list((await db.execute(select(PageResource))).scalars().all())
    counts: dict[int, int] = {}
    for resource in resources:
        counts[resource.page_id] = counts.get(resource.page_id, 0) + 1
    groups: dict[str, list[dict]] = {}
    for page in pages:
        groups.setdefault(page.region, []).append({
            "id": str(page.id), "name": page.name, "code": page.code, "route": page.route,
            "region": page.region, "icon": page.icon, "description": page.description,
            "status": page.status, "resourceCount": counts.get(page.id, 0),
        })
    order = ["总览", "社区运营", "触达中心", "社区管理", "资金与治理", "系统管理"]
    return ok([{"label": label, "items": groups[label]} for label in order if label in groups])


@router.get("/pages/{page_id}")
async def page_detail(page_id: int, db: DbSession, admin: CurrentAdmin):
    page = await get_or_404(db, SysPage, page_id)
    return ok(camelize(model_dict(page)))


@router.get("/pages/{page_id}/resources")
async def page_resources(page_id: int, db: DbSession, admin: CurrentAdmin):
    await get_or_404(db, SysPage, page_id)
    rows = list((await db.execute(
        select(PageResource).where(PageResource.page_id == page_id).order_by(PageResource.id)
    )).scalars().all())
    return ok([camelize(model_dict(row)) for row in rows])


@router.post("/pages/{page_id}/resources")
async def create_page_resource(page_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    await get_or_404(db, SysPage, page_id)
    name = payload.get("name", "自定义资源")
    row = PageResource(
        page_id=page_id, name=name, type=payload.get("type", "按钮"),
        code=payload.get("code") or f"page.{page_id}.{int(datetime.now().timestamp())}",
        permission_code=payload.get("permissionCode", ""), status="启用",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(camelize(model_dict(row)), "页面资源已创建")


@router.get("/parameter-nodes/tree")
async def parameter_tree(db: DbSession, admin: CurrentAdmin):
    rows = list((await db.execute(select(ParameterKey).order_by(ParameterKey.sort, ParameterKey.id))).scalars().all())
    nodes = {
        row.id: {
            "id": str(row.id), "label": row.label, "code": row.code, "kind": row.kind,
            "status": row.status, "children": [],
        }
        for row in rows
    }
    roots: list[dict] = []
    for row in rows:
        if row.parent_id and row.parent_id in nodes:
            nodes[row.parent_id]["children"].append(nodes[row.id])
        else:
            roots.append(nodes[row.id])
    return ok(roots)


@router.get("/parameter-keys/{key_id}/items")
async def parameter_items(key_id: int, db: DbSession, admin: CurrentAdmin):
    key = await get_or_404(db, ParameterKey, key_id)
    rows = list((await db.execute(
        select(ParameterItem).where(ParameterItem.parameter_key_id == key_id).order_by(ParameterItem.id)
    )).scalars().all())
    return ok({
        "key": {"id": str(key.id), "label": key.label, "code": key.code, "kind": key.kind},
        "items": [
            {"id": str(row.id), "name": row.name, "value": row.value, "description": row.description,
             "status": row.status, "updatedAt": row.updated_label}
            for row in rows
        ],
    })


@router.put("/parameter-items/{item_id}")
async def update_parameter_item(item_id: int, payload: dict, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, ParameterItem, item_id)
    if "value" in payload:
        row.value = str(payload["value"])
    if "description" in payload:
        row.description = payload["description"]
    if "status" in payload:
        row.status = payload["status"]
    row.updated_label = "刚刚"
    await db.commit()
    return ok({"id": str(row.id), "name": row.name, "value": row.value,
               "description": row.description, "status": row.status, "updatedAt": row.updated_label},
              "参数项已保存")


@router.patch("/parameter-items/{item_id}/status")
async def toggle_parameter_item(item_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, ParameterItem, item_id)
    row.status = "停用" if row.status == "启用" else "启用"
    row.updated_label = "刚刚"
    await db.commit()
    return ok({"id": str(row.id), "status": row.status}, "参数状态已更新")


@router.post("/parameter-items/{item_id}/publish")
async def publish_parameter_item(item_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, ParameterItem, item_id)
    row.updated_label = "刚刚"
    await db.commit()
    return ok({"id": str(row.id), "status": row.status}, "参数已发布")


@router.get("/audit-logs")
async def audit_logs(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    action: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(AuditLog.actor_name.ilike(like), AuditLog.action.ilike(like),
                              AuditLog.resource_id.ilike(like), AuditLog.trace_id.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(AuditLog.id.desc()), page, pageSize)
    return paginated([camelize(model_dict(row)) for row in rows], page, pageSize, total)


@router.get("/audit-logs/{log_id}")
async def audit_detail(log_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, AuditLog, log_id)
    return ok(camelize(model_dict(row)))


@router.get("/exports")
async def export_jobs(db: DbSession, admin: CurrentAdmin):
    return ok({"items": [], "page": 1, "pageSize": 20, "total": 0})
