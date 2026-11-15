"""站内通知服务：写 AppNotification（C 端通知中心）+ Outbox 事件（后续接 Push/短信）。

同类事件 5 分钟聚合去重由通知消费者实现（移动端详设 11.5），此处只负责落库与发件箱。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.audit import write_outbox
from src.db.models import AppNotification


async def notify_user(
    db: AsyncSession,
    user_id: int,
    *,
    category: str,
    title: str,
    description: str = "",
    icon: str = "",
    tag: str = "",
    route: dict | None = None,
    event_type: str = "NotificationRequested",
) -> AppNotification:
    notification = AppNotification(
        user_id=user_id,
        category=category,
        title=title,
        description=description,
        icon=icon,
        tag=tag,
        route=route or {},
    )
    db.add(notification)
    await db.flush()
    await write_outbox(
        db,
        event_type=event_type,
        aggregate_type="app_notification",
        aggregate_id=notification.id,
        payload={"userId": user_id, "category": category, "title": title},
    )
    # 在线推送（WS 下行 NOTIFY）；离线由端侧拉取兜底
    from src.core.ws_manager import ws_manager

    await ws_manager.push(user_id, "NOTIFY", {
        "id": notification.id, "category": category, "title": title,
        "description": description, "tag": tag, "route": route or {},
    })
    return notification
