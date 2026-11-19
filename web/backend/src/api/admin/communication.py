from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import (
    allowed_community_ids,
    community_scope_conditions,
    require_permission,
    resolve_community_scope,
)
from src.core.responses import (
    ERR_DATA_SCOPE,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.db.models import (
    AppNotification,
    Notice,
    NoticeRead,
    NotificationRecord,
    NotificationTask,
    NotificationTemplate,
    Resident,
    User,
)
from src.db.models.common import utcnow

router = APIRouter(tags=["admin:communication"])


# ---------------------------------------------------------------- 公告（W04-04）

async def _assert_notice_scope(db: DbSession, admin: CurrentAdmin, notice: Notice) -> None:
    if notice.community_id is None:
        allowed = await allowed_community_ids(db, admin)
        if allowed is not None:
            raise ApiError(ERR_DATA_SCOPE, "数据范围越界", 403)
        return
    await resolve_community_scope(db, admin, notice.community_id)


async def _assert_task_scope(db: DbSession, admin: CurrentAdmin,
                             task: NotificationTask) -> None:
    allowed = await allowed_community_ids(db, admin)
    if allowed is None:
        return
    community_ids = set((task.target_filter or {}).get("communityIds") or [])
    if task.target_type != "COMMUNITY" or not community_ids:
        raise ApiError(ERR_DATA_SCOPE, "无权向全部社区发送通知", 403)
    if not community_ids.issubset(allowed):
        raise ApiError(ERR_DATA_SCOPE, "数据范围越界", 403)


class NoticeIn(BaseModel):
    title: str
    scope: str = "全部社区"
    content: str = ""
    communityId: int | None = None
    pinned: bool = False


async def _notice_row(db: DbSession, notice: Notice) -> dict:
    target = int((await db.scalar(
        select(func.count()).select_from(Resident).where(
            Resident.certification_status == "VERIFIED",
            *( [Resident.community_id == notice.community_id] if notice.community_id else []),
        ))) or 0)
    read = int((await db.scalar(
        select(func.count()).select_from(NoticeRead).where(
            NoticeRead.notice_id == notice.id))) or 0)
    return {
        "id": str(notice.id), "title": notice.title, "scope": notice.scope,
        "content": notice.content, "status": notice.status, "pinned": notice.pinned,
        "communityId": str(notice.community_id) if notice.community_id else "",
        "readProgress": f"{read} / {target}" if target else "—",
        "readCount": read, "targetCount": target,
        "publishedAt": int(notice.published_at.timestamp() * 1000) if notice.published_at else 0,
        "createdAt": int(notice.created_at.timestamp() * 1000) if notice.created_at else 0,
    }


@router.get("/notices")
async def list_notices(admin: CurrentAdmin, db: DbSession,
                       keyword: str | None = Query(default=None),
                       status: str | None = Query(default=None),
                       page: int = Query(default=1), pageSize: int = Query(default=20)):
    resolved = await resolve_community_scope(db, admin, None)
    stmt = select(Notice).where(
        *community_scope_conditions(resolved, Notice.community_id))
    if keyword:
        stmt = stmt.where(or_(Notice.title.ilike(f"%{keyword}%"),
                              Notice.scope.ilike(f"%{keyword}%")))
    if status:
        stmt = stmt.where(Notice.status == status)
    rows, total = await paginate(db, stmt.order_by(Notice.id.desc()), page, pageSize)
    return paginated([await _notice_row(db, row) for row in rows], page, pageSize, total)


@router.post("/notices",
             dependencies=[Depends(require_permission("communication:notice:create"))])
async def create_notice(payload: NoticeIn, request: Request,
                        admin: CurrentAdmin, db: DbSession):
    if len(payload.title.strip()) < 2:
        raise ApiError(ERR_PARAM, "公告标题必填", 400)
    resolved = await resolve_community_scope(db, admin, payload.communityId)
    if isinstance(resolved, set) and payload.communityId is None:
        raise ApiError(ERR_DATA_SCOPE, "无权发布全平台公告", 403)
    notice = Notice(
        community_id=payload.communityId, title=payload.title.strip()[:120],
        content=payload.content, scope=payload.scope, pinned=payload.pinned,
        publisher_id=admin.id, status="DRAFT",
    )
    db.add(notice)
    await db.flush()
    await write_audit(db, request, actor=admin, action="notice.create",
                      resource_type="notice", resource_id=notice.id,
                      before=None, after={"title": notice.title})
    await db.commit()
    return ok(await _notice_row(db, notice), "公告已创建（草稿）")


@router.get("/notices/{notice_id}")
async def notice_detail(notice_id: int, admin: CurrentAdmin, db: DbSession):
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise ApiError(ERR_NOT_FOUND, "公告不存在", 404)
    await _assert_notice_scope(db, admin, notice)
    return ok(await _notice_row(db, notice))


@router.put("/notices/{notice_id}",
            dependencies=[Depends(require_permission("communication:notice:create"))])
async def update_notice(notice_id: int, payload: NoticeIn, request: Request,
                        admin: CurrentAdmin, db: DbSession):
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise ApiError(ERR_NOT_FOUND, "公告不存在", 404)
    await _assert_notice_scope(db, admin, notice)
    resolved = await resolve_community_scope(db, admin, payload.communityId)
    if isinstance(resolved, set) and payload.communityId is None:
        raise ApiError(ERR_DATA_SCOPE, "无权发布全平台公告", 403)
    if notice.status == "PUBLISHED":
        raise ApiError(ERR_PARAM, "已发布公告请先撤回再编辑", 400)
    before = {"title": notice.title}
    notice.title = payload.title.strip()[:120]
    notice.content = payload.content
    notice.scope = payload.scope
    notice.community_id = payload.communityId
    notice.pinned = payload.pinned
    await write_audit(db, request, actor=admin, action="notice.update",
                      resource_type="notice", resource_id=notice.id,
                      before=before, after={"title": notice.title})
    await db.commit()
    return ok(await _notice_row(db, notice), "已保存")


@router.post("/notices/{notice_id}/publish",
             dependencies=[Depends(require_permission("communication:notice:publish"))])
async def publish_notice(notice_id: int, request: Request,
                         admin: CurrentAdmin, db: DbSession):
    """发布：向目标社区已认证住户下发站内通知（AppNotification）。"""
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise ApiError(ERR_NOT_FOUND, "公告不存在", 404)
    await _assert_notice_scope(db, admin, notice)
    if notice.status == "PUBLISHED":
        raise ApiError(ERR_PARAM, "公告已发布", 400)
    notice.status = "PUBLISHED"
    notice.published_at = utcnow()

    stmt = select(Resident).where(Resident.certification_status == "VERIFIED",
                                  Resident.user_id.is_not(None))
    if notice.community_id:
        stmt = stmt.where(Resident.community_id == notice.community_id)
    residents = list((await db.execute(stmt)).scalars().all())
    for resident in residents[:5000]:
        db.add(AppNotification(
            user_id=resident.user_id, category="COMMUNITY", title=notice.title,
            description=notice.content[:200], icon="megaphone", tag="公告",
            route={"type": "broadcast", "id": str(notice.id)},
        ))
    await write_audit(db, request, actor=admin, action="notice.publish",
                      resource_type="notice", resource_id=notice.id,
                      before={"status": "DRAFT"},
                      after={"status": "PUBLISHED", "targets": len(residents)})
    await db.commit()
    return ok(await _notice_row(db, notice), f"公告已发布，触达 {len(residents)} 位住户")


@router.post("/notices/{notice_id}/withdraw",
             dependencies=[Depends(require_permission("communication:notice:publish"))])
async def withdraw_notice(notice_id: int, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise ApiError(ERR_NOT_FOUND, "公告不存在", 404)
    await _assert_notice_scope(db, admin, notice)
    before = {"status": notice.status}
    notice.status = "WITHDRAWN"
    await write_audit(db, request, actor=admin, action="notice.withdraw",
                      resource_type="notice", resource_id=notice.id,
                      before=before, after={"status": "WITHDRAWN"})
    await db.commit()
    return ok(await _notice_row(db, notice), "公告已撤回")


@router.get("/notices/{notice_id}/reads")
async def notice_reads(notice_id: int, admin: CurrentAdmin, db: DbSession):
    notice = await db.get(Notice, notice_id)
    if not notice:
        raise ApiError(ERR_NOT_FOUND, "公告不存在", 404)
    await _assert_notice_scope(db, admin, notice)
    rows = list((await db.execute(
        select(NoticeRead).where(NoticeRead.notice_id == notice_id)
        .order_by(NoticeRead.read_at.desc()).limit(200))).scalars().all())
    result = []
    for row in rows:
        user = await db.get(User, row.user_id)
        result.append({"userId": str(row.user_id),
                       "name": user.nickname if user else "",
                       "readAt": int(row.read_at.timestamp() * 1000) if row.read_at else 0})
    return ok(result)


# ---------------------------------------------------------------- 通知任务（触达中心）

class TaskIn(BaseModel):
    name: str
    channels: str = "IN_APP"  # IN_APP / SMS / PUSH / SERVICE（逗号分隔）
    targetType: str = "ALL"  # ALL / COMMUNITY / IMPORTED
    communityIds: list[int] = []
    templateId: int | None = None
    content: str = ""


async def _task_row(db: DbSession, task: NotificationTask) -> dict:
    delivered = int((await db.scalar(
        select(func.count()).select_from(NotificationRecord).where(
            NotificationRecord.task_id == task.id,
            NotificationRecord.status.in_(["SENT", "DELIVERED", "READ"])))) or 0)
    read = int((await db.scalar(
        select(func.count()).select_from(NotificationRecord).where(
            NotificationRecord.task_id == task.id,
            NotificationRecord.status == "READ"))) or 0)
    total = int((await db.scalar(
        select(func.count()).select_from(NotificationRecord).where(
            NotificationRecord.task_id == task.id))) or 0)
    return {
        "id": str(task.id), "name": task.name, "channels": task.channels,
        "targetType": task.target_type, "targetFilter": task.target_filter,
        "status": task.status, "delivery": f"{delivered} / {total}",
        "readCount": read,
        "sentAt": int(task.sent_at.timestamp() * 1000) if task.sent_at else 0,
        "createdAt": int(task.created_at.timestamp() * 1000) if task.created_at else 0,
    }


@router.get("/notification-templates")
async def list_templates(admin: CurrentAdmin, db: DbSession):
    rows = list((await db.execute(
        select(NotificationTemplate).order_by(NotificationTemplate.id))).scalars().all())
    return ok([{"id": str(row.id), "code": row.code, "name": row.name,
                "title": row.title, "content": row.content, "channels": row.channels}
               for row in rows])


@router.get("/notification-tasks")
async def list_tasks(admin: CurrentAdmin, db: DbSession,
                     keyword: str | None = Query(default=None),
                     status: str | None = Query(default=None),
                     page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(NotificationTask)
    if keyword:
        stmt = stmt.where(NotificationTask.name.ilike(f"%{keyword}%"))
    if status:
        stmt = stmt.where(NotificationTask.status == status)
    resolved = await resolve_community_scope(db, admin, None)
    if isinstance(resolved, set):
        all_rows = list((await db.execute(
            stmt.order_by(NotificationTask.id.desc()))).scalars().all())
        allowed_ids = resolved

        def _visible(task: NotificationTask) -> bool:
            ids = set((task.target_filter or {}).get("communityIds") or [])
            return task.target_type == "COMMUNITY" and bool(ids) and ids.issubset(allowed_ids)

        filtered = [row for row in all_rows if _visible(row)]
        total = len(filtered)
        start = (page - 1) * pageSize
        rows = filtered[start:start + pageSize]
    else:
        rows, total = await paginate(
            db, stmt.order_by(NotificationTask.id.desc()), page, pageSize)
    return paginated([await _task_row(db, row) for row in rows], page, pageSize, total)


@router.post("/notification-tasks",
             dependencies=[Depends(require_permission("communication:task:create"))])
async def create_task(payload: TaskIn, request: Request,
                      admin: CurrentAdmin, db: DbSession):
    if len(payload.name.strip()) < 2:
        raise ApiError(ERR_PARAM, "任务名称必填", 400)
    allowed = await allowed_community_ids(db, admin)
    if allowed is not None:
        if payload.targetType != "COMMUNITY" or not payload.communityIds:
            raise ApiError(ERR_DATA_SCOPE, "无权向全部社区发送通知", 403)
        if not set(payload.communityIds).issubset(allowed):
            raise ApiError(ERR_DATA_SCOPE, "数据范围越界", 403)
    task = NotificationTask(
        name=payload.name.strip()[:120], channels=payload.channels,
        target_type=payload.targetType,
        target_filter={"communityIds": payload.communityIds},
        template_id=payload.templateId, status="DRAFT", created_by=admin.id,
    )
    db.add(task)
    await db.flush()
    await write_audit(db, request, actor=admin, action="notification-task.create",
                      resource_type="notification_task", resource_id=task.id,
                      before=None, after={"name": task.name})
    await db.commit()
    return ok(await _task_row(db, task), "通知任务已创建（草稿）")


@router.get("/notification-tasks/{task_id}")
async def task_detail(task_id: int, admin: CurrentAdmin, db: DbSession):
    task = await db.get(NotificationTask, task_id)
    if not task:
        raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
    await _assert_task_scope(db, admin, task)
    return ok(await _task_row(db, task))


@router.get("/notification-tasks/{task_id}/estimate")
async def estimate_task(task_id: int, admin: CurrentAdmin, db: DbSession):
    """目标人群预估（发送前）。排除黑名单与退订用户。"""
    task = await db.get(NotificationTask, task_id)
    if not task:
        raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
    await _assert_task_scope(db, admin, task)
    count = await _estimate_targets(db, task)
    return ok({"estimated": count})


async def _estimate_targets(db: DbSession, task: NotificationTask) -> int:
    community_ids = (task.target_filter or {}).get("communityIds") or []
    if task.target_type == "COMMUNITY" and community_ids:
        return int((await db.scalar(
            select(func.count()).select_from(Resident).where(
                Resident.certification_status == "VERIFIED",
                Resident.user_id.is_not(None),
                Resident.community_id.in_(community_ids)))) or 0)
    return int((await db.scalar(
        select(func.count()).select_from(Resident).where(
            Resident.certification_status == "VERIFIED",
            Resident.user_id.is_not(None)))) or 0)


async def _target_user_ids(db: DbSession, task: NotificationTask) -> list[int]:
    community_ids = (task.target_filter or {}).get("communityIds") or []
    stmt = select(Resident.user_id).where(
        Resident.certification_status == "VERIFIED", Resident.user_id.is_not(None))
    if task.target_type == "COMMUNITY" and community_ids:
        stmt = stmt.where(Resident.community_id.in_(community_ids))
    return [int(uid) for uid in (await db.execute(stmt)).scalars().all()][:5000]


@router.post("/notification-tasks/{task_id}/send",
             dependencies=[Depends(require_permission("communication:task:send"))])
async def send_task(task_id: int, request: Request, admin: CurrentAdmin, db: DbSession):
    """发送：生成投递明细（站内信落 AppNotification，短信/Push 记记录待渠道回执）。"""
    task = await db.get(NotificationTask, task_id)
    if not task:
        raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
    await _assert_task_scope(db, admin, task)
    if task.status not in ("DRAFT", "SCHEDULED"):
        raise ApiError(ERR_PARAM, f"当前状态（{task.status}）不可发送", 400)
    template = await db.get(NotificationTemplate, task.template_id) if task.template_id else None
    title = template.title if template else task.name
    content = template.content if template else (task.target_filter or {}).get("content", "")

    user_ids = await _target_user_ids(db, task)
    channels = [channel.strip() for channel in task.channels.split(",") if channel.strip()]
    for user_id in user_ids:
        for channel in channels or ["IN_APP"]:
            db.add(NotificationRecord(task_id=task.id, user_id=user_id, channel=channel,
                                      title=title, content=content[:500], status="SENT",
                                      sent_at=utcnow()))
        db.add(AppNotification(user_id=user_id, category="COMMUNITY", title=title,
                               description=content[:200], icon="bell", tag="通知"))
    task.status = "COMPLETED"
    task.sent_at = utcnow()
    task.stats = {"total": len(user_ids), "channels": channels}
    await write_audit(db, request, actor=admin, action="notification-task.send",
                      resource_type="notification_task", resource_id=task.id,
                      before={"status": "DRAFT"},
                      after={"status": "COMPLETED", "total": len(user_ids)})
    await db.commit()
    return ok(await _task_row(db, task), f"已发送，触达 {len(user_ids)} 人")


@router.post("/notification-tasks/{task_id}/cancel",
             dependencies=[Depends(require_permission("communication:task:send"))])
async def cancel_task(task_id: int, request: Request, admin: CurrentAdmin, db: DbSession):
    task = await db.get(NotificationTask, task_id)
    if not task:
        raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
    await _assert_task_scope(db, admin, task)
    if task.status in ("COMPLETED", "CANCELLED"):
        raise ApiError(ERR_PARAM, "任务已结束", 400)
    before = {"status": task.status}
    task.status = "CANCELLED"
    await write_audit(db, request, actor=admin, action="notification-task.cancel",
                      resource_type="notification_task", resource_id=task.id,
                      before=before, after={"status": "CANCELLED"})
    await db.commit()
    return ok(await _task_row(db, task), "任务已取消")


@router.post("/notification-tasks/{task_id}/test")
async def test_task(task_id: int, admin: CurrentAdmin, db: DbSession):
    """测试发送：仅发给自己。"""
    task = await db.get(NotificationTask, task_id)
    if not task:
        raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
    await _assert_task_scope(db, admin, task)
    db.add(NotificationRecord(task_id=task.id, user_id=admin.id, channel="IN_APP",
                              title=f"[测试] {task.name}", status="SENT", sent_at=utcnow()))
    await db.commit()
    return ok({"success": True}, "测试消息已发送（仅发给你）")


@router.get("/notification-tasks/{task_id}/records")
async def task_records(task_id: int, admin: CurrentAdmin, db: DbSession,
                       page: int = Query(default=1), pageSize: int = Query(default=20)):
    """送达/阅读明细。"""
    task = await db.get(NotificationTask, task_id)
    if not task:
        raise ApiError(ERR_NOT_FOUND, "任务不存在", 404)
    await _assert_task_scope(db, admin, task)
    stmt = select(NotificationRecord).where(NotificationRecord.task_id == task_id)
    rows, total = await paginate(db, stmt.order_by(NotificationRecord.id.desc()), page, pageSize)
    result = []
    for row in rows:
        user = await db.get(User, row.user_id)
        result.append({"id": str(row.id), "user": user.nickname if user else "",
                       "channel": row.channel, "status": row.status, "error": row.error,
                       "sentAt": int(row.sent_at.timestamp() * 1000) if row.sent_at else 0,
                       "readAt": int(row.read_at.timestamp() * 1000) if row.read_at else 0})
    return paginated(result, page, pageSize, total)
