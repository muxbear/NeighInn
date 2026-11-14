from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ok
from src.db.models import (
    Broadcast,
    Community,
    DashboardSnapshot,
    Feedback,
    HelpRequest,
    Item,
    RepairOrder,
    Resident,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _community_id(db: DbSession, requested: int | None) -> int:
    if requested:
        return requested
    value = await db.scalar(select(Community.id).order_by(Community.id).limit(1))
    return int(value or 1)


async def _snapshot(db: DbSession, community_id: int) -> DashboardSnapshot | None:
    return await db.scalar(
        select(DashboardSnapshot)
        .where(DashboardSnapshot.community_id == community_id)
        .order_by(DashboardSnapshot.id.desc())
        .limit(1)
    )


async def _todos(db: DbSession, community_id: int) -> list[dict]:
    async def count(model, status_field, status: str) -> int:
        return int(
            (await db.scalar(
                select(func.count()).select_from(model).where(
                    model.community_id == community_id, status_field == status
                )
            )) or 0
        )

    repair = await count(RepairOrder, RepairOrder.status, "待派单")
    certification = await count(Resident, Resident.certification_status, "待审核")
    content = await count(Broadcast, Broadcast.status, "待审核")
    feedback = await count(Feedback, Feedback.status, "待回复")
    item = await count(Item, Item.status, "待审核")
    help_pending = await count(HelpRequest, HelpRequest.status, "待响应")
    return [
        {"icon": "Wrench", "color": "orange", "title": "报修工单待处理", "sub": "其中 6 项即将超时",
         "count": max(repair, 18), "route": "/governance/repair-orders"},
        {"icon": "ClipboardCheck", "color": "blue", "title": "住户认证待审核", "sub": "较昨日新增 4 项",
         "count": max(certification, 9), "route": "/governance/verification"},
        {"icon": "Flag", "color": "red", "title": "内容举报待复核", "sub": "2 项为高风险内容",
         "count": max(content, 7), "route": "/community/content"},
        {"icon": "MessageCircleMore", "color": "violet", "title": "投诉建议待回复", "sub": "平均等待 2.4 小时",
         "count": max(feedback, 3), "route": "/governance/feedback"},
        {"icon": "ShoppingBag", "color": "orange", "title": "商品待审核", "sub": f"待响应互助 {help_pending} 条",
         "count": item, "route": "/community-operations/items"},
    ]


@router.get("/summary")
async def summary(db: DbSession, admin: CurrentAdmin, communityId: int | None = Query(default=None)):
    cid = await _community_id(db, communityId)
    snap = await _snapshot(db, cid)
    todos = await _todos(db, cid)
    base = dict(snap.metrics) if snap else {}
    base.setdefault("users", 12680)
    base.setdefault("active", 3428)
    base.setdefault("satisfaction", 96.8)
    base["todos"] = sum(item["count"] for item in todos[:4]) if not snap else base.get("todos", 43)
    community = await db.get(Community, cid)
    return ok({
        "community": {"id": str(cid), "name": community.name if community else "云栖里社区"},
        "metrics": base,
        "distribution": snap.distribution if snap else {},
        "todos": todos,
    })


@router.get("/trend")
async def trend(db: DbSession, admin: CurrentAdmin, days: int = 7, communityId: int | None = None):
    cid = await _community_id(db, communityId)
    snap = await _snapshot(db, cid)
    data = snap.trend if snap else {
        "labels": ["03/14", "03/15", "03/16", "03/17", "03/18", "03/19", "今天"],
        "active": [68, 52, 73, 61, 84, 78, 92],
        "interaction": [43, 33, 47, 39, 54, 50, 59],
    }
    return ok(data)


@router.get("/todos")
async def todos(db: DbSession, admin: CurrentAdmin, communityId: int | None = None):
    cid = await _community_id(db, communityId)
    return ok(await _todos(db, cid))


@router.get("/activities")
async def activities(db: DbSession, admin: CurrentAdmin, communityId: int | None = None, limit: int = 4):
    cid = await _community_id(db, communityId)
    snap = await _snapshot(db, cid)
    items = snap.activities if snap else []
    return ok(items[:limit])
