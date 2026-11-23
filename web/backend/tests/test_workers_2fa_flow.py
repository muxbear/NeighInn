"""Phase 3 测试：时间驱动业务规则（M06-02/03、BR-07/11）、Outbox 继电器、2FA 完整流程。"""

from datetime import timedelta

import pyotp
import pytest
from sqlalchemy import func, select

from src.core.config import settings
from src.db.models import AppNotification, Item, Order, OutboxEvent, WalletAccount
from src.db.models.common import utcnow
from src.workers.outbox_relay import relay_once
from src.workers.timeout_tasks import run_timeouts
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_headers,
    admin_login,
    bearer,
    create_on_sale_item,
    create_order,
    make_appointment,
    pay_order,
    register_user,
    verified_user,
)


async def _seller_and_item(client, phone, **overrides):
    seller = await verified_user(client, phone)
    await admin_login(client)
    item_id = await create_on_sale_item(client, admin_headers(client), seller["token"], **overrides)
    return seller, item_id


@pytest.mark.asyncio
async def test_unpaid_order_auto_cancelled(client, db_session):
    """M06-03：超过支付时限（30min）自动取消并解锁物品。"""
    _seller, item_id = await _seller_and_item(client, "13966660001")
    buyer = await register_user(client, "13966660002")
    order = await create_order(client, buyer["token"], item_id)

    db_session.expire_all()
    row = await db_session.get(Order, int(order["orderId"]))
    row.pay_deadline_at = utcnow() - timedelta(minutes=1)
    await db_session.commit()

    stats = await run_timeouts(db_session)
    assert stats["cancelledUnpaid"] >= 1

    await db_session.refresh(row)
    assert row.status == "CANCELLED"
    item = await db_session.get(Item, int(item_id))
    assert item.status == "ON_SALE"
    notes = (await db_session.execute(
        select(func.count()).select_from(AppNotification)
        .where(AppNotification.user_id == int(buyer["profile"]["id"])))).scalar()
    assert notes >= 1


@pytest.mark.asyncio
async def test_stale_gift_application_cancelled(client, db_session):
    """M06-02：赠与/互换申请 48h 未确认自动取消并解锁。"""
    _seller, item_id = await _seller_and_item(
        client, "13966660003", title="儿童绘本 30 册", tradeType="FREE_GIFT", priceCents=0)
    buyer = await verified_user(client, "13966660004")
    order = await create_order(client, buyer["token"], item_id)

    db_session.expire_all()
    row = await db_session.get(Order, int(order["orderId"]))
    row.confirm_deadline_at = utcnow() - timedelta(hours=1)
    await db_session.commit()

    stats = await run_timeouts(db_session)
    assert stats["cancelledStale"] >= 1
    await db_session.refresh(row)
    assert row.status == "CANCELLED"
    item = await db_session.get(Item, int(item_id))
    assert item.status == "ON_SALE"


@pytest.mark.asyncio
async def test_auto_release_after_buyer_confirmation(client, db_session):
    """BR-11：买家验货确认后 72h 超时自动放款（无需卖家操作）。"""
    seller, item_id = await _seller_and_item(client, "13966660005")
    buyer = await register_user(client, "13966660006")
    order = await create_order(client, buyer["token"], item_id)
    order_id = order["orderId"]
    await pay_order(client, buyer["token"], order_id)
    await make_appointment(client, buyer["token"], order_id)

    # 仅买家确认满意 → 订单进入验货中并写入自动放款截止
    resp = await client.post(f"{C_BASE}/orders/{order_id}/confirm",
                             json={"satisfied": True}, headers=bearer(buyer["token"]))
    assert resp.status_code == 200

    db_session.expire_all()
    row = await db_session.get(Order, int(order_id))
    assert row.release_deadline_at is not None  # 截止时间已写入
    row.release_deadline_at = utcnow() - timedelta(minutes=1)
    await db_session.commit()

    stats = await run_timeouts(db_session)
    assert stats["autoReleased"] >= 1

    await db_session.refresh(row)
    assert row.status == "COMPLETED"
    assert row.escrow_status == "RELEASED"
    wallet = await db_session.scalar(
        select(WalletAccount).where(WalletAccount.user_id == int(seller["profile"]["id"])))
    assert wallet.balance_cents == 12800  # 自动放款到账
    item = await db_session.get(Item, int(item_id))
    assert item.status == "SOLD"


@pytest.mark.asyncio
async def test_expired_item_auto_off_shelf_and_renew(client, db_session):
    """BR-07：30 天到期自动下架（EXPIRED），可续期重新上架。"""
    seller, item_id = await _seller_and_item(client, "13966660007")
    db_session.expire_all()
    item = await db_session.get(Item, int(item_id))
    item.expires_at = utcnow() - timedelta(hours=1)
    await db_session.commit()

    stats = await run_timeouts(db_session)
    assert stats["expiredItems"] >= 1
    await db_session.refresh(item)
    assert item.status == "EXPIRED"

    renew = await client.post(f"{C_BASE}/items/{item_id}/renew",
                              headers=bearer(seller["token"]))
    assert renew.status_code == 200
    await db_session.refresh(item)
    assert item.status == "ON_SALE"


@pytest.mark.asyncio
async def test_outbox_relay_publishes_events(client, db_session):
    """Outbox 继电器：业务事件落库 → 轮询投递 → 标记 PUBLISHED（幂等二次为空）。"""
    await verified_user(client, "13966660008")  # 审核动作产生 outbox 事件

    db_session.expire_all()
    pending_before = int((await db_session.scalar(
        select(func.count()).select_from(OutboxEvent)
        .where(OutboxEvent.status == "PENDING"))) or 0)
    assert pending_before >= 1

    delivered = await relay_once(db_session)
    assert delivered >= 1
    pending_after = int((await db_session.scalar(
        select(func.count()).select_from(OutboxEvent)
        .where(OutboxEvent.status == "PENDING"))) or 0)
    assert pending_after == 0

    second = await relay_once(db_session)
    assert second == 0  # 幂等：无新事件


@pytest.mark.asyncio
async def test_2fa_bind_login_and_recovery_code(client, db_session, monkeypatch):
    """W01-01：2FA 绑定 → 登录强制动态码 → TOTP 通过 → 恢复码兜底（一次性）。"""
    monkeypatch.setattr(settings, "auth_require_2fa", True)
    csrf = await admin_login(client)

    bind = await client.post(f"{ADMIN_BASE}/auth/2fa/bind", headers=csrf)
    assert bind.status_code == 200, bind.text
    data = bind.json()["data"]
    secret = data["secret"]
    recovery = data["recoveryCodes"]
    assert len(recovery) == 8 and data["enabled"] is False

    # 未确认绑定前不强制 2FA
    await client.post(f"{ADMIN_BASE}/auth/logout", headers=csrf)
    login_plain = await client.post(f"{ADMIN_BASE}/auth/login",
                                    json={"username": "admin", "password": "Admin@2025"})
    assert "csrfToken" in login_plain.json()["data"]

    # 确认绑定：错误动态码拒绝
    bad = await client.post(f"{ADMIN_BASE}/auth/2fa/verify-bind",
                            json={"otp": "000000"}, headers=admin_headers(client))
    assert bad.status_code == 401
    totp = pyotp.TOTP(secret).now()
    ok_bind = await client.post(f"{ADMIN_BASE}/auth/2fa/verify-bind",
                                json={"otp": totp}, headers=admin_headers(client))
    assert ok_bind.status_code == 200
    assert ok_bind.json()["data"]["enabled"] is True

    # 启用后登录：缺动态码 → 挑战
    await client.post(f"{ADMIN_BASE}/auth/logout", headers=admin_headers(client))
    challenge = await client.post(f"{ADMIN_BASE}/auth/login",
                                  json={"username": "admin", "password": "Admin@2025"})
    assert challenge.json()["data"]["twoFactorRequired"] is True

    # 动态码登录成功
    login_ok = await client.post(f"{ADMIN_BASE}/auth/login",
                                 json={"username": "admin", "password": "Admin@2025",
                                       "otp": pyotp.TOTP(secret).now()})
    assert login_ok.status_code == 200
    assert "csrfToken" in login_ok.json()["data"]

    # 恢复码登录成功且一次性消费
    await client.post(f"{ADMIN_BASE}/auth/logout", headers=admin_headers(client))
    login_recovery = await client.post(f"{ADMIN_BASE}/auth/login",
                                       json={"username": "admin", "password": "Admin@2025",
                                             "otp": recovery[0]})
    assert login_recovery.status_code == 200

    await client.post(f"{ADMIN_BASE}/auth/logout", headers=admin_headers(client))
    reused = await client.post(f"{ADMIN_BASE}/auth/login",
                               json={"username": "admin", "password": "Admin@2025",
                                     "otp": recovery[0]})
    assert reused.status_code == 401  # 恢复码已消费
