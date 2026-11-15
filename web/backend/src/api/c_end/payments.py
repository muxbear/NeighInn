from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from src.core.config import settings
from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_BIZ_RULE, ERR_NOT_FOUND, ApiError, ok
from src.db.models import Order, PaymentTransaction
from src.domain import enums as E
from src.domain.state import order_sm
from src.services import order_service as svc
from src.services import pay_service
from src.services.notify_service import notify_user

router = APIRouter(tags=["c:payments"])


class PrepayIn(BaseModel):
    orderId: int
    method: str = "wechat"  # wechat / alipay（渠道可配置，M06-03）


@router.post("/payments/prepay")
async def prepay(payload: PrepayIn, user: CurrentUser, db: DbSession):
    """预支付下单（M06-03/BR-11）：返回拉起参数与过期时间；幂等防重复支付。"""
    order = await svc.get_order_or_404(db, payload.orderId)
    svc.assert_participant(order, user)
    if user.id != order.buyer_id:
        raise ApiError(ERR_BIZ_RULE, "仅买家可支付", 422)
    if order.trade_type != E.TradeType.MONETARY:
        raise ApiError(ERR_BIZ_RULE, "非货币订单无需支付", 422)
    if order.status != E.OrderStatus.PENDING_PAYMENT:
        raise ApiError(ERR_BIZ_RULE, "订单当前状态不可支付", 422)

    channel = "WECHAT" if payload.method == "wechat" else "ALIPAY"
    txn = await pay_service.create_payment_intent(db, order, channel)
    await db.commit()
    return ok({
        "orderNo": order.order_no,
        "orderId": str(order.id),
        "payParams": pay_service.build_pay_params(txn),
        "expireAt": int(order.pay_deadline_at.timestamp() * 1000) if order.pay_deadline_at else 0,
    })


@router.get("/payments/{order_no}/status")
async def payment_status(order_no: str, user: CurrentUser, db: DbSession):
    """支付状态查询（服务端查询通道，与回调双通道确认，移动端详设 9.2.1）。"""
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if not order:
        raise ApiError(ERR_NOT_FOUND, "订单不存在", 404)
    svc.assert_participant(order, user)
    txn = await db.scalar(
        select(PaymentTransaction)
        .where(PaymentTransaction.order_id == order.id, PaymentTransaction.type == "ESCROW")
        .order_by(PaymentTransaction.id.desc()).limit(1))
    if not txn:
        return ok({"status": "NOT_FOUND"})
    status_map = {"SUCCESS": "SUCCESS", "PROCESSING": "PROCESSING", "FAILED": "FAILED"}
    return ok({
        "status": status_map.get(txn.status, "PROCESSING"),
        "orderId": str(order.id),
        "orderStatus": order.status,
    })


@router.post("/payments/mock-callback")
async def mock_channel_callback(payload: dict, db: DbSession):
    """渠道回调（仅开发环境）：模拟持牌渠道异步通知，验签后入账（NF-13 双通道之回调通道）。
    生产由支付机构回调平台网关的 /webhooks/payments/{channel}。"""
    if settings.app_env != "dev":
        raise ApiError(ERR_NOT_FOUND, "Not Found", 404)
    txn_no = str(payload.get("txnNo", ""))
    sign = str(payload.get("sign", ""))
    txn = await pay_service.settle_payment_success(db, txn_no, sign)

    order = await svc.get_order_or_404(db, txn.order_id)
    if order.status == E.OrderStatus.PENDING_PAYMENT:
        order.status = order_sm.fire(order.status, E.OrderStatus.ESCROWED)
        order.escrow_status = E.EscrowStatus.ESCROWED
        order.pay_deadline_at = None
        await svc.add_event(db, order, "PAID", actor_type="BUYER",
                            actor_id=order.buyer_id, note="买家已支付，货款平台托管")
        await notify_user(db, order.seller_id, category="TRADE",
                          title="买家已付款，货款平台托管",
                          description="请尽快与买家预约线下验货",
                          icon="wallet", tag="托管", route={"type": "order", "id": str(order.id)})
    await db.commit()
    return ok({"status": "SUCCESS", "orderStatus": order.status})
