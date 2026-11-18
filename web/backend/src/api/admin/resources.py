"""资源管理（W01-02 / 详设 4.7.10）。

当前项目尚未落 `sys_pages` / `page_resources` 实体表，本模块以 `permissions`
作为页面与页面资源的目录数据源：
- 权限表中 `type=页面` 且具备路由的记录即一个菜单页面；
- 同一权限前缀下的其他权限（按钮/开关/接口等）即该页面的可授权资源；
- 新增页面资源直接写入 `permissions`，运行时鉴权仍只读该表与角色授权关系。

后续落地独立资源目录表时，仅需替换本模块的取数实现，接口契约保持不变。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from src.api.utils import epoch_ms
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, ok
from src.db.models import Permission

router = APIRouter(tags=["admin:resource"])

ResourceViewPerm = Depends(require_permission("system:resource:view"))
ResourceCreatePerm = Depends(require_permission("system:resource:create"))

# 区域分组：按权限码前缀匹配，命中前缀最长者优先。
GROUP_RULES: tuple[tuple[str, str], ...] = (
    ("community:broadcast", "社区运营"),
    ("community:item", "社区运营"),
    ("community:help", "社区运营"),
    ("community:life", "社区运营"),
    ("community:maintenance", "社区管理"),
    ("community:resident", "社区管理"),
    ("dashboard", "总览"),
    ("communication", "触达中心"),
    ("finance", "资金与治理"),
    ("governance", "资金与治理"),
    ("system", "系统管理"),
    ("reporting", "报表与数据"),
)
GROUP_ORDER = ["总览", "社区运营", "社区管理", "触达中心", "资金与治理", "系统管理", "报表与数据"]

# 存量权限码缺少路由时的兜底（不改库即可让资源树展示当前前端真实路由）。
ROUTE_FALLBACKS = {"system:admin-user:view": "/system/users"}
# 同一路由存在新旧权限码时优先展示新码（如用户管理由 system:user 迁移至 system:admin-user）。
PREFERRED_CODES = {"system:admin-user:view"}


def _group_of(code: str) -> str:
    matched = [(prefix, label) for prefix, label in GROUP_RULES if code.startswith(prefix)]
    if not matched:
        return "其他"
    return max(matched, key=lambda item: len(item[0]))[1]


def _page_prefix(code: str) -> str:
    return code.rsplit(":", 1)[0] if code.endswith(":view") else code


def _route_of(page: Permission) -> str:
    return page.route or ROUTE_FALLBACKS.get(page.code, "")


def _page_item(page: Permission) -> dict:
    return {
        "id": str(page.id),
        "name": page.name,
        "code": _page_prefix(page.code),
        "route": _route_of(page),
    }


def _resource_item(resource: Permission) -> dict:
    return {
        "id": str(resource.id),
        "name": resource.name,
        "type": resource.type,
        "code": resource.code.rsplit(":", 1)[-1],
        "permissionCode": resource.code,
        "status": "启用" if resource.status == "ACTIVE" else "停用",
        "updatedAt": epoch_ms(resource.updated_at),
    }


async def _get_page(db: DbSession, page_id: int) -> Permission:
    page = await db.get(Permission, page_id)
    if not page or page.type != "页面":
        raise ApiError(ERR_NOT_FOUND, "页面不存在", 404)
    return page


async def _page_resources(db: DbSession, page: Permission) -> list[Permission]:
    prefix = _page_prefix(page.code)
    rows = list((await db.execute(
        select(Permission)
        .where(Permission.code.like(f"{prefix}:%"), Permission.id != page.id)
        .order_by(Permission.sort, Permission.id))).scalars().all())
    return rows


@router.get("/pages/tree", dependencies=[ResourceViewPerm])
async def page_tree(admin: CurrentAdmin, db: DbSession):
    """页面资源树：按区域分组返回「菜单页面」。"""
    pages = list((await db.execute(
        select(Permission).where(Permission.type == "页面")
        .order_by(Permission.sort, Permission.id))).scalars().all())
    pages.sort(key=lambda row: (0 if row.code in PREFERRED_CODES else 1, row.sort))
    groups: dict[str, list[dict]] = {}
    seen_routes: set[str] = set()
    for page in pages:
        route = _route_of(page)
        if not route or route in seen_routes:
            continue
        seen_routes.add(route)
        groups.setdefault(_group_of(page.code), []).append(_page_item(page))
    ordered = [{"label": label, "items": groups.pop(label)}
               for label in GROUP_ORDER if label in groups]
    ordered.extend({"label": label, "items": items} for label, items in groups.items())
    return ok(ordered)


@router.get("/pages/{page_id}", dependencies=[ResourceViewPerm])
async def page_detail(page_id: int, admin: CurrentAdmin, db: DbSession):
    page = await _get_page(db, page_id)
    resources = await _page_resources(db, page)
    return ok({
        **_page_item(page),
        "region": _group_of(page.code),
        "description": f"{page.name}页面的菜单、路由与可授权资源。",
        "status": page.status,
        "statusLabel": "页面已启用" if page.status == "ACTIVE" else "页面已停用",
        "permissionCount": len(resources) + 1,
        "updatedAt": epoch_ms(page.updated_at),
    })


@router.get("/pages/{page_id}/resources", dependencies=[ResourceViewPerm])
async def page_resources(page_id: int, admin: CurrentAdmin, db: DbSession):
    page = await _get_page(db, page_id)
    return ok([_resource_item(row) for row in await _page_resources(db, page)])


class PageResourceIn(BaseModel):
    name: str
    type: str = "按钮"


@router.post("/pages/{page_id}/resources", dependencies=[ResourceCreatePerm])
async def create_page_resource(page_id: int, payload: PageResourceIn, request: Request,
                               admin: CurrentAdmin, db: DbSession):
    page = await _get_page(db, page_id)
    name = payload.name.strip()[:64]
    resource_type = payload.type.strip()[:16] or "按钮"
    if not name:
        raise ApiError(ERR_PARAM, "资源名称必填", 400)
    prefix = _page_prefix(page.code)
    existing = set((await db.execute(
        select(Permission.code).where(Permission.code.like(f"{prefix}:%")))).scalars().all())
    index = 1
    while f"{prefix}:custom{index}" in existing:
        index += 1
    code = f"{prefix}:custom{index}"
    max_sort = int(await db.scalar(
        select(func.max(Permission.sort)).where(Permission.code.like(f"{prefix}:%"))) or 0)
    resource = Permission(name=name, code=code, type=resource_type, route="", sort=max_sort + 1)
    db.add(resource)
    await db.flush()
    await write_audit(db, request, actor=admin, action="page-resource.create",
                      resource_type="permission", resource_id=resource.id,
                      before=None, after={"code": code, "page": page.code})
    await db.commit()
    return ok(_resource_item(resource), "页面资源已创建")
