"""后台社区物品管理测试：概览聚合、编辑、下架原因与删除守卫。"""

import pytest
from sqlalchemy import select

from src.db.models import Favorite
from tests.conftest import (
    ADMIN_BASE,
    admin_login,
    bearer,
    create_draft,
    create_on_sale_item,
    create_order,
    register_user,
    submit_item,
    verified_user,
)


@pytest.mark.asyncio
async def test_item_overview_uses_real_counts(client):
    """指标卡与 Tab 计数来自真实聚合，覆盖在售/待审核/推荐位/本周成交。"""
    seller = await verified_user(client, "13922220001")
    csrf = await admin_login(client)
    on_sale_id = await create_on_sale_item(client, csrf, seller["token"])
    resp = await client.post(f"{ADMIN_BASE}/items/{on_sale_id}/recommend",
                             json={"enabled": True}, headers=csrf)
    assert resp.status_code == 200, resp.text

    pending_id = await create_draft(client, seller["token"])
    submitted = await submit_item(client, seller["token"], pending_id)
    assert submitted["status"] == "PENDING_REVIEW"

    overview = (await client.get(
        f"{ADMIN_BASE}/operations/overview",
        params={"module": "items", "communityId": 1},
        headers=csrf,
    )).json()["data"]
    assert overview["metrics"]["onSale"] == 1
    assert overview["metrics"]["pendingReview"] == 1
    assert overview["metrics"]["recommended"] == 1
    assert overview["metrics"]["recommendSlots"] == 12
    assert overview["metrics"]["weekDeals"] == 0
    assert overview["metrics"]["weekNew"] == 2
    assert overview["statusCounts"]["ON_SALE"] == 1
    assert overview["statusCounts"]["PENDING_REVIEW"] == 1
    assert overview["total"] == 2


@pytest.mark.asyncio
async def test_admin_update_item_and_validation(client):
    seller = await verified_user(client, "13922220002")
    csrf = await admin_login(client)
    item_id = await create_on_sale_item(client, csrf, seller["token"])

    resp = await client.put(
        f"{ADMIN_BASE}/items/{item_id}",
        json={
            "title": "九成新儿童平衡车（已保养）",
            "tradeType": "FREE_GIFT",
            "priceCents": 9900,
            "condition": "九九新",
            "qualityDesc": "孩子只骑过三次，车身无划痕，刹车灵敏，已做保养并附赠护具。",
        },
        headers=csrf,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["title"] == "九成新儿童平衡车（已保养）"
    assert data["tradeType"] == "FREE_GIFT"
    assert data["priceCents"] == 0  # 免费赠与价格强制归零（BR-12）

    invalid = await client.put(
        f"{ADMIN_BASE}/items/{item_id}",
        json={"title": "一"},
        headers=csrf,
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == 40001


@pytest.mark.asyncio
async def test_admin_offline_requires_reason(client):
    seller = await verified_user(client, "13922220003")
    csrf = await admin_login(client)
    item_id = await create_on_sale_item(client, csrf, seller["token"])

    # 请求体缺失 / 原因为空 → 参数校验失败（前端需弹窗收集原因）
    missing = await client.post(f"{ADMIN_BASE}/items/{item_id}/offline", headers=csrf)
    assert missing.status_code == 400
    assert missing.json()["code"] == 40001
    empty = await client.post(f"{ADMIN_BASE}/items/{item_id}/offline",
                              json={"reason": ""}, headers=csrf)
    assert empty.status_code == 400
    assert empty.json()["code"] == 40001

    resp = await client.post(f"{ADMIN_BASE}/items/{item_id}/offline",
                             json={"reason": "照片与实物不符"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "OFF_SHELF"


@pytest.mark.asyncio
async def test_admin_delete_item_and_order_guard(client, db_session):
    seller = await verified_user(client, "13922220004")
    buyer = await register_user(client, "13922220005")
    csrf = await admin_login(client)

    removable = await create_on_sale_item(client, csrf, seller["token"])
    fav = await client.post(f"/api/v1/items/{removable}/favorite",
                            headers=bearer(buyer["token"]))
    assert fav.status_code == 200, fav.text
    resp = await client.delete(f"{ADMIN_BASE}/items/{removable}", headers=csrf)
    assert resp.status_code == 200, resp.text
    gone = await client.get(f"{ADMIN_BASE}/items/{removable}")
    assert gone.status_code == 404
    assert await db_session.scalar(
        select(Favorite.id).where(Favorite.target_type == "ITEM",
                                  Favorite.target_id == int(removable))) is None

    ordered = await create_on_sale_item(client, csrf, seller["token"])
    await create_order(client, buyer["token"], ordered)
    blocked = await client.delete(f"{ADMIN_BASE}/items/{ordered}", headers=csrf)
    assert blocked.status_code == 422
    assert "交易中" in blocked.json()["message"]
