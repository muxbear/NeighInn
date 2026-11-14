from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import or_, select

from src.api.utils import get_or_404, paginate
from src.core.deps import CurrentAdmin, DbSession
from src.core.responses import ok, paginated
from src.db.models import Notice, NotificationTask

router = APIRouter(tags=["communication"])


class NoticeIn(BaseModel):
    title: str
    scope: str = "全部社区"
    publisher: str = "运营中心"
    content: str = ""
    communityId: int | None = None
    status: str = "已发布"


class TaskIn(BaseModel):
    name: str
    channels: str = "站内信"
    target: str = "全部用户"
    template: str = ""
    status: str = "草稿"


def serialize_notice(row: Notice) -> dict:
    return {
        "id": str(row.id), "title": row.title, "scope": row.scope, "publisher": row.publisher,
        "readProgress": row.read_progress, "status": row.status, "publishedAt": row.published_label,
        "pinned": row.pinned, "communityId": str(row.community_id) if row.community_id else "",
    }


def serialize_task(row: NotificationTask) -> dict:
    return {
        "id": str(row.id), "name": row.name, "channels": row.channels, "target": row.target,
        "delivery": row.delivery, "status": row.status, "sentAt": row.sent_label,
    }


@router.get("/notices")
async def list_notices(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(Notice)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Notice.title.ilike(like), Notice.scope.ilike(like), Notice.publisher.ilike(like)))
    if status:
        stmt = stmt.where(Notice.status == status)
    rows, total = await paginate(db, stmt.order_by(Notice.id), page, pageSize)
    return paginated([serialize_notice(row) for row in rows], page, pageSize, total)


@router.post("/notices")
async def create_notice(payload: NoticeIn, db: DbSession, admin: CurrentAdmin):
    row = Notice(
        community_id=payload.communityId, title=payload.title, scope=payload.scope,
        publisher=payload.publisher, status=payload.status, published_label="刚刚",
        content=payload.content,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_notice(row), "公告已创建")


@router.post("/notices/{notice_id}/publish")
async def publish_notice(notice_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Notice, notice_id)
    row.status = "已发布"
    row.published_label = "刚刚"
    await db.commit()
    return ok(serialize_notice(row), "公告已发布")


@router.post("/notices/{notice_id}/withdraw")
async def withdraw_notice(notice_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, Notice, notice_id)
    row.status = "已撤回"
    await db.commit()
    return ok(serialize_notice(row), "公告已撤回")


@router.get("/notification-tasks")
async def list_tasks(
    db: DbSession, admin: CurrentAdmin, keyword: str | None = None,
    status: str | None = None, page: int = 1, pageSize: int = 20,
):
    stmt = select(NotificationTask)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(NotificationTask.name.ilike(like), NotificationTask.channels.ilike(like)))
    if status:
        stmt = stmt.where(NotificationTask.status == status)
    rows, total = await paginate(db, stmt.order_by(NotificationTask.id), page, pageSize)
    return paginated([serialize_task(row) for row in rows], page, pageSize, total)


@router.post("/notification-tasks")
async def create_task(payload: TaskIn, db: DbSession, admin: CurrentAdmin):
    row = NotificationTask(
        name=payload.name, channels=payload.channels, target=payload.target,
        template=payload.template, status=payload.status, sent_label="未发送",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(serialize_task(row), "通知任务已创建")


@router.post("/notification-tasks/{task_id}/send")
async def send_task(task_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, NotificationTask, task_id)
    row.status = "已完成"
    row.delivery = row.delivery if row.delivery != "—" else "0 / 0"
    row.sent_label = "刚刚"
    await db.commit()
    return ok(serialize_task(row), "通知任务已提交发送")


@router.post("/notification-tasks/{task_id}/cancel")
async def cancel_task(task_id: int, db: DbSession, admin: CurrentAdmin):
    row = await get_or_404(db, NotificationTask, task_id)
    row.status = "已取消"
    await db.commit()
    return ok(serialize_task(row), "通知任务已取消")
