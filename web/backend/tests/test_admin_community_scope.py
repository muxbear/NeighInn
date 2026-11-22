"""社区管理员：后台账号社区管理范围（区划授权 + 指定社区）。

覆盖：范围读写、上下级区划合并、区划子树动态展开、指定社区并集、
非全局管理员越权写入拦截、审计与账号删除清理。
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.db.models import (
    AdminUser,
    AdminUserRegionGrant,
    AuditLog,
    Community,
    Region,
)
from tests.conftest import ADMIN_BASE, admin_login

SCOPE_PASSWORD = "ScopeAdmin@2025"


async def _role_id(client, csrf: dict, code: str) -> int:
    resp = await client.get(f"{ADMIN_BASE}/roles", headers=csrf)
    assert resp.status_code == 200, resp.text
    return next(int(row["id"]) for row in resp.json()["data"] if row["code"] == code)


async def _create_admin(client, csrf: dict, username: str,
                        role_ids: list[int]) -> int:
    resp = await client.post(f"{ADMIN_BASE}/admin-users", json={
        "username": username,
        "password": SCOPE_PASSWORD,
        "realName": f"测试{username[-4:]}",
        "roleIds": role_ids,
        "status": "ACTIVE",
    }, headers=csrf)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["id"])


async def _region_id(db_session, code: str) -> int:
    region = await db_session.scalar(select(Region).where(Region.code == code))
    assert region is not None
    return int(region.id)


async def _community_id(db_session, code: str) -> int:
    community = await db_session.scalar(
        select(Community).where(Community.code == code))
    assert community is not None
    return int(community.id)


@pytest.mark.asyncio
async def test_community_scope_roundtrip_and_region_merge(client, db_session):
    csrf = await admin_login(client)
    role_id = await _role_id(client, csrf, "community_admin")
    admin_id = await _create_admin(client, csrf, "scope_roundtrip", [role_id])

    xihu = await _region_id(db_session, "330106")          # 浙江省 / 杭州市 / 西湖区
    wenxin = await _region_id(db_session, "330106001")     # 西湖区 / 文新街道
    lake = await _community_id(db_session, "SQ3301020001")  # 上城区“湖畔名庭”

    # 上级区划 + 下级街道同时提交时，仅保留上级区划授权。
    resp = await client.put(
        f"{ADMIN_BASE}/admin-users/{admin_id}/community-scope",
        json={"regionIds": [xihu, wenxin], "communityIds": [lake]},
        headers=csrf,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["adminUserId"] == str(admin_id)
    assert [int(item["regionId"]) for item in data["regionGrants"]] == [xihu]
    assert [int(item["id"]) for item in data["communities"]] == [lake]
    grant_path = [node["name"] for node in data["regionGrants"][0]["path"]]
    assert grant_path == ["浙江省", "杭州市", "西湖区"]
    assert data["regionGrants"][0]["level"] == "DISTRICT"

    # GET 与 PUT 返回一致。
    resp = await client.get(
        f"{ADMIN_BASE}/admin-users/{admin_id}/community-scope", headers=csrf)
    assert resp.status_code == 200, resp.text
    fetched = resp.json()["data"]
    assert [int(item["regionId"]) for item in fetched["regionGrants"]] == [xihu]
    assert [int(item["id"]) for item in fetched["communities"]] == [lake]

    # 账号列表带出范围摘要，社区管理页无需逐个拉取。
    resp = await client.get(f"{ADMIN_BASE}/admin-users",
                            params={"keyword": "scope_roundtrip"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    row = resp.json()["data"]["items"][0]
    assert row["scopeRegionCount"] == 1
    assert row["scopeCommunityCount"] == 1

    # 审计与落库。
    action_count = await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "admin-user.scope.update",
            AuditLog.resource_id == str(admin_id),
        ))
    assert action_count == 1
    region_rows = await db_session.scalar(
        select(func.count()).select_from(AdminUserRegionGrant).where(
            AdminUserRegionGrant.admin_user_id == admin_id))
    assert region_rows == 1

    # 非法区划直接拒绝。
    resp = await client.put(
        f"{ADMIN_BASE}/admin-users/{admin_id}/community-scope",
        json={"regionIds": [99999999], "communityIds": []}, headers=csrf)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001

    # 删除账号时同步清理区划授权，避免残留孤儿记录。
    resp = await client.delete(f"{ADMIN_BASE}/admin-users/{admin_id}", headers=csrf)
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert await db_session.scalar(
        select(func.count()).select_from(AdminUserRegionGrant).where(
            AdminUserRegionGrant.admin_user_id == admin_id)) == 0


@pytest.mark.asyncio
async def test_region_grant_expands_data_scope_dynamically(client, db_session):
    csrf = await admin_login(client)
    role_id = await _role_id(client, csrf, "community_admin")
    admin_id = await _create_admin(client, csrf, "scope_dynamic", [role_id])

    xihu = await _region_id(db_session, "330106")
    wenxin = await _region_id(db_session, "330106001")
    lake = await _community_id(db_session, "SQ3301020001")

    resp = await client.put(
        f"{ADMIN_BASE}/admin-users/{admin_id}/community-scope",
        json={"regionIds": [xihu], "communityIds": [lake]},
        headers=csrf,
    )
    assert resp.status_code == 200, resp.text

    # 区划授权按子树动态展开：西湖区 5 个小区 + 指定上城区 1 个 = 6 个。
    resp = await client.post(f"{ADMIN_BASE}/auth/login", json={
        "username": "scope_dynamic", "password": SCOPE_PASSWORD,
    })
    assert resp.status_code == 200, resp.text
    resp = await client.get(f"{ADMIN_BASE}/auth/me")
    assert resp.status_code == 200, resp.text
    community_names = {item["name"] for item in resp.json()["data"]["admin"]["communities"]}
    assert "湖畔名庭" in community_names
    assert "阳光花园小区" in community_names
    assert len(community_names) == 6

    resp = await client.get(f"{ADMIN_BASE}/communities",
                            params={"page": 1, "pageSize": 50})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 6

    # 区划下新增社区自动纳入，无需重新授权。
    db_session.add(Community(
        region_id=xihu,
        street_id=wenxin,
        name="动态新增苑",
        code="SQDYNAMIC0001",
        type="商品房社区",
        address="文新街道动态新增苑",
        status="OPERATING",
    ))
    await db_session.commit()
    resp = await client.get(f"{ADMIN_BASE}/communities",
                            params={"page": 1, "pageSize": 50})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 7
    assert "动态新增苑" in {
        item["name"] for item in resp.json()["data"]["items"]}


@pytest.mark.asyncio
async def test_scoped_operator_cannot_assign_community_scope(client, db_session):
    csrf = await admin_login(client)

    resp = await client.post(f"{ADMIN_BASE}/roles", json={
        "name": "范围委派员",
        "code": "scope_delegate",
        "dataScope": "COMMUNITY_SET",
    }, headers=csrf)
    assert resp.status_code == 200, resp.text
    role_id = int(resp.json()["data"]["id"])
    resp = await client.put(
        f"{ADMIN_BASE}/roles/{role_id}/permissions",
        json={"permissions": [
            "system:admin-user:view",
            "system:admin-user:update",
        ]},
        headers=csrf,
    )
    assert resp.status_code == 200, resp.text

    await _create_admin(client, csrf, "scope_operator", [role_id])
    target_id = await _create_admin(
        client, csrf, "scope_target",
        [await _role_id(client, csrf, "community_admin")])

    resp = await client.post(f"{ADMIN_BASE}/auth/login", json={
        "username": "scope_operator", "password": SCOPE_PASSWORD,
    })
    assert resp.status_code == 200, resp.text
    operator_csrf = {"x-csrf-token": resp.json()["data"]["csrfToken"]}

    region = await _region_id(db_session, "330106")
    resp = await client.put(
        f"{ADMIN_BASE}/admin-users/{target_id}/community-scope",
        json={"regionIds": [region], "communityIds": []},
        headers=operator_csrf,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == 40301

    # 未发生写入。
    assert await db_session.scalar(
        select(func.count()).select_from(AdminUserRegionGrant).where(
            AdminUserRegionGrant.admin_user_id == target_id)) == 0


@pytest.mark.asyncio
async def test_super_admin_scope_is_read_only(client, db_session):
    csrf = await admin_login(client)
    super_id = await db_session.scalar(
        select(AdminUser.id).where(AdminUser.is_super_admin.is_(True)))
    resp = await client.put(
        f"{ADMIN_BASE}/admin-users/{super_id}/community-scope",
        json={"regionIds": [], "communityIds": []}, headers=csrf)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == 42201
