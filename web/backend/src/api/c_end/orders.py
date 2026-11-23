from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from src.api.utils import paginate
from src.core.deps import CurrentUser, DbSession
from src.core.idempotency import complete_idempotency, guard_idempotency
from src.core.responses import (
    ERR_BIZ_RULE,
    ERR_CONFLICT,
    ERR_NOT_VERIFIED,
    ERR_PARAM,
    ApiError,
    ok,
    paginated,
)
from src.db.models import CreditLog, Dispute, Item, Order, Review, User
from src.db.models.common import utcnow
from src.domain import enums as E
from src.domain.state import order_sm
from src.services import order_service as svc
from src.services import pay_service
from src.services.notify_service import notify_user

router = APIRouter(tags=["c:orders"])


class CreateOrderIn(BaseModel):
    itemId: int
    offeredItemIds: list[int] = []
    note: str = ""


class AppointmentIn(BaseModel):
    time: str  # ISO 8601 时间串（接入时移动端映射为时间选择器）
    place: str
    note: str = ""


class InspectIn(BaseModel):
    satisfied: bool
    reason: str = ""


class DisputeIn(BaseModel):
    reason: str
    description: str = ""
    images: list[str] = []


class ReviewIn(BaseModel):
    rating: int
    tags: list[str] = []
    content: str = ""
    anonymous: bool = False


def _order_no(order_id: int) -> str:
    return f"NI{utcnow():%Y%m%d}{order_id:06d}"


# ---------------------------------------------------------------- 创建订单（M06-01/BR-08/BR-12/BR-13）

@router.post("/orders")
async def create_order(payload: CreateOrderIn, request: Request,
                       user: CurrentUser, db: DbSession):
    """按物品交易方式创建订单：货币 → 待付款（30min 未付自动取消）；赠与/互换 → 待卖家确认。
    创建即锁定物品为 RESERVED（BR-08）；互换双方物品须已过 AI 质检上架（BR-13）。"""
    idem = await guard_idempotency(db, request, payload.model_dump())
    if idem and idem.status == "COMPLETED":
        return ok(idem.response_json["data"])

    item = await svc.lock_item_for_order(db, payload.itemId)
    if item.seller_id == user.id:
        raise ApiError(ERR_BIZ_RULE, "不能购买自己发布的物品", 422)
    # 免费领取需实名（运营要求）：实名信息用于线下当面领取时的身份核验。
    if item.trade_type == E.TradeType.FREE_GIFT and user.realname_status != "VERIFIED":
        raise ApiError(ERR_NOT_VERIFIED, "免费领取需先完成实名认证", 403)

    offered_snapshot: list[dict] = []
    if item.trade_type == E.TradeType.BARTER:
        if not payload.offeredItemIds:
            raise ApiError(ERR_PARAM, "互换必须提交用于交换的物品（BR-13）", 400)
        from src.domain.state import item_sm

        for offered_id in payload.offeredItemIds[:3]:
            offered = await db.get(Item, offered_id)
            if not offered or offered.seller_id != user.id:
                raise ApiError(ERR_PARAM, "交换物品必须是你自己在架的物品", 400)
            if offered.status != E.ItemStatus.ON_SALE:
                raise ApiError(ERR_CONFLICT, f"交换物品「{offered.title}」已被占用或不在架（BR-13）", 409)
            # 互换双方物品一并锁定，任一方被占用则整单不可约（BR-13）
            offered.status = item_sm.fire(offered.status, E.ItemStatus.RESERVED)
            offered_snapshot.append({
                "item_id": offered.id, "title": offered.title,
                "condition": offered.condition,
                "image": "",
            })

    now = utcnow()
    order = Order(
        order_no="PENDING",
        item_id=item.id,
        buyer_id=user.id,
        seller_id=item.seller_id,
        community_id=item.community_id,
        trade_type=item.trade_type,
        amount_cents=item.price_cents if item.trade_type == E.TradeType.MONETARY else 0,
        offered_items=offered_snapshot,
        note=payload.note,
        status=(E.OrderStatus.PENDING_PAYMENT if item.trade_type == E.TradeType.MONETARY
                else E.OrderStatus.PENDING_CONFIRM),
        escrow_status=E.EscrowStatus.UNPAID,
        appointment_status="NONE",
        pay_deadline_at=(now + timedelta(minutes=30)
                         if item.trade_type == E.TradeType.MONETARY else None),
        confirm_deadline_at=(now + timedelta(hours=48)
                             if item.trade_type != E.TradeType.MONETARY else None),
    )
    db.add(order)
    await db.flush()
    order.order_no = _order_no(order.id)
    await svc.add_event(db, order, "CREATED", actor_type="BUYER", actor_id=user.id,
                        note=f"创建{item_svc_label(order.trade_type)}订单")

    seller_notice = ("买家已下单，等待支付" if item.trade_type == E.TradeType.MONETARY
                     else "收到新的领取/互换申请，请在 48 小时内确认")
    await notify_user(db, item.seller_id, category="TRADE", title=seller_notice,
                      description=f"物品「{item.title}」", icon="order", tag="订单",
                      route={"type": "order", "id": str(order.id)})

    data = {
        "orderId": str(order.id),
        "orderNo": order.order_no,
        "amount": order.amount_cents / 100,
        "expireAt": int(order.pay_deadline_at.timestamp() * 1000) if order.pay_deadline_at else 0,
    }
    await complete_idempotency(db, idem, data)
    await db.commit()
    return ok(data, "订单已创建")


def item_svc_label(trade_type: str) -> str:
    return {"MONETARY": "担保支付", "FREE_GIFT": "免费赠与", "BARTER": "物品互换"}[trade_type]


# ---------------------------------------------------------------- 查询（M06-09）

@router.get("/orders")
async def list_orders(
    user: CurrentUser, db: DbSession,
    type: str | None = Query(default=None),
    role: str | None = Query(default=None),
    page: int = Query(default=1), pageSize: int = Query(default=20),
):
    stmt = select(Order)
    if role == "seller":
        stmt = stmt.where(Order.seller_id == user.id)
    else:
        stmt = stmt.where(Order.buyer_id == user.id)
    if type in E.TradeType.ALL:
        stmt = stmt.where(Order.trade_type == type)
    rows, total = await paginate(db, stmt.order_by(Order.id.desc()), page, pageSize)
    return paginated([await svc.serialize_order(db, order, user) for order in rows],
                     page, pageSize, total)


@router.get("/orders/{order_id}")
async def order_detail(order_id: int, user: CurrentUser, db: DbSession):
    order = await svc.get_order_or_404(db, order_id)
    svc.assert_participant(order, user)
    return ok(await svc.serialize_order(db, order, user, detail=True))


# ---------------------------------------------------------------- 预约验货（M06-01/02）

@router.post("/orders/{order_id}/appointment")
async def set_appointment(order_id: int, payload: AppointmentIn,
                          user: CurrentUser, db: DbSession):
    """预约/改期：双方均可发起；48h 未响应自动取消（赠与/互换，M06-02）。"""
    order = await svc.get_order_or_404(db, order_id)
    svc.assert_participant(order, user)
    if order.status not in (E.OrderStatus.ESCROWED, E.OrderStatus.CONFIRMED,
                            E.OrderStatus.APPOINTMENT):
        raise ApiError(ERR_BIZ_RULE, "当前状态不可预约", 422)
    appointment_at = svc.parse_appointment_time(payload.time)
    if appointment_at is None:
        raise ApiError(ERR_PARAM, "预约时间无法识别（支持 ISO 或「明天 14:00」等预设）", 400)

    order.appointment_at = appointment_at
    order.appointment_place = payload.place[:64]
    order.appointment_note = payload.note[:200]
    order.appointment_status = "CONFIRMED"
    if order.status != E.OrderStatus.APPOINTMENT:
        order.status = order_sm.fire(order.status, E.OrderStatus.APPOINTMENT)
    await svc.add_event(db, order, "APPOINTED",
                        actor_type="BUYER" if user.id == order.buyer_id else "SELLER",
                        actor_id=user.id, note=f"{payload.place} · {payload.time}")

    peer_id = order.seller_id if user.id == order.buyer_id else order.buyer_id
    await notify_user(db, peer_id, category="TRADE", title="验货预约已确认",
                      description=f"{payload.time} · {payload.place}",
                      icon="calendar", tag="预约", route={"type": "order", "id": str(order.id)})
    await db.commit()
    return ok(await svc.serialize_order(db, order, user, detail=True))


# ---------------------------------------------------------------- 赠与/互换确认（M06-07/08）

@router.post("/orders/{order_id}/confirm-application")
async def confirm_application(order_id: int, user: CurrentUser, db: DbSession):
    """卖家确认赠与/互换申请（48h 超时自动取消，M06-02）。"""
    order = await svc.get_order_or_404(db, order_id)
    svc.assert_participant(order, user)
    if user.id != order.seller_id:
        raise ApiError(ERR_BIZ_RULE, "仅卖家可确认申请", 422)
    if order.trade_type == E.TradeType.MONETARY:
        raise ApiError(ERR_BIZ_RULE, "货币订单无需确认申请", 422)
    order.status = order_sm.fire(order.status, E.OrderStatus.CONFIRMED)
    await svc.add_event(db, order, "CONFIRMED", actor_type="SELLER", actor_id=user.id,
                        note="卖家确认申请")
    await notify_user(db, order.buyer_id, category="TRADE", title="申请已通过",
                      description="卖家已确认，快预约见面验货吧",
                      icon="check", tag="订单", route={"type": "order", "id": str(order.id)})
    await db.commit()
    return ok(await svc.serialize_order(db, order, user, detail=True))


# ---------------------------------------------------------------- 验货确认（M06-04/BR-11）

@router.post("/orders/{order_id}/confirm")
async def confirm_inspection(order_id: int, payload: InspectIn,
                             user: CurrentUser, db: DbSession):
    """双方当面验货后各自确认：双方满意 → 放款/交割；任一方不满意（必选原因）→ 退款/取消。
    资金操作不做乐观更新（移动端详设 9.2.3），以服务端账本为准。"""
    order = await svc.get_order_or_404(db, order_id)
    svc.assert_participant(order, user)
    role = "buyer" if user.id == order.buyer_id else "seller"
    if order.status not in (E.OrderStatus.APPOINTMENT, E.OrderStatus.INSPECTING):
        raise ApiError(ERR_BIZ_RULE, "当前状态不可验货确认", 422)

    if order.status == E.OrderStatus.APPOINTMENT:
        order.status = order_sm.fire(order.status, E.OrderStatus.INSPECTING)

    actor_type = "BUYER" if role == "buyer" else "SELLER"
    monetary = order.trade_type == E.TradeType.MONETARY

    if not payload.satisfied:
        if len(payload.reason.strip()) < 2:
            raise ApiError(ERR_PARAM, "不满意必须选择或填写原因（M06-04）", 400)
        await svc.add_event(db, order, "INSPECT_REJECTED", actor_type=actor_type,
                            actor_id=user.id, note=payload.reason)
        if monetary:
            order.status = order_sm.fire(order.status, E.OrderStatus.REFUNDING)
            order.escrow_status = E.EscrowStatus.REFUNDING
            await pay_service.refund_to_buyer(db, order, reason=f"验货不满意：{payload.reason}")
            order.status = order_sm.fire(order.status, E.OrderStatus.REFUNDED)
            order.escrow_status = E.EscrowStatus.REFUNDED
            await svc.add_event(db, order, "REFUNDED", note="货款已原路退回")
        else:
            order.status = order_sm.fire(order.status, E.OrderStatus.CANCELLED)
        await svc.unlock_item(db, order.item_id)
        await svc.unlock_swap_items(db, order)
        peer_id = order.seller_id if role == "buyer" else order.buyer_id
        await notify_user(db, peer_id, category="TRADE",
                          title="验货未成交" if not monetary else "退款已原路退回",
                          description=payload.reason, icon="alert", tag="验货",
                          route={"type": "order", "id": str(order.id)})
        await db.commit()
        return ok(await svc.serialize_order(db, order, user, detail=True))

    # 满意确认：记录双方确认；双方均确认后进入放款/交割。
    # BR-11：任一方确认后超时（默认 72h）未完成操作 → 系统自动放款（workers/timeout_tasks）。
    await svc.add_event(db, order, "INSPECT_SATISFIED", actor_type=actor_type,
                        actor_id=user.id, note="验货满意")
    if monetary and order.release_deadline_at is None:
        from src.core.config import settings

        order.release_deadline_at = utcnow() + timedelta(hours=settings.auto_release_hours)
    events = await svc.events_of(db, order.id)
    confirmed_roles = {event.actor_type for event in events
                       if event.event == "INSPECT_SATISFIED"}
    if not ({"BUYER", "SELLER"} <= confirmed_roles):
        await db.commit()
        return ok(await svc.serialize_order(db, order, user, detail=True),
                  "已确认，等待对方验货")

    if monetary:
        order.status = order_sm.fire(order.status, E.OrderStatus.PENDING_RELEASE)
        order.escrow_status = E.EscrowStatus.PENDING_RELEASE
        await pay_service.release_to_seller(db, order)
        order.escrow_status = E.EscrowStatus.RELEASED
        await svc.add_event(db, order, "RELEASED", note="平台已放款至卖家钱包")
        await _complete_order(db, order, final_status=E.ItemStatus.SOLD)
    else:
        final = (E.ItemStatus.GIFTED if order.trade_type == E.TradeType.FREE_GIFT
                 else E.ItemStatus.SOLD)
        await _complete_order(db, order, final_status=final)

    peer_id = order.seller_id if role == "buyer" else order.buyer_id
    await notify_user(db, peer_id, category="TRADE", title="交易完成，来互评吧",
                      description="双方已确认成交", icon="star", tag="成交",
                      route={"type": "order", "id": str(order.id)})
    if monetary:
        await notify_user(db, order.seller_id, category="TRADE",
                          title=f"货款 ¥{order.amount_cents / 100:g} 已到账",
                          description="可在钱包申请提现", icon="wallet", tag="放款",
                          route={"type": "order", "id": str(order.id)})
    await db.commit()
    return ok(await svc.serialize_order(db, order, user, detail=True))


async def _complete_order(db: DbSession, order: Order, final_status: str) -> None:
    order.status = order_sm.fire(order.status, E.OrderStatus.COMPLETED)
    order.completed_at = utcnow()
    await svc.add_event(db, order, "COMPLETED", note="交易完成")
    await svc.unlock_item(db, order.item_id, final=final_status)
    await svc.unlock_swap_items(db, order, final=final_status)


# ---------------------------------------------------------------- 取消（M06-02/03）

@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: int, user: CurrentUser, db: DbSession):
    order = await svc.get_order_or_404(db, order_id)
    svc.assert_participant(order, user)
    monetary = order.trade_type == E.TradeType.MONETARY
    if monetary and order.status != E.OrderStatus.PENDING_PAYMENT:
        raise ApiError(ERR_BIZ_RULE, "已托管订单不可直接取消，请申请退款或发起纠纷", 422)
    order.status = order_sm.fire(order.status, E.OrderStatus.CANCELLED)
    order.cancel_reason = "用户主动取消"
    await svc.add_event(db, order, "CANCELLED",
                        actor_type="BUYER" if user.id == order.buyer_id else "SELLER",
                        actor_id=user.id, note="用户主动取消")
    await svc.unlock_item(db, order.item_id)
    await svc.unlock_swap_items(db, order)
    await db.commit()
    return ok(await svc.serialize_order(db, order, user, detail=True))


# ---------------------------------------------------------------- 纠纷（M06-11 → W05-02）

@router.post("/orders/{order_id}/dispute")
async def submit_dispute(order_id: int, payload: DisputeIn,
                         user: CurrentUser, db: DbSession):
    """发起纠纷：描述 + 证据（≤9 张）；订单转纠纷中，托管资金冻结（W05-02）。"""
    order = await svc.get_order_or_404(db, order_id)
    svc.assert_participant(order, user)
    if order.status in E.OrderStatus.TERMINAL:
        raise ApiError(ERR_BIZ_RULE, "订单已结束，无法发起纠纷", 422)
    if len(payload.images) > 9:
        raise ApiError(ERR_PARAM, "证据照片最多 9 张", 400)
    if len(payload.reason.strip()) < 5:
        raise ApiError(ERR_PARAM, "请描述纠纷原因（至少 5 个字）", 400)

    order.status = order_sm.fire(order.status, E.OrderStatus.DISPUTING)
    if order.trade_type == E.TradeType.MONETARY:
        order.escrow_status = E.EscrowStatus.FROZEN
    respondent_id = order.seller_id if user.id == order.buyer_id else order.buyer_id
    dispute = Dispute(
        dispute_no=f"DP{utcnow():%Y%m%d}{order.id:06d}",
        order_id=order.id,
        community_id=order.community_id,
        initiator_id=user.id,
        respondent_id=respondent_id,
        amount_cents=order.amount_cents,
        status=E.DisputeStatus.OPEN,
        statement=f"{payload.reason}\n{payload.description}".strip(),
    )
    db.add(dispute)
    await db.flush()
    from src.db.models import DisputeEvidence

    for index, key in enumerate(payload.images):
        db.add(DisputeEvidence(dispute_id=dispute.id, uploader_id=user.id,
                               object_key=key, description=f"证据 {index + 1}"))
    await svc.add_event(db, order, "DISPUTED",
                        actor_type="BUYER" if user.id == order.buyer_id else "SELLER",
                        actor_id=user.id, note=payload.reason)
    await notify_user(db, respondent_id, category="TRADE", title="对方发起了纠纷申请",
                      description=payload.reason, icon="gavel", tag="纠纷",
                      route={"type": "order", "id": str(order.id)})
    await db.commit()
    return ok({"success": True, "disputeId": str(dispute.id),
               "order": await svc.serialize_order(db, order, user, detail=True)})


# ---------------------------------------------------------------- 互评（M06-10/信用）

@router.post("/orders/{order_id}/reviews")
async def submit_review(order_id: int, payload: ReviewIn,
                        user: CurrentUser, db: DbSession):
    """仅真实交易双方可互评；赠与交易同样计入信用（BR-12）；评价计入信用流水。"""
    order = await svc.get_order_or_404(db, order_id)
    svc.assert_participant(order, user)
    if order.status != E.OrderStatus.COMPLETED:
        raise ApiError(ERR_BIZ_RULE, "交易完成后才能评价", 422)
    if not (1 <= payload.rating <= 5):
        raise ApiError(ERR_PARAM, "评分需为 1–5 星", 400)
    if await db.scalar(select(Review.id).where(
            Review.order_id == order.id, Review.reviewer_id == user.id).limit(1)):
        raise ApiError(ERR_CONFLICT, "已评价过该订单", 409)

    reviewee_id = order.seller_id if user.id == order.buyer_id else order.buyer_id
    direction = "BUYER_TO_SELLER" if user.id == order.buyer_id else "SELLER_TO_BUYER"
    review = Review(order_id=order.id, reviewer_id=user.id, reviewee_id=reviewee_id,
                    rating=payload.rating, tags=payload.tags[:6],
                    content=payload.content[:500], anonymous=payload.anonymous,
                    direction=direction)
    db.add(review)

    # 信用流水（M07-08/W05-04）：评分映射分值变动
    delta = {5: 2, 4: 1, 3: 0}.get(payload.rating, -2)
    reviewee = await db.get(User, reviewee_id)
    if reviewee and delta != 0:
        reviewee.credit_score = max(0, min(1000, reviewee.credit_score + delta))
        db.add(CreditLog(user_id=reviewee_id, delta=delta, event_type="REVIEW",
                         ref_type="order", ref_id=order.id,
                         balance_after=reviewee.credit_score,
                         note=f"交易互评 {payload.rating} 星"))
    await db.commit()
    return ok({"success": True, "rating": payload.rating}, "评价成功，信用已累积")
