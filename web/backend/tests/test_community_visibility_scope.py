"""新注册用户的小区内容隔离（M02/BR-02）。

回归：首页与各浏览接口曾仅识别 VERIFIED 住户；新注册用户的未认证住户档案
（注册时选择的意向小区）不被采纳，查询在取不到小区时退化为全平台数据，
导致新用户在首页各板块看到其它小区的物品/生活/互助/喇叭内容。
"""

import pytest

from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_headers,
    bearer,
    create_on_sale_item,
    register_user,
    verified_user,
)


async def _register_with_intent(client, phone: str, community_id: int) -> dict:
    account = await register_user(client, phone)
    resp = await client.post(f"{C_BASE}/auth/register/complete", json={
        "nickname": f"新邻居{phone[-4:]}",
        "intentCommunityId": community_id,
    }, headers=bearer(account["token"]))
    assert resp.status_code == 200, resp.text
    return account


async def _publish_life(client, token: str, title: str) -> str:
    resp = await client.post(f"{C_BASE}/life/posts", json={
        "mediaType": "gallery",
        "media": [f"life/{title}.jpg"],
        "title": title,
        "description": "同一小区的生活动态。",
        "category": "小区风景",
    }, headers=bearer(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


async def _seed_two_communities(client) -> None:
    """在一号/二号小区各准备物品、生活、互助、喇叭内容。"""
    seller_a = await verified_user(client, "13944440001", community_id=1)
    seller_b = await verified_user(client, "13944440002", community_id=2)
    csrf = admin_headers(client)

    await create_on_sale_item(client, csrf, seller_a["token"], title="一号小区独有物品")
    await create_on_sale_item(client, csrf, seller_b["token"], title="二号小区独有物品")

    for token, title in ((seller_a["token"], "一号小区生活"),
                         (seller_b["token"], "二号小区生活")):
        post_id = await _publish_life(client, token, title)
        review = await client.post(f"{ADMIN_BASE}/life-posts/{post_id}/review",
                                   json={"decision": "APPROVE"},
                                   headers=admin_headers(client))
        assert review.status_code == 200, review.text

    for token, title in ((seller_a["token"], "一号小区互助"),
                         (seller_b["token"], "二号小区互助")):
        resp = await client.post(f"{C_BASE}/services", json={
            "kind": "HELP", "title": title,
        }, headers=bearer(token))
        assert resp.status_code == 200, resp.text

    for community_id, title in ((1, "一号小区公告"), (2, "二号小区公告")):
        resp = await client.post(f"{ADMIN_BASE}/broadcasts", json={
            "communityId": community_id,
            "title": title,
            "type": "NEW_ITEM",
            "effectiveMode": "IMMEDIATE",
        }, headers=admin_headers(client))
        assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_new_registered_user_only_sees_intent_community(client):
    """未认证新用户（仅注册建档）按意向小区浏览，不得看到其它小区内容。"""
    await _seed_two_communities(client)
    newbie = await _register_with_intent(client, "13944440003", community_id=1)
    headers = bearer(newbie["token"])

    home = (await client.get(f"{C_BASE}/home", headers=headers)).json()["data"]
    assert home["community"]["id"] == "1"
    assert [row["title"] for row in home["hotItems"]] == ["一号小区独有物品"]
    assert [row["title"] for row in home["lifePosts"]] == ["一号小区生活"]
    assert [row["title"] for row in home["serviceHelp"]] == ["一号小区互助"]
    assert [row["title"] for row in home["broadcasts"]] == ["一号小区公告"]
    counts = {zone["key"]: zone["count"] for zone in home["zones"]}
    assert counts["sale"] == 1
    assert counts["service"] == 1
    assert counts["gift"] == counts["swap"] == 0

    items = (await client.get(f"{C_BASE}/items", headers=headers)).json()["data"]
    assert [row["title"] for row in items["items"]] == ["一号小区独有物品"]

    life = (await client.get(f"{C_BASE}/life/posts", headers=headers)).json()["data"]
    assert [row["title"] for row in life["items"]] == ["一号小区生活"]

    services = (await client.get(f"{C_BASE}/services", headers=headers)).json()["data"]
    assert [row["title"] for row in services["items"]] == ["一号小区互助"]

    broadcasts = (await client.get(f"{C_BASE}/broadcasts", headers=headers)).json()["data"]
    assert [row["title"] for row in broadcasts] == ["一号小区公告"]


@pytest.mark.asyncio
async def test_user_without_community_sees_no_global_content(client):
    """未选择入住小区的账号（旧客户端跳过引导）不得回退到全平台内容。"""
    seller = await verified_user(client, "13944440011", community_id=1)
    await create_on_sale_item(client, admin_headers(client), seller["token"],
                              title="一号小区物品")

    newbie = await register_user(client, "13944440012")  # 未完善注册资料
    headers = bearer(newbie["token"])

    home = (await client.get(f"{C_BASE}/home", headers=headers)).json()["data"]
    assert home["community"]["id"] == ""
    assert home["hotItems"] == []
    assert home["lifePosts"] == []
    assert home["serviceHelp"] == []
    assert home["serviceOffer"] == []
    assert home["broadcasts"] == []
    assert all(zone["count"] == 0 for zone in home["zones"])

    assert (await client.get(f"{C_BASE}/items", headers=headers)).json()["data"]["items"] == []
    assert (await client.get(f"{C_BASE}/life/posts", headers=headers)).json()["data"]["items"] == []
    assert (await client.get(f"{C_BASE}/services", headers=headers)).json()["data"]["items"] == []
    assert (await client.get(f"{C_BASE}/broadcasts", headers=headers)).json()["data"] == []
