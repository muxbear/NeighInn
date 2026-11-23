"""工作台聚合接口：真实口径、社区范围、业务动态与待办闭环。"""

import time

import pytest

from tests.conftest import (
    ADMIN_BASE,
    admin_login,
    create_draft,
    register_user,
    submit_owner_proof,
    verified_user,
)


@pytest.mark.asyncio
async def test_summary_returns_real_aggregates(client):
    csrf = await admin_login(client)

    empty = (await client.get(f"{ADMIN_BASE}/dashboard/summary", headers=csrf)).json()["data"]
    assert empty["scope"] == "PLATFORM"
    assert empty["metrics"]["users"] == 0
    assert empty["metrics"]["platformUsers"] == 0
    assert empty["metrics"]["gmvCents"] == 0
    assert empty["metrics"]["activeRate"] == 0.0
    assert empty["distribution"]["total"] == 0

    account = await verified_user(client, "13900002222", community_id=1)

    summary = (await client.get(f"{ADMIN_BASE}/dashboard/summary", headers=csrf)).json()["data"]
    assert summary["metrics"]["users"] == 1
    assert summary["metrics"]["platformUsers"] == 1
    assert summary["metrics"]["todayNewUsers"] == 1
    # 登录会写入 last_active_at，因此近 7 日活跃是真实值而非 0。
    assert summary["metrics"]["activeUsers"] == 1
    assert summary["metrics"]["activeRate"] == 100.0
    assert summary["distribution"] == {
        "owner": 1, "tenant": 0, "family": 0, "business": 0,
        "staff": 0, "student": 0, "total": 1,
    }
    assert account["communityId"] == 1


@pytest.mark.asyncio
async def test_summary_and_todos_are_community_scoped(client):
    await verified_user(client, "13900003333", community_id=1)
    await verified_user(client, "13900004444", community_id=2)
    csrf = await admin_login(client)

    # 两个社区各有一名待审核认证，用于验证待办按社区收敛。
    pending_1 = await register_user(client, "13900005555")
    await submit_owner_proof(client, pending_1["token"], community_id=1)
    pending_2 = await register_user(client, "13900006666")
    await submit_owner_proof(client, pending_2["token"], community_id=2)

    platform = (await client.get(
        f"{ADMIN_BASE}/dashboard/summary", headers=csrf)).json()["data"]
    assert platform["scope"] == "PLATFORM"
    # 全平台用户数包含两名待审核注册用户；认证住户分布只统计已认证档案。
    assert platform["metrics"]["users"] == 4
    assert platform["metrics"]["platformUsers"] == 4
    assert platform["distribution"]["total"] == 2

    community_1 = (await client.get(
        f"{ADMIN_BASE}/dashboard/summary",
        params={"communityId": 1}, headers=csrf)).json()["data"]
    assert community_1["scope"] == "COMMUNITY"
    assert community_1["community"]["id"] == "1"
    assert community_1["metrics"]["users"] == 1
    assert community_1["metrics"]["platformUsers"] == 4
    assert community_1["distribution"]["total"] == 1

    todos_1 = (await client.get(
        f"{ADMIN_BASE}/dashboard/todos",
        params={"communityId": 1}, headers=csrf)).json()["data"]
    todos_2 = (await client.get(
        f"{ADMIN_BASE}/dashboard/todos",
        params={"communityId": 2}, headers=csrf)).json()["data"]
    todos_all = (await client.get(
        f"{ADMIN_BASE}/dashboard/todos", headers=csrf)).json()["data"]

    cert_1 = next(item for item in todos_1 if item["key"] == "certification")
    cert_2 = next(item for item in todos_2 if item["key"] == "certification")
    cert_all = next(item for item in todos_all if item["key"] == "certification")
    assert (cert_1["count"], cert_2["count"], cert_all["count"]) == (1, 1, 2)

    missing = await client.get(
        f"{ADMIN_BASE}/dashboard/summary",
        params={"communityId": 9999}, headers=csrf)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_trend_uses_business_day_and_real_content(client):
    account = await verified_user(client, "13900007777", community_id=1)
    csrf = await admin_login(client)
    item_id = await create_draft(client, account["token"], title="工作台趋势测试物品")
    assert item_id

    trend = (await client.get(
        f"{ADMIN_BASE}/dashboard/trend",
        params={"days": 7, "communityId": 1}, headers=csrf)).json()["data"]
    assert trend["scope"] == "COMMUNITY"
    assert trend["days"] == 7
    assert len(trend["labels"]) == 7
    # 今日（业务时区自然日）新增注册 1、内容发布 1。
    assert trend["newUsers"][-1] == 1
    assert trend["contentPublished"][-1] == 1
    assert sum(trend["newUsers"]) == 1

    other = (await client.get(
        f"{ADMIN_BASE}/dashboard/trend",
        params={"days": 7, "communityId": 2}, headers=csrf)).json()["data"]
    assert sum(other["newUsers"]) == 0
    assert sum(other["contentPublished"]) == 0

    # 天数上限收敛到 30，避免看板被超大区间拖慢。
    capped = await client.get(
        f"{ADMIN_BASE}/dashboard/trend",
        params={"days": 90}, headers=csrf)
    assert capped.status_code == 400


@pytest.mark.asyncio
async def test_activities_are_business_events_with_epoch_millis(client):
    account = await verified_user(client, "13900008888", community_id=1)
    csrf = await admin_login(client)
    item_id = await create_draft(client, account["token"], title="动态流测试物品")
    assert item_id

    events = (await client.get(
        f"{ADMIN_BASE}/dashboard/activities",
        params={"limit": 10, "communityId": 1}, headers=csrf)).json()["data"]
    kinds = {event["kind"] for event in events}
    assert "certification" in kinds
    cert_event = next(event for event in events if event["kind"] == "certification")
    assert cert_event["action"] == "提交了住户认证"
    assert cert_event["actor"]
    # naive UTC 时间必须换算为正确 epoch，避免服务器时区造成小时级偏移。
    assert abs(int(time.time() * 1000) - cert_event["time"]) < 60 * 60 * 1000

    scoped = (await client.get(
        f"{ADMIN_BASE}/dashboard/activities",
        params={"limit": 10, "communityId": 2}, headers=csrf)).json()["data"]
    assert all(event["kind"] != "certification" for event in scoped)
    assert all(event["kind"] != "item" for event in scoped)

    limited = (await client.get(
        f"{ADMIN_BASE}/dashboard/activities",
        params={"limit": 1}, headers=csrf)).json()["data"]
    assert len(limited) == 1


@pytest.mark.asyncio
async def test_todos_only_expose_actionable_modules(client):
    """报修模块后端仍为 Phase 2 占位（501），工作台不得暴露无法闭环的待办入口。"""
    csrf = await admin_login(client)

    todos = (await client.get(
        f"{ADMIN_BASE}/dashboard/todos",
        params={"communityId": 1}, headers=csrf)).json()["data"]
    keys = {item["key"] for item in todos}
    assert keys == {
        "community_application", "certification", "item", "life", "report", "dispute",
        "withdrawal", "help", "help_service",
    }
    assert "repair" not in keys and "feedback" not in keys
    assert all(item["route"].startswith("/") for item in todos)
