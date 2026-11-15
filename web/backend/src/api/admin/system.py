from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.db.models import AuditLog, Dictionary, DictionaryItem, ParameterItem, ParameterKey
from src.db.models.common import utcnow
from src.services import param_service

router = APIRouter(tags=["admin:system"])


# ---------------------------------------------------------------- 参数配置（W04-05）

def _key_node(key: ParameterKey) -> dict:
    return {"id": str(key.id), "label": key.label, "code": key.code,
            "kind": key.kind, "status": key.status, "sort": key.sort}


@router.get("/parameter-nodes/tree")
async def parameter_tree(admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(ParameterKey).order_by(ParameterKey.sort, ParameterKey.id))).scalars().all())
    nodes = {row.id: {**_key_node(row), "children": []} for row in rows}
    roots: list[dict] = []
    for row in rows:
        node = nodes[row.id]
        if row.parent_id and row.parent_id in nodes:
            nodes[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok(roots)


@router.post("/parameter-nodes",
             dependencies=[Depends(require_permission("system:parameter:create"))])
async def create_parameter_node(payload: dict, request: Request,
                                admin: CurrentAdmin, db: DbSession):
    label = str(payload.get("label", "")).strip()
    code = str(payload.get("code", "")).strip()
    if not label or not code:
        raise ApiError(ERR_PARAM, "名称与编码必填", 400)
    if await db.scalar(select(ParameterKey).where(ParameterKey.code == code)):
        raise ApiError(40901, "参数键编码已存在", 409)
    node = ParameterKey(label=label, code=code, kind=payload.get("kind", "KEY"),
                        parent_id=payload.get("parentId"), sort=int(payload.get("sort", 0)))
    db.add(node)
    await db.flush()
    await write_audit(db, request, actor=admin, action="parameter-node.create",
                      resource_type="parameter_key", resource_id=node.id,
                      before=None, after={"code": code})
    await db.commit()
    return ok(_key_node(node), "参数节点已创建")


@router.get("/parameter-keys/{key_id}/items")
async def parameter_items(key_id: int, admin: CurrentAdmin, db: DbSession):
    key = await db.get(ParameterKey, key_id)
    if not key:
        raise ApiError(ERR_NOT_FOUND, "参数键不存在", 404)
    rows = list((await db.execute(
        select(ParameterItem).where(ParameterItem.parameter_key_id == key_id)
        .order_by(ParameterItem.id))).scalars().all())
    return ok({
        "key": _key_node(key),
        "items": [{"id": str(row.id), "name": row.name, "value": row.value,
                   "description": row.description, "status": row.status,
                   "updatedAt": int(row.updated_at.timestamp() * 1000) if row.updated_at else 0}
                  for row in rows],
    })


class ParameterItemIn(BaseModel):
    value: str | None = None
    description: str | None = None
    reason: str = ""


@router.put("/parameter-items/{item_id}",
            dependencies=[Depends(require_permission("system:parameter:update"))])
async def update_parameter_item(item_id: int, payload: ParameterItemIn,
                                request: Request, admin: CurrentAdmin, db: DbSession):
    """修改参数项：保存不生效，需发布；高危参数建议填 reason（审计可追溯）。"""
    item = await db.get(ParameterItem, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "参数项不存在", 404)
    before = {"value": item.value, "description": item.description, "status": item.status}
    if payload.value is not None:
        item.value = str(payload.value)[:255]
    if payload.description is not None:
        item.description = payload.description[:255]
    item.updated_by = admin.id
    item.updated_at = utcnow()
    await write_audit(db, request, actor=admin, action="parameter-item.update",
                      resource_type="parameter_item", resource_id=item.id,
                      before=before,
                      after={"value": item.value, "reason": payload.reason})
    await db.commit()
    return ok({"id": str(item.id), "value": item.value}, "参数项已保存（发布后不生效）")


@router.patch("/parameter-items/{item_id}/status",
              dependencies=[Depends(require_permission("system:parameter:update"))])
async def toggle_parameter_item(item_id: int, request: Request,
                                admin: CurrentAdmin, db: DbSession):
    item = await db.get(ParameterItem, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "参数项不存在", 404)
    item.status = "停用" if item.status == "启用" else "启用"
    item.updated_at = utcnow()
    param_service.invalidate_cache()
    await write_audit(db, request, actor=admin, action="parameter-item.toggle",
                      resource_type="parameter_item", resource_id=item.id,
                      before=None, after={"status": item.status})
    await db.commit()
    return ok({"id": str(item.id), "status": item.status}, "状态已切换")


@router.post("/parameter-items/{item_id}/publish",
             dependencies=[Depends(require_permission("system:parameter:publish"))])
async def publish_parameter_item(item_id: int, request: Request,
                                 admin: CurrentAdmin, db: DbSession):
    """发布生效：失效参数缓存，移动端 AppConfig 下次读取即更新。"""
    item = await db.get(ParameterItem, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "参数项不存在", 404)
    item.updated_at = utcnow()
    param_service.invalidate_cache()
    await write_audit(db, request, actor=admin, action="parameter-item.publish",
                      resource_type="parameter_item", resource_id=item.id,
                      before=None, after={"value": item.value, "status": item.status})
    await db.commit()
    return ok({"id": str(item.id), "status": item.status}, "参数已发布并即时生效")


@router.get("/parameters/{key}")
async def get_parameter(key: str, admin: CurrentAdmin, db: DbSession):
    value = await param_service.get_param(db, key, "")
    return ok({"key": key, "value": value})


# ---------------------------------------------------------------- 字典

@router.get("/dictionaries")
async def list_dictionaries(admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(select(Dictionary).order_by(Dictionary.id))).scalars().all())
    return ok([{"id": str(row.id), "code": row.code, "name": row.name,
                "description": row.description} for row in rows])


@router.get("/dictionaries/{dict_id}/items")
async def dictionary_items(dict_id: int, admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(DictionaryItem).where(DictionaryItem.dictionary_id == dict_id)
        .order_by(DictionaryItem.sort, DictionaryItem.id))).scalars().all())
    return ok([{"id": str(row.id), "label": row.label, "value": row.value,
                "tone": row.tone, "sort": row.sort, "status": row.status}
               for row in rows])


# ---------------------------------------------------------------- 审计日志（W01-03：只读）

@router.get("/audit-logs",
            dependencies=[Depends(require_permission("system:audit:view"))])
async def list_audit_logs(admin: CurrentAdmin, db: DbSession,
                          keyword: str | None = Query(default=None),
                          action: str | None = Query(default=None),
                          page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(AuditLog.actor_name.ilike(like),
                              AuditLog.action.ilike(like),
                              AuditLog.resource_id.ilike(like),
                              AuditLog.trace_id.ilike(like)))
    rows, total = await paginate(db, stmt.order_by(AuditLog.id.desc()), page, pageSize)
    return paginated([{
        "id": str(row.id), "actorName": row.actor_name, "action": row.action,
        "resourceType": row.resource_type, "resourceId": row.resource_id,
        "result": row.result, "ip": row.ip, "traceId": row.trace_id,
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
    } for row in rows], page, pageSize, total)


@router.get("/audit-logs/{log_id}",
            dependencies=[Depends(require_permission("system:audit:view"))])
async def audit_log_detail(log_id: int, admin: CurrentAdmin, db: DbSession):
    """详情含 before/after JSON diff、请求上下文、traceId。"""
    row = await db.get(AuditLog, log_id)
    if not row:
        raise ApiError(ERR_NOT_FOUND, "审计日志不存在", 404)
    return ok({
        "id": str(row.id), "actorId": str(row.actor_id) if row.actor_id else "",
        "actorName": row.actor_name, "action": row.action,
        "resourceType": row.resource_type, "resourceId": row.resource_id,
        "beforeSnapshot": row.before_snapshot, "afterSnapshot": row.after_snapshot,
        "ip": row.ip, "userAgent": row.user_agent, "traceId": row.trace_id,
        "result": row.result,
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
    })
