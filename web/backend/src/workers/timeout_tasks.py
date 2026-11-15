"""时间驱动业务任务（此前状态机有承诺但无执行者的规则）：

- M06-03 / 30min：下单未支付自动取消并解锁物品；
- M06-02 / 48h：赠与/互换申请未确认自动取消；
- BR-11 / 72h：买家验货确认后卖家未响应（或双方未完成确认）自动放款；
- BR-07 / 30 天：物品到期自动下架（EXPIRED，可续期）。

生产：替换为 Celery/Arq 定时任务；当前为进程内轮询（settings.enable_scheduler）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import SessionLocal
from src.db.models import Item, Order
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import item_sm, order_sm
from src.services import order_service as order_svc
from src.services import pay_service
from src.services.notify_service import notify_user

logger = logging.getLogger(__name__)


async def cancel_unpaid_orders(db: AsyncSession) -> int:
    rows = list((await db.execute(
        select(Order).where(
            Order.status == E.OrderStatus.PENDING_PAYMENT,
            Order.pay_deadline_at.is_not(None),
            Order.pay_deadline_at < utcnow()))).scalars().all())
    for order in rows:
        order.status = order_sm.fire(order.status, E.OrderStatus.CANCELLED)
        order.cancel_reason = "超时未支付自动取消"
        await order_svc.add_event(db, order, "CANCELLED", note="超过支付时限自动取消")
        await order_svc.unlock_item(db, order.item_id)
        await order_svc.unlock_swap_items(db, order)
        await notify_user(db, order.buyer_id, category="TRADE", title="订单已超时取消",
                          description="超过支付时限未付款，订单已自动取消",
                          icon="clock", tag="订单", route={"type": "order", "id": str(order.id)})
        await notify_user(db, order.seller_id, category="TRADE", title="订单已超时取消",
                          description="买家未在时限内付款，物品已重新上架",
                          icon="clock", tag="订单", route={"type": "order", "id": str(order.id)})
    return len(rows)


async def cancel_stale_confirmations(db: AsyncSession) -> int:
    rows = list((await db.execute(
        select(Order).where(
            Order.status.in_([E.OrderStatus.APPLIED, E.OrderStatus.PENDING_CONFIRM]),
            Order.confirm_deadline_at.is_not(None),
            Order.confirm_deadline_at < utcnow()))).scalars().all())
    for order in rows:
        order.status = order_sm.fire(order.status, E.OrderStatus.CANCELLED)
        order.cancel_reason = "申请超时未确认自动取消"
        await order_svc.add_event(db, order, "CANCELLED", note="超过 48 小时未确认自动取消")
        await order_svc.unlock_item(db, order.item_id)
        await order_svc.unlock_swap_items(db, order)
        await notify_user(db, order.buyer_id, category="TRADE", title="申请已超时取消",
                          description="卖家未在 48 小时内确认，物品已重新上架",
                          icon="clock", tag="订单", route={"type": "order", "id": str(order.id)})
    return len(rows)


async def auto_release_orders(db: AsyncSession) -> int:
    """BR-11：验货确认后超时（默认 72h）自动放款。买家确认后即写入 release_deadline_at。"""
    rows = list((await db.execute(
        select(Order).where(
            Order.status.in_([E.OrderStatus.INSPECTING, E.OrderStatus.PENDING_RELEASE]),
            Order.trade_type == E.TradeType.MONETARY,
            Order.release_deadline_at.is_not(None),
            Order.release_deadline_at < utcnow()))).scalars().all())
    for order in rows:
        if order.status == E.OrderStatus.INSPECTING:
            order.status = order_sm.fire(order.status, E.OrderStatus.PENDING_RELEASE)
        order.escrow_status = E.EscrowStatus.PENDING_RELEASE
        await pay_service.release_to_seller(db, order, reason="超时未确认自动放款")
        order.escrow_status = E.EscrowStatus.RELEASED
        order.status = order_sm.fire(order.status, E.OrderStatus.COMPLETED)
        order.completed_at = utcnow()
        await order_svc.add_event(db, order, "RELEASED", note="买家确认后超时自动放款")
        await order_svc.add_event(db, order, "COMPLETED", note="交易完成")
        await order_svc.unlock_item(db, order.item_id, final=E.ItemStatus.SOLD)
        await order_svc.unlock_swap_items(db, order, final=E.ItemStatus.SOLD)
        await notify_user(db, order.seller_id, category="TRADE",
                          title=f"货款 ¥{order.amount_cents / 100:g} 已自动放款",
                          description="买家确认后超时未完成操作，系统已自动放款",
                          icon="wallet", tag="放款",
                          route={"type": "order", "id": str(order.id)})
        await notify_user(db, order.buyer_id, category="TRADE", title="交易已完成",
                          description="验货确认超时，系统已自动完成放款",
                          icon="check", tag="订单",
                          route={"type": "order", "id": str(order.id)})
    return len(rows)


async def expire_items(db: AsyncSession) -> int:
    rows = list((await db.execute(
        select(Item).where(
            Item.status == E.ItemStatus.ON_SALE,
            Item.expires_at.is_not(None),
            Item.expires_at < utcnow()))).scalars().all())
    for item in rows:
        item.status = item_sm.fire(item.status, E.ItemStatus.EXPIRED)
        await notify_user(db, item.seller_id, category="TRADE", title="物品已到期下架",
                          description=f"「{item.title}」已到期，可一键续期 30 天",
                          icon="clock", tag="物品", route={"type": "item", "id": str(item.id)})
    return len(rows)


async def run_timeouts(db: AsyncSession) -> dict:
    """执行一轮全部超时任务（供定时循环与测试直接调用）。"""
    result = {
        "cancelledUnpaid": await cancel_unpaid_orders(db),
        "cancelledStale": await cancel_stale_confirmations(db),
        "autoReleased": await auto_release_orders(db),
        "expiredItems": await expire_items(db),
    }
    await db.commit()
    return result


async def timeout_loop(interval_seconds: int = 60, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            async with SessionLocal() as db:
                stats = await run_timeouts(db)
                if any(stats.values()):
                    logger.info("timeout tasks: %s", stats)
        except Exception:
            logger.exception("timeout task iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def now() -> datetime:
    return utcnow()
