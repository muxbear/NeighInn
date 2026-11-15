"""订单域服务层（M06）：订单号、序列化（含时间轴与动作位）、参与者守卫、BR-08 锁定。

BR-08：同一物品同一时刻只能有一个有效订单。生产用唯一部分索引兜底：
    CREATE UNIQUE INDEX uq_orders_active_item ON orders(item_id)
    WHERE status NOT IN ('COMPLETED','CANCELLED','REFUNDED');
应用层先校验再置 RESERVED（物品状态机守卫）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.responses import ERR_CONFLICT, ERR_FORBIDDEN, ERR_NOT_FOUND, ApiError
from src.db.models import Item, Order, OrderEvent, Review, User
from src.domain import enums as E
from src.domain.state import item_sm
from src.services import item_service as item_svc

STATUS_TEXT = {
    E.OrderStatus.PENDING_PAYMENT: "待付款",
    E.OrderStatus.ESCROWED: "已托管 · 待预约验货",
    E.OrderStatus.APPLIED: "已申请 · 待确认",
    E.OrderStatus.PENDING_CONFIRM: "待对方确认",
    E.OrderStatus.CONFIRMED: "已确认 · 待预约",
    E.OrderStatus.APPOINTMENT: "已预约 · 待见面验货",
    E.OrderStatus.INSPECTING: "验货中",
    E.OrderStatus.PENDING_RELEASE: "已成交 · 待放款",
    E.OrderStatus.COMPLETED: "交易完成",
    E.OrderStatus.CANCELLED: "已取消",
    E.OrderStatus.REFUNDING: "退款中",
    E.OrderStatus.REFUNDED: "已退款",
    E.OrderStatus.DISPUTING: "纠纷处理中",
}

MONETARY_STEPS = ["创建订单", "支付托管", "预约验货", "双方验货", "平台放款", "交易完成"]
OTHER_STEPS = ["提交申请", "对方确认", "预约见面", "双方验货", "交割完成"]


async def get_order_or_404(db: AsyncSession, order_id: int) -> Order:
    order = await db.get(Order, order_id)
    if not order:
        raise ApiError(ERR_NOT_FOUND, "订单不存在", 404)
    return order


def assert_participant(order: Order, user: User) -> str:
    """返回角色 buyer/seller；非交易双方拒绝访问。"""
    if order.buyer_id == user.id:
        return "buyer"
    if order.seller_id == user.id:
        return "seller"
    raise ApiError(ERR_FORBIDDEN, "仅交易双方可操作该订单", 403)


async def lock_item_for_order(db: AsyncSession, item_id: int) -> Item:
    """创建订单前锁定物品（BR-08）：必须 ON_SALE 且能转入 RESERVED。"""
    item = await db.get(Item, item_id)
    if not item:
        raise ApiError(ERR_NOT_FOUND, "物品不存在或已下架", 404)
    if item.status != E.ItemStatus.ON_SALE:
        raise ApiError(ERR_CONFLICT, "物品已被预约或不在售（BR-08）", 409)
    item.status = item_sm.fire(item.status, E.ItemStatus.RESERVED)
    return item


async def unlock_item(db: AsyncSession, item_id: int, final: str | None = None) -> None:
    """订单取消时解锁物品回上架；成交时转 SOLD/GIFTED 终态。"""
    item = await db.get(Item, item_id)
    if not item or item.status != E.ItemStatus.RESERVED:
        return
    if final in (E.ItemStatus.SOLD, E.ItemStatus.GIFTED):
        item.status = item_sm.fire(item.status, final)
    else:
        item.status = item_sm.fire(item.status, E.ItemStatus.ON_SALE)


async def unlock_swap_items(db: AsyncSession, order: Order, final: str | None = None) -> None:
    """互换订单：买家提供的交换物品一并解锁/终态（BR-13）。"""
    for offered in order.offered_items or []:
        await unlock_item(db, int(offered.get("item_id", 0)), final)


async def add_event(db: AsyncSession, order: Order, event: str,
                    actor_type: str = "SYSTEM", actor_id: int | None = None,
                    note: str = "", payload: dict | None = None) -> None:
    db.add(OrderEvent(order_id=order.id, event=event, actor_type=actor_type,
                      actor_id=actor_id, note=note, payload=payload or {}))
    await db.flush()


async def events_of(db: AsyncSession, order_id: int) -> list[OrderEvent]:
    return list((await db.execute(
        select(OrderEvent).where(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.id))).scalars().all())


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


def _step_rank(order: Order) -> int:
    """静态步骤进度（用于 timeline 高亮当前节点）。"""
    mapping = {
        E.OrderStatus.PENDING_PAYMENT: 0,
        E.OrderStatus.ESCROWED: 1,
        E.OrderStatus.APPLIED: 0,
        E.OrderStatus.PENDING_CONFIRM: 1,
        E.OrderStatus.CONFIRMED: 2,
        E.OrderStatus.APPOINTMENT: 2,
        E.OrderStatus.INSPECTING: 3,
        E.OrderStatus.PENDING_RELEASE: 4,
        E.OrderStatus.COMPLETED: 5,
        E.OrderStatus.CANCELLED: 0,
        E.OrderStatus.REFUNDING: 3,
        E.OrderStatus.REFUNDED: 3,
        E.OrderStatus.DISPUTING: 3,
    }
    return mapping.get(order.status, 0)


def format_appointment_time(dt: datetime | None) -> str:
    """预约时间展示（移动端约定格式）：M月D日 HH:mm。"""
    if not dt:
        return ""
    return f"{dt.month}月{dt.day}日 {dt:%H:%M}"


def parse_appointment_time(text: str) -> datetime | None:
    """预约时间解析：优先 ISO 8601；兼容移动端预设中文标签
    （今天/明天/后天 HH:mm、本周六/本周日 HH:mm）。无法识别返回 None。"""
    from datetime import timedelta

    text = text.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    now = datetime.now(UTC).replace(tzinfo=None)
    day_offset = {"今天": 0, "明天": 1, "后天": 2}
    for label, offset in day_offset.items():
        if text.startswith(label):
            return _with_time(now + timedelta(days=offset), text[len(label):])
    weekday_map = {"本周六": 5, "本周日": 6}
    for label, weekday in weekday_map.items():
        if text.startswith(label):
            delta = (weekday - now.weekday()) % 7 or 7
            return _with_time(now + timedelta(days=delta), text[len(label):])
    return None


def _with_time(day: datetime, time_part: str) -> datetime | None:
    import re

    match = re.search(r"(\d{1,2}):(\d{2})", time_part)
    if not match:
        return None
    return day.replace(hour=int(match.group(1)), minute=int(match.group(2)),
                       second=0, microsecond=0)


async def _party_brief(db: AsyncSession, user_id: int) -> dict:
    user = await db.get(User, user_id)
    return {
        "id": str(user_id),
        "name": user.nickname if user else "",
        "avatar": (user.avatar_key if user else "") or "avatar-person-1",
        "verified": bool(user and user.realname_status == "VERIFIED"),
        "credit": "信用极好" if (user and user.credit_score >= 90) else "信用良好",
    }


def _actions(order: Order, role: str, reviewed: bool) -> dict:
    """移动端 Order 动作位（mobile/models/order.model.ts）。"""
    s = order.status
    monetary = order.trade_type == E.TradeType.MONETARY
    return {
        "canPay": monetary and s == E.OrderStatus.PENDING_PAYMENT and role == "buyer",
        "canConfirmApplication": (
            not monetary and s in (E.OrderStatus.APPLIED, E.OrderStatus.PENDING_CONFIRM)
            and role == "seller"),
        "canCompleteTrade": s == E.OrderStatus.PENDING_RELEASE and role == "seller",
        "canAppointment": s in (E.OrderStatus.ESCROWED, E.OrderStatus.CONFIRMED,
                                E.OrderStatus.APPOINTMENT),
        "canInspect": s in (E.OrderStatus.APPOINTMENT, E.OrderStatus.INSPECTING),
        "canReview": s == E.OrderStatus.COMPLETED and not reviewed,
        "canCancel": (s == E.OrderStatus.PENDING_PAYMENT and role == "buyer") or (
            not monetary and s in (E.OrderStatus.APPLIED, E.OrderStatus.PENDING_CONFIRM,
                                   E.OrderStatus.CONFIRMED, E.OrderStatus.APPOINTMENT)),
        "canDispute": s not in (*E.OrderStatus.TERMINAL, E.OrderStatus.DISPUTING),
        "reviewable": s == E.OrderStatus.COMPLETED and not reviewed,
    }


async def serialize_order(db: AsyncSession, order: Order, viewer: User, *,
                          detail: bool = False) -> dict:
    role = "buyer" if viewer.id == order.buyer_id else "seller"
    item = await db.get(Item, order.item_id)
    item_card = await item_svc.serialize_item(db, item, viewer) if item else {}

    reviewed = bool(await db.scalar(
        select(Review.id).where(Review.order_id == order.id,
                                Review.reviewer_id == viewer.id).limit(1)))
    data = {
        "id": str(order.id),
        "orderNo": order.order_no,
        "tradeType": item_svc.TRADE_LABEL[order.trade_type],
        "tradeTypeCode": order.trade_type,
        "status": order.status,
        "statusText": STATUS_TEXT[order.status],
        "escrowStatus": order.escrow_status,
        "amount": order.amount_cents / 100,
        "item": item_card,
        "offeredItems": order.offered_items or [],
        "buyer": await _party_brief(db, order.buyer_id),
        "seller": await _party_brief(db, order.seller_id),
        "role": role,
        "createdAt": int(order.created_at.timestamp() * 1000) if order.created_at else 0,
        "createdAtText": _time_ago(order.created_at),
        "progressText": STATUS_TEXT[order.status],
        "appointment": {
            "time": format_appointment_time(order.appointment_at),
            "timeIso": order.appointment_at.isoformat() if order.appointment_at else "",
            "place": order.appointment_place,
            "note": order.appointment_note,
            "status": order.appointment_status,
        } if order.appointment_status != "NONE" else None,
        "payDeadlineAt": int(order.pay_deadline_at.timestamp() * 1000) if order.pay_deadline_at else 0,
        **_actions(order, role, reviewed),
    }
    if detail:
        events = await events_of(db, order.id)
        event_by_key = {event.event: event for event in events}
        steps = MONETARY_STEPS if order.trade_type == E.TradeType.MONETARY else OTHER_STEPS
        rank = _step_rank(order)
        event_keys = (["CREATED", "PAID", "APPOINTED", "INSPECTING", "RELEASED", "COMPLETED"]
                      if order.trade_type == E.TradeType.MONETARY else
                      ["CREATED", "CONFIRMED", "APPOINTED", "INSPECTING", "COMPLETED"])
        timeline = []
        for index, (key, title) in enumerate(zip(event_keys, steps, strict=False)):
            event = event_by_key.get(key)
            timeline.append({
                "key": key.lower(),
                "title": title,
                "time": _time_ago(event.created_at) if event else "",
                "done": index < rank or (order.status == E.OrderStatus.COMPLETED),
                "active": index == rank and order.status not in E.OrderStatus.TERMINAL,
            })
        data["timeline"] = timeline
        data["events"] = [
            {"event": event.event, "note": event.note, "actorType": event.actor_type,
             "time": _time_ago(event.created_at)} for event in events
        ]
    return data


def admin_status_label(order: Order) -> dict:
    return {"status": order.status, "escrowStatus": order.escrow_status,
            "statusText": STATUS_TEXT[order.status]}
