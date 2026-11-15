"""订单与资金域集成测试（M06 三种交易方式 + W05/W06 资金治理，对应 AC-05/AC-06/AC-08）。

覆盖：货币全链路（下单→托管→预约→双方验货→放款→互评→提现）、BR-08 一物一卖、
赠与/互换闭环、验货不满意退款、取消解锁、纠纷冻结与双人复核资金处置、提现双人复核。

注意：多次管理员登录会刷新会话 CSRF Cookie，因此所有管理员操作统一使用
最近一次 admin_login 返回的 headers（辅助函数已封装该顺序）。
"""

import pytest
from sqlalchemy import func, select

from src.core.security import hash_password
from src.db.models import (
    AdminUser,
    CreditLog,
    Dispute,
    Item,
    LedgerEntry,
    Order,
    WalletAccount,
)
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_login,
    bearer,
    both_confirm_satisfied,
    create_on_sale_item,
    create_order,
    make_appointment,
    pay_order,
    register_user,
    verified_user,
)

PHONE_SELLER = "13922220001"
PHONE_BUYER = "13922220002"


async def _seller_item(client, **overrides):
    """卖家认证 + 物品上架；返回 (seller, item_id, 最新管理端 CSRF)。"""
    seller = await verified_user(client, PHONE_SELLER)
    csrf = await admin_login(client)
    item_id = await create_on_sale_item(client, csrf, seller["token"], **overrides)
    return seller, item_id, csrf


async def _second_admin(db_session, client):
    """创建并登录第二位管理员（双人复核场景）。"""
    if not await db_session.scalar(select(AdminUser).where(AdminUser.username == "reviewer2")):
        db_session.add(AdminUser(username="reviewer2",
                                 password_hash=hash_password("Reviewer@2025"),
                                 real_name="复审员", status="ACTIVE", is_super_admin=True))
        await db_session.commit()
    return await admin_login(client, "reviewer2", "Reviewer@2025")


@pytest.mark.asyncio
async def test_monetary_full_flow(client, db_session):
    """AC-06 货币交易全链路：支付→托管→验货→放款→提现→互评→信用。"""
    seller, item_id, _csrf = await _seller_item(client)
    buyer = await register_user(client, PHONE_BUYER)

    # 下单：物品锁定 RESERVED（BR-08）
    order_data = await create_order(client, buyer["token"], item_id)
    order_id = order_data["orderId"]
    assert order_data["expireAt"] > 0  # 30 分钟支付倒计时（M06-03）
    item = await db_session.get(Item, int(item_id))
    assert item.status == "RESERVED"

    # BR-08：同一物品第二个订单被拒（40901）
    rival = await register_user(client, "13922220003")
    conflict = await client.post(f"{C_BASE}/orders", json={"itemId": int(item_id)},
                                 headers=bearer(rival["token"]))
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 40901

    # 验签失败的回调被拒绝（NF-13）
    bad = await client.post(f"{C_BASE}/payments/mock-callback",
                            json={"txnNo": "TXfake", "sign": "bad-sign"})
    assert bad.status_code in (400, 404)

    # 支付 → 托管
    result = await pay_order(client, buyer["token"], order_id)
    assert result["orderStatus"] == "ESCROWED"
    escrow_balance = int((await db_session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
        .where(LedgerEntry.account == "PLATFORM_ESCROW",
               LedgerEntry.direction == "CREDIT"))).scalar() or 0)
    assert escrow_balance == 12800  # 托管户全额入账（隔离存管）

    # 支付状态双通道查询
    status = (await client.get(f"{C_BASE}/payments/{order_data['orderNo']}/status",
                               headers=bearer(buyer["token"]))).json()["data"]
    assert status["status"] == "SUCCESS"

    # 预约 → 双方验货满意 → 放款
    await make_appointment(client, buyer["token"], order_id)
    detail = await both_confirm_satisfied(client, buyer["token"], seller["token"], order_id)
    assert detail["status"] == "COMPLETED"
    assert detail["escrowStatus"] == "RELEASED"
    assert any(step["title"] == "平台放款" and step["done"] for step in detail["timeline"])

    # 物品终态已售出；卖家钱包到账（BR-11/M06-05）
    await db_session.refresh(item)
    assert item.status == "SOLD"
    seller_wallet = await db_session.scalar(
        select(WalletAccount).where(WalletAccount.user_id == int(seller["profile"]["id"])))
    assert seller_wallet.balance_cents == 12800
    assert seller_wallet.withdrawable_cents == 12800

    wallet = (await client.get(f"{C_BASE}/wallet", headers=bearer(seller["token"]))).json()["data"]
    assert wallet["balance"] == 128.0 and wallet["withdrawable"] == 128.0

    # 互评：仅真实交易双方可评；信用流水（M06-10/M07-08）
    review = await client.post(f"{C_BASE}/orders/{order_id}/reviews",
                               json={"rating": 5, "tags": ["描述相符", "守时"]},
                               headers=bearer(buyer["token"]))
    assert review.status_code == 200
    credit_log = await db_session.scalar(
        select(CreditLog).where(CreditLog.user_id == int(seller["profile"]["id"])))
    assert credit_log is not None and credit_log.delta == 2

    outsider = await register_user(client, "13922220004")
    bad_review = await client.post(f"{C_BASE}/orders/{order_id}/reviews",
                                   json={"rating": 1}, headers=bearer(outsider["token"]))
    assert bad_review.status_code == 403

    # 管理端订单快照（W05-01）与看板
    admin_orders = await client.get(f"{ADMIN_BASE}/finance/orders",
                                    params={"keyword": order_data["orderNo"]})
    row = admin_orders.json()["data"]["items"][0]
    assert row["escrowStatus"] == "RELEASED" and row["amountCents"] == 12800

    snapshot = (await client.get(f"{ADMIN_BASE}/finance/orders/{order_id}")).json()["data"]
    assert snapshot["payments"], "应含托管支付记录"
    assert any(event["event"] == "RELEASED" for event in snapshot["events"])

    overview = (await client.get(f"{ADMIN_BASE}/finance/overview")).json()["data"]
    assert overview["structure"]["escrow"] == 0  # 已全额放款


@pytest.mark.asyncio
async def test_gift_flow(client, db_session):
    """AC-06 赠与：申请→卖家确认→预约→交割闭环；不计入托管（BR-12）。"""
    seller, item_id, _csrf = await _seller_item(
        client, title="儿童绘本 30 册", tradeType="FREE_GIFT", priceCents=0)
    buyer = await register_user(client, PHONE_BUYER)

    order_data = await create_order(client, buyer["token"], item_id)
    order_id = order_data["orderId"]
    assert order_data["amount"] == 0

    detail = (await client.get(f"{C_BASE}/orders/{order_id}",
                               headers=bearer(buyer["token"]))).json()["data"]
    assert detail["status"] == "PENDING_CONFIRM"
    assert detail["canCancel"] is True

    confirm = await client.post(f"{C_BASE}/orders/{order_id}/confirm-application",
                                headers=bearer(seller["token"]))
    assert confirm.status_code == 200
    assert confirm.json()["data"]["status"] == "CONFIRMED"

    await make_appointment(client, buyer["token"], order_id)
    detail = await both_confirm_satisfied(client, buyer["token"], seller["token"], order_id)
    assert detail["status"] == "COMPLETED"

    item = await db_session.get(Item, int(item_id))
    assert item.status == "GIFTED"  # 已赠出（SRS 4.3）
    ledger_count = int((await db_session.execute(
        select(func.count()).select_from(LedgerEntry))).scalar() or 0)
    assert ledger_count == 0  # 赠与不产生资金账本（BR-12 单独计件）


@pytest.mark.asyncio
async def test_swap_flow(client, db_session):
    """AC-06 互换：双方物品须过质检上架（BR-13），交割后双方物品均转已售出。"""
    seller, swap_item_id, _ = await _seller_item(
        client, title="露营折叠椅两把", tradeType="BARTER",
        barterExpect="希望换儿童绘本或婴儿推车")
    buyer = await verified_user(client, PHONE_BUYER)
    csrf = await admin_login(client)
    offered_id = await create_on_sale_item(client, csrf, buyer["token"],
                                           title="儿童绘本全套", tradeType="FREE_GIFT",
                                           priceCents=0)

    # 交换物品必须属于买家且在架（BR-13）
    bad = await client.post(f"{C_BASE}/orders",
                            json={"itemId": int(swap_item_id),
                                  "offeredItemIds": [int(swap_item_id)]},
                            headers=bearer(buyer["token"]))
    assert bad.status_code == 400

    order_data = await create_order(client, buyer["token"], swap_item_id,
                                    offeredItemIds=[int(offered_id)])
    order_id = order_data["orderId"]
    offered = await db_session.get(Item, int(offered_id))
    assert offered.status == "RESERVED"  # 双方物品均锁定

    await client.post(f"{C_BASE}/orders/{order_id}/confirm-application",
                      headers=bearer(seller["token"]))
    await make_appointment(client, seller["token"], order_id)
    detail = await both_confirm_satisfied(client, buyer["token"], seller["token"], order_id)
    assert detail["status"] == "COMPLETED"

    await db_session.refresh(offered)
    swap_item = await db_session.get(Item, int(swap_item_id))
    assert offered.status == "SOLD" and swap_item.status == "SOLD"


@pytest.mark.asyncio
async def test_inspection_reject_triggers_refund(client, db_session):
    """AC-06 退款：验货不满意（必选原因）→ 托管原路退回（BR-11/M06-06）。"""
    _, item_id, _ = await _seller_item(client)
    buyer = await register_user(client, PHONE_BUYER)
    order_data = await create_order(client, buyer["token"], item_id)
    order_id = order_data["orderId"]
    await pay_order(client, buyer["token"], order_id)
    await make_appointment(client, buyer["token"], order_id)

    # 不满意原因必填（M06-04）
    no_reason = await client.post(f"{C_BASE}/orders/{order_id}/confirm",
                                  json={"satisfied": False}, headers=bearer(buyer["token"]))
    assert no_reason.status_code == 400

    detail = (await client.post(
        f"{C_BASE}/orders/{order_id}/confirm",
        json={"satisfied": False, "reason": "屏幕有划痕与描述不符"},
        headers=bearer(buyer["token"]))).json()["data"]
    assert detail["status"] == "REFUNDED"
    assert detail["escrowStatus"] == "REFUNDED"

    # 资金全链路平衡：托管户借=贷归零，物品回上架（M06-04）
    escrow = await db_session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
        .where(LedgerEntry.account == "PLATFORM_ESCROW",
               LedgerEntry.direction == "CREDIT"))
    escrow_out = await db_session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
        .where(LedgerEntry.account == "PLATFORM_ESCROW",
               LedgerEntry.direction == "DEBIT"))
    assert (escrow.scalar() or 0) == (escrow_out.scalar() or 0) == 12800
    item = await db_session.get(Item, int(item_id))
    assert item.status == "ON_SALE"


@pytest.mark.asyncio
async def test_cancel_unlocks_item(client, db_session):
    """M06-02：取消后物品解锁回上架；已托管订单不可直接取消。"""
    _, item_id, _ = await _seller_item(client)
    buyer = await register_user(client, PHONE_BUYER)

    order_data = await create_order(client, buyer["token"], item_id)
    cancel = await client.post(f"{C_BASE}/orders/{order_data['orderId']}/cancel",
                               headers=bearer(buyer["token"]))
    assert cancel.status_code == 200
    assert cancel.json()["data"]["status"] == "CANCELLED"
    item = await db_session.get(Item, int(item_id))
    assert item.status == "ON_SALE"

    # 已托管订单不可直接取消（需退款/纠纷）
    order2 = await create_order(client, buyer["token"], item_id)
    await pay_order(client, buyer["token"], order2["orderId"])
    bad = await client.post(f"{C_BASE}/orders/{order2['orderId']}/cancel",
                            headers=bearer(buyer["token"]))
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_dispute_dual_review_refund(client, db_session):
    """AC-08/W05-02/W06-04：纠纷冻结 → 资金类结论 → 双人复核 → 执行退款。"""
    _seller, item_id, csrf = await _seller_item(client)
    buyer = await register_user(client, PHONE_BUYER)
    order_data = await create_order(client, buyer["token"], item_id)
    order_id = order_data["orderId"]
    await pay_order(client, buyer["token"], order_id)
    await make_appointment(client, buyer["token"], order_id)

    # 证据最多 9 张
    too_many = await client.post(
        f"{C_BASE}/orders/{order_id}/dispute",
        json={"reason": "物品与描述严重不符", "images": [f"e{i}.jpg" for i in range(10)]},
        headers=bearer(buyer["token"]))
    assert too_many.status_code == 400

    resp = await client.post(
        f"{C_BASE}/orders/{order_id}/dispute",
        json={"reason": "物品与描述严重不符", "description": "实物存在功能故障",
              "images": ["disputes/ev1.jpg", "disputes/ev2.jpg"]},
        headers=bearer(buyer["token"]))
    assert resp.status_code == 200, resp.text
    dispute_id = resp.json()["data"]["disputeId"]
    detail = (await client.get(f"{C_BASE}/orders/{order_id}",
                               headers=bearer(buyer["token"]))).json()["data"]
    assert detail["status"] == "DISPUTING"
    assert detail["escrowStatus"] == "FROZEN"  # 托管资金真实冻结（M06-11）

    # 证据可查阅（私有桶签名 URL 降级返回 objectKey）
    evidences = (await client.get(f"{ADMIN_BASE}/disputes/{dispute_id}/evidences")).json()["data"]
    assert len(evidences) == 2

    # 调解记录
    med = await client.post(f"{ADMIN_BASE}/disputes/{dispute_id}/mediate",
                            json={"note": "已联系双方核实情况，建议原路退款"}, headers=csrf)
    assert med.status_code == 200

    # 资金类结论 → 进入双人复核（不立即执行）
    resolve = await client.post(
        f"{ADMIN_BASE}/disputes/{dispute_id}/resolve",
        json={"conclusionType": "CANCEL_REFUND",
              "conclusion": "核实物品确有问题，取消订单并全额退款"}, headers=csrf)
    assert resolve.status_code == 200, resolve.text
    data = resolve.json()["data"]
    assert data["dispute"]["status"] == "PENDING_REVIEW"
    adjustment_id = data["adjustment"]["id"]

    # 申请人不得复核自己的处置单（42203）
    self_review = await client.post(
        f"{ADMIN_BASE}/finance/adjustments/{adjustment_id}/review",
        json={"decision": "APPROVE"}, headers=csrf)
    assert self_review.status_code == 422
    assert self_review.json()["code"] == 42203

    # 第二位管理员复核 → 执行退款 → 纠纷结案
    csrf2 = await _second_admin(db_session, client)
    approved = await client.post(
        f"{ADMIN_BASE}/finance/adjustments/{adjustment_id}/review",
        json={"decision": "APPROVE"}, headers=csrf2)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "EXECUTED"

    dispute = await db_session.get(Dispute, int(dispute_id))
    assert dispute.status == "RESOLVED"
    order = await db_session.get(Order, int(order_id))
    assert order.status == "REFUNDED"
    assert order.escrow_status == "REFUNDED"


@pytest.mark.asyncio
async def test_withdrawal_dual_review_flow(client, db_session):
    """W06-03/04：小额单审到账；大额双人复核；复核人不同（42203）；驳回退回资金。"""
    seller, item_id, csrf = await _seller_item(client)
    buyer = await register_user(client, PHONE_BUYER)
    order_data = await create_order(client, buyer["token"], item_id)
    await pay_order(client, buyer["token"], order_data["orderId"])
    await make_appointment(client, buyer["token"], order_data["orderId"])
    await both_confirm_satisfied(client, buyer["token"], seller["token"], order_data["orderId"])

    # 超出可提现余额被拒
    too_much = await client.post(f"{C_BASE}/wallet/withdrawals",
                                 json={"amountCents": 99999900},
                                 headers=bearer(seller["token"]))
    assert too_much.status_code == 422

    # 小额提现（128 元 → 费率 0.1% → 手续费 13 分）单审到账
    small = await client.post(f"{C_BASE}/wallet/withdrawals",
                              json={"amountCents": 12800},
                              headers=bearer(seller["token"]))
    assert small.status_code == 200
    assert small.json()["data"]["needDualReview"] is False
    wd_small_id = (await client.get(
        f"{ADMIN_BASE}/finance/withdrawals", params={"status": "PENDING"})).json()["data"]["items"][0]["id"]
    review = await client.post(
        f"{ADMIN_BASE}/finance/withdrawals/{wd_small_id}/review",
        json={"decision": "APPROVE", "note": "资料齐全"}, headers=csrf)
    assert review.status_code == 200, review.text
    assert review.json()["data"]["status"] == "PAID"

    wallet = await db_session.scalar(
        select(WalletAccount).where(WalletAccount.user_id == int(seller["profile"]["id"])))
    assert wallet.balance_cents == 0 and wallet.withdrawable_cents == 0

    # 大额提现（补足余额模拟多笔成交后的大额）
    wallet.balance_cents = 600_000
    wallet.withdrawable_cents = 600_000
    await db_session.commit()
    big = await client.post(f"{C_BASE}/wallet/withdrawals",
                            json={"amountCents": 500_000},
                            headers=bearer(seller["token"]))
    assert big.status_code == 200
    assert big.json()["data"]["needDualReview"] is True

    wd_big = (await client.get(f"{ADMIN_BASE}/finance/withdrawals",
                               params={"status": "PENDING"})).json()["data"]["items"][0]
    # 初审 → 仍待复审
    first = await client.post(
        f"{ADMIN_BASE}/finance/withdrawals/{wd_big['id']}/review",
        json={"decision": "APPROVE", "note": "初审通过"}, headers=csrf)
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "PENDING"

    # 同一管理员复审被拒（42203）
    dup = await client.post(
        f"{ADMIN_BASE}/finance/withdrawals/{wd_big['id']}/review",
        json={"decision": "APPROVE"}, headers=csrf)
    assert dup.status_code == 422
    assert dup.json()["code"] == 42203

    # 第二位管理员复审 → 到账
    csrf2 = await _second_admin(db_session, client)
    second = await client.post(
        f"{ADMIN_BASE}/finance/withdrawals/{wd_big['id']}/review",
        json={"decision": "APPROVE"}, headers=csrf2)
    assert second.status_code == 200
    assert second.json()["data"]["status"] == "PAID"

    # 驳回路径：资金退回可提现
    again = await client.post(f"{C_BASE}/wallet/withdrawals",
                              json={"amountCents": 10000},
                              headers=bearer(seller["token"]))
    assert again.status_code == 200
    wd_last = (await client.get(f"{ADMIN_BASE}/finance/withdrawals",
                                params={"status": "PENDING"})).json()["data"]["items"][0]
    # 复审员登录已刷新 CSRF Cookie，重新以初审管理员身份登录取新头
    csrf = await admin_login(client)
    rejected = await client.post(
        f"{ADMIN_BASE}/finance/withdrawals/{wd_last['id']}/review",
        json={"decision": "REJECT", "note": "账户信息与实名不一致"}, headers=csrf)
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"
    await db_session.refresh(wallet)
    assert wallet.withdrawable_cents == 100_000  # 冻结资金已退回


@pytest.mark.asyncio
async def test_prepay_is_idempotent(client, db_session):
    """NF-13：重复拉起支付返回同一支付意图；重复回调幂等（托管不重复入账）。"""
    _, item_id, _ = await _seller_item(client)
    buyer = await register_user(client, PHONE_BUYER)
    order_data = await create_order(client, buyer["token"], item_id)
    order_id = order_data["orderId"]

    first = (await client.post(f"{C_BASE}/payments/prepay",
                               json={"orderId": int(order_id)},
                               headers=bearer(buyer["token"]))).json()["data"]
    second = (await client.post(f"{C_BASE}/payments/prepay",
                                json={"orderId": int(order_id)},
                                headers=bearer(buyer["token"]))).json()["data"]
    assert first["payParams"]["mockPayUrl"] == second["payParams"]["mockPayUrl"]

    await pay_order(client, buyer["token"], order_id)
    params = first["payParams"]
    txn_no = params["mockPayUrl"].rsplit("/", 1)[-1]
    again = await client.post(f"{C_BASE}/payments/mock-callback",
                              json={"txnNo": txn_no, "sign": params["sign"]})
    assert again.status_code == 200

    escrow_credits = int((await db_session.execute(
        select(func.count()).select_from(LedgerEntry)
        .where(LedgerEntry.account == "PLATFORM_ESCROW",
               LedgerEntry.direction == "CREDIT", LedgerEntry.type == "ESCROW"))).scalar() or 0)
    assert escrow_credits == 1  # 重复回调未重复入账


@pytest.mark.asyncio
async def test_orders_list_filters(client):
    """M06-09：订单列表按买入/卖出与交易方式筛选。"""
    seller, item_id, _ = await _seller_item(client)
    buyer = await register_user(client, PHONE_BUYER)
    await create_order(client, buyer["token"], item_id)

    bought = (await client.get(f"{C_BASE}/orders", params={"role": "buyer"},
                               headers=bearer(buyer["token"]))).json()["data"]
    sold = (await client.get(f"{C_BASE}/orders", params={"role": "seller"},
                             headers=bearer(seller["token"]))).json()["data"]
    assert bought["total"] == 1 and sold["total"] == 1
    assert bought["items"][0]["role"] == "buyer"
    assert sold["items"][0]["role"] == "seller"
    assert bought["items"][0]["canPay"] is True
