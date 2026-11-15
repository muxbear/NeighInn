from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update

from src.api.utils import paginate
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_NOT_FOUND, ApiError, ok, paginated
from src.db.models import AppNotification

router = APIRouter(tags=["c:notifications"])

# 移动端分类（mobile/models/notification.model.ts）：交易 / 互动 / 社区
CATEGORY_LABEL = {"TRADE": "交易", "INTERACTION": "互动", "COMMUNITY": "社区"}
CATEGORY_CODE = {v: k for k, v in CATEGORY_LABEL.items()}

DEFAULT_SETTINGS = {
    "pushEnabled": True,
    "tradeEnabled": True,
    "communityEnabled": True,
    "interactionEnabled": True,
}


def _time_ago(dt: datetime | None) -> str:
    if not dt:
        return ""
    delta = datetime.now(UTC).replace(tzinfo=None) - dt.replace(tzinfo=None)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    return f"{hours // 24}天前"


def _row(notification: AppNotification) -> dict:
    return {
        "id": notification.id,
        "category": CATEGORY_LABEL.get(notification.category, notification.category),
        "icon": notification.icon,
        "title": notification.title,
        "description": notification.description,
        "time": _time_ago(notification.created_at),
        "createdAt": int(notification.created_at.timestamp() * 1000) if notification.created_at else 0,
        "tag": notification.tag,
        "route": notification.route or {},
        "read": notification.read_at is not None,
    }


@router.get("/notifications")
async def list_notifications(
    user: CurrentUser, db: DbSession,
    category: str = Query(default="全部"),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    """通知中心（M07-03）：交易/互动/社区分类。"""
    stmt = select(AppNotification).where(AppNotification.user_id == user.id)
    code = CATEGORY_CODE.get(category)
    if code:
        stmt = stmt.where(AppNotification.category == code)
    rows, total = await paginate(db, stmt.order_by(AppNotification.id.desc()), page, pageSize)
    return paginated([_row(row) for row in rows], page, pageSize, total)


@router.get("/notifications/unread")
async def unread_summary(user: CurrentUser, db: DbSession):
    unread = int((await db.scalar(
        select(func.count()).select_from(AppNotification).where(
            AppNotification.user_id == user.id, AppNotification.read_at.is_(None)))) or 0)
    from src.db.models import Conversation

    conversations = int((await db.scalar(
        select(func.count()).select_from(Conversation).where(
            (Conversation.user_a_id == user.id) | (Conversation.user_b_id == user.id)))) or 0)
    return ok({"count": unread, "conversationCount": conversations})


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: int, user: CurrentUser, db: DbSession):
    notification = await db.get(AppNotification, notification_id)
    if not notification or notification.user_id != user.id:
        raise ApiError(ERR_NOT_FOUND, "通知不存在", 404)
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
    unread = int((await db.scalar(
        select(func.count()).select_from(AppNotification).where(
            AppNotification.user_id == user.id, AppNotification.read_at.is_(None)))) or 0)
    return ok({"success": True, "unread": unread})


@router.post("/notifications/read-all")
async def read_all_notifications(user: CurrentUser, db: DbSession):
    await db.execute(
        update(AppNotification)
        .where(AppNotification.user_id == user.id, AppNotification.read_at.is_(None))
        .values(read_at=datetime.now(UTC).replace(tzinfo=None)))
    await db.commit()
    return ok({"success": True})


@router.get("/notifications/settings")
async def notification_settings(user: CurrentUser, db: DbSession):
    stored = (user.settings_json or {}).get("notifications", {})
    return ok({**DEFAULT_SETTINGS, **stored})


class SettingsIn(BaseModel):
    pushEnabled: bool | None = None
    tradeEnabled: bool | None = None
    communityEnabled: bool | None = None
    interactionEnabled: bool | None = None


@router.put("/notifications/settings")
async def update_notification_settings(payload: SettingsIn, user: CurrentUser, db: DbSession):
    stored = dict((user.settings_json or {}).get("notifications", {}))
    for key, value in payload.model_dump(exclude_none=True).items():
        stored[key] = value
    settings_json = dict(user.settings_json or {})
    settings_json["notifications"] = stored
    user.settings_json = settings_json
    await db.commit()
    return ok({**DEFAULT_SETTINGS, **stored}, "通知设置已保存")
