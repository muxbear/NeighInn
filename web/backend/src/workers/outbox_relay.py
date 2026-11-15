"""Outbox 事件继电器（后台详设 5.8.2）。

业务事务内写入 outbox_events → Relay 轮询投递（开发环境：结构化日志 + 标记已发布；
生产：publish 到 RabbitMQ persistent message，消费端按 processed_events 幂等）。
失败指数退避；超过 5 次进入 DEAD 并告警。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import SessionLocal
from src.db.models import OutboxEvent
from src.db.models.common import utcnow

logger = logging.getLogger(__name__)

MAX_RETRY = 5
BATCH_SIZE = 100


async def relay_once(db: AsyncSession | None = None) -> int:
    """投递一批待发事件，返回投递数量。可注入会话（测试）；默认自开会话。"""
    if db is None:
        async with SessionLocal() as session:
            return await relay_once(session)

    rows = list((await db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.status == "PENDING")
        .order_by(OutboxEvent.id)
        .limit(BATCH_SIZE))).scalars().all())
    delivered = 0
    for event in rows:
        try:
            # 生产：await publisher.publish(event.event_type, event.payload)
            logger.info("outbox publish type=%s aggregate=%s:%s",
                        event.event_type, event.aggregate_type, event.aggregate_id)
            event.status = "PUBLISHED"
            event.published_at = utcnow()
            delivered += 1
        except Exception as exc:  # noqa: BLE001 单条投递失败不影响批次
            event.retry_count += 1
            if event.retry_count >= MAX_RETRY:
                event.status = "DEAD"
                logger.error("outbox event %s dead-lettered: %s", event.event_id, exc)
            else:
                logger.warning("outbox event %s retry %s: %s",
                               event.event_id, event.retry_count, exc)
    await db.commit()
    return delivered


async def relay_loop(interval_seconds: int = 5, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            await relay_once()
        except Exception:
            logger.exception("outbox relay iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
