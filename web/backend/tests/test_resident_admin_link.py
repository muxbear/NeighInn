"""住户 ↔ C 端账号 ↔ 后台账号关联与授权（0012）。

覆盖：住户授权后台角色（自动建平台账号与后台账号、返回一次性初始密码）、
调整角色、撤销授权、重置密码、可授予角色白名单、强制改密与会话版本、
用户管理手工绑定/解绑住户、删除住户时存在后台身份的拦截、数据范围过滤。
"""

import pytest
from sqlalchemy import select

from src.core.security import decrypt_field
from src.db.models import AdminUser, PlatformUser, Resident, Role
from tests.conftest import ADMIN_BASE, admin_headers, admin_login, login_user


def _resident_payload(**overrides) -> dict:
    payload = {
        "communityId": 1,
        "name": "李叔叔",
        "gender": "男",
        "phone": "13700007777",
        "identity": "业主",
        "building": "3 栋 2 单元 501",
        "relationship": "房屋产权人",
        "certification": "已认证",
        "certificationNo": "",
        "level": "普通用户",
        "status": "正常",
    }
    payload.update(overrides)
    return payload


async def _role_id(db_session, code: str = "community_admin") -> int:
    return int(await db_session.scalar(select(Role.id).where(Role.code == code)))


async def _fresh(db_session, model, pk: int):
    """清空身份映射后重新加载，避免跨会话缓存读到旧值。"""
    db_session.expunge_all()
    return await db_session.get(model, pk)


@pytest.mark.asyncio
async def test_grant_resident_admin_creates_linked_accounts(client, db_session):
    csrf = await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(), headers=csrf)
    assert resp.status_code == 200, resp.text
    resident_id = int(resp.json()["data"]["id"])

    roles = await client.get(f"{ADMIN_BASE}/resident-admin-roles", headers=csrf)
    assert roles.status_code == 200, roles.text
    role_codes = {row["code"] for row in roles.json()["data"]}
    assert "community_admin" in role_codes
    assert "super_admin" not in role_codes
    role_id = await _role_id(db_session)

    granted = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
        json={"roleIds": [role_id], "reason": "业主委员会推荐"},
        headers={**csrf, "X-Idempotency-Key": "grant-test-1"},
    )
    assert granted.status_code == 200, granted.text
    data = granted.json()["data"]
    assert data["initialPassword"]
    assert data["admin"]["source"] == "RESIDENT"
    assert data["admin"]["mustChangePassword"] is True
    assert [role["code"] for role in data["admin"]["roles"]] == ["community_admin"]
    assert data["admin"]["communities"][0]["id"] == "1"
    assert data["linkedUserCreated"] is True

    # 住户列表返回后台身份，且不逐行查询也应返回
    listing = await client.get(f"{ADMIN_BASE}/residents",
                               params={"communityId": 1}, headers=csrf)
    row = next(item for item in listing.json()["data"]["items"]
               if int(item["id"]) == resident_id)
    assert row["adminAccount"]["username"] == data["admin"]["username"]
    assert row["userId"]

    # 平台账号已建立并可短信登录移动端
    resident = await db_session.get(Resident, resident_id)
    assert resident.user_id is not None
    user = await db_session.get(PlatformUser, resident.user_id)
    assert decrypt_field(user.phone_enc) == "13700007777"

    # 初始密码可用于后台登录，且首登被强制改密拦截
    login = await client.post(f"{ADMIN_BASE}/auth/login", json={
        "username": data["admin"]["username"],
        "password": data["initialPassword"],
    })
    assert login.status_code == 200, login.text
    assert login.json()["data"]["admin"]["mustChangePassword"] is True
    blocked = await client.get(f"{ADMIN_BASE}/dashboard/summary",
                               params={"communityId": 1})
    assert blocked.status_code == 403
    assert blocked.json()["code"] == 40306

    changed = await client.post(f"{ADMIN_BASE}/auth/password/change", json={
        "oldPassword": data["initialPassword"],
        "newPassword": "NewPass@2026ok",
    }, headers=admin_headers(client))
    assert changed.status_code == 200, changed.text
    me = await client.get(f"{ADMIN_BASE}/auth/me")
    assert me.json()["data"]["admin"]["mustChangePassword"] is False
    ok_summary = await client.get(f"{ADMIN_BASE}/dashboard/summary",
                                  params={"communityId": 1})
    assert ok_summary.status_code == 200, ok_summary.text


@pytest.mark.asyncio
async def test_grant_requires_verified_resident_and_assignable_role(client, db_session):
    csrf = await admin_login(client)
    resp = await client.post(
        f"{ADMIN_BASE}/residents",
        json=_resident_payload(certification="未认证", phone="13700006666"),
        headers=csrf,
    )
    resident_id = int(resp.json()["data"]["id"])
    role_id = await _role_id(db_session)

    denied = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
        json={"roleIds": [role_id]}, headers=csrf)
    assert denied.status_code == 422
    assert denied.json()["code"] == 42201

    # 未标记可授予的角色（社区运营）不可用于住户
    operator_role = await _role_id(db_session, "community_operator")
    resp = await client.put(
        f"{ADMIN_BASE}/residents/{resident_id}",
        json=_resident_payload(certification="已认证", phone="13700006666"),
        headers=csrf,
    )
    assert resp.status_code == 200, resp.text
    bad_role = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
        json={"roleIds": [operator_role]}, headers=csrf)
    assert bad_role.status_code == 422
    assert "不允许授予" in bad_role.json()["message"]


@pytest.mark.asyncio
async def test_grant_replay_and_adjust_role(client, db_session):
    csrf = await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="13700005555"), headers=csrf)
    resident_id = int(resp.json()["data"]["id"])
    role_id = await _role_id(db_session)
    headers = {**csrf, "X-Idempotency-Key": "grant-replay-1"}

    first = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
        json={"roleIds": [role_id]}, headers=headers)
    assert first.status_code == 200, first.text
    username = first.json()["data"]["admin"]["username"]

    # 同幂等键重放：不返回明文密码
    replay = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
        json={"roleIds": [role_id]}, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["initialPassword"] is None
    assert replay.json()["data"]["replay"] is True

    # 调整角色：不重复建号、不返回新密码（先建一个可授予的自定义角色）
    created_role = await client.post(f"{ADMIN_BASE}/roles", json={
        "name": "楼栋联络员",
        "code": "building_liaison",
        "dataScope": "OWN_COMMUNITY",
        "assignableToResident": True,
    }, headers=csrf)
    assert created_role.status_code == 200, created_role.text
    liaison_role = int(created_role.json()["data"]["id"])
    adjusted = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
        json={"roleIds": [liaison_role]}, headers={**csrf,
                                                   "X-Idempotency-Key": "grant-adjust-1"})
    assert adjusted.status_code == 200, adjusted.text
    payload = adjusted.json()["data"]
    assert payload["admin"]["username"] == username
    assert payload["initialPassword"] is None
    assert payload["adjusted"] is True


@pytest.mark.asyncio
async def test_revoke_and_reset_password(client, db_session):
    csrf = await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="13700004444"), headers=csrf)
    resident_id = int(resp.json()["data"]["id"])
    role_id = await _role_id(db_session)
    granted = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
        json={"roleIds": [role_id]}, headers=csrf)
    assert granted.status_code == 200, granted.text
    data = granted.json()["data"]

    reset = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account/reset-password",
        headers={**csrf, "X-Idempotency-Key": "reset-pw-1"})
    assert reset.status_code == 200, reset.text
    new_password = reset.json()["data"]["initialPassword"]
    assert new_password and new_password != data["initialPassword"]

    revoke = await client.post(
        f"{ADMIN_BASE}/residents/{resident_id}/admin-account/revoke",
        headers={**csrf, "X-Idempotency-Key": "revoke-1"})
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["data"]["status"] == "DISABLED"

    db_session.expunge_all()
    admin_row = await db_session.scalar(
        select(AdminUser).where(AdminUser.resident_id == resident_id))
    assert admin_row.status == "DISABLED"
    assert admin_row.must_change_password is True
    username = admin_row.username

    login = await client.post(f"{ADMIN_BASE}/auth/login", json={
        "username": username,
        "password": new_password,
    })
    assert login.status_code == 403

    # C 端账号不受撤销影响，仍可登录移动端
    account = await login_user(client, "13700004444")
    assert account["token"]


@pytest.mark.asyncio
async def test_delete_resident_blocked_when_admin_linked(client, db_session):
    csrf = await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="13700003333"), headers=csrf)
    resident_id = int(resp.json()["data"]["id"])
    role_id = await _role_id(db_session)
    await client.post(f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
                      json={"roleIds": [role_id]}, headers=csrf)

    blocked = await client.delete(f"{ADMIN_BASE}/residents/{resident_id}", headers=csrf)
    assert blocked.status_code == 422, blocked.text
    assert "解除授权" in blocked.json()["message"]


@pytest.mark.asyncio
async def test_admin_user_bind_and_unbind_resident(client, db_session):
    csrf = await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="13700002222"), headers=csrf)
    resident_id = int(resp.json()["data"]["id"])

    options = await client.get(f"{ADMIN_BASE}/resident-options",
                               params={"communityId": 1, "keyword": "李叔叔"},
                               headers=csrf)
    assert options.status_code == 200, options.text
    assert any(int(item["id"]) == resident_id for item in options.json()["data"])

    created = await client.post(f"{ADMIN_BASE}/admin-users", json={
        "username": "community_staff",
        "password": "Staff@2026abc",
        "realName": "社区员工",
        "phone": "13700002222",
        "residentId": resident_id,
        "roleIds": [await _role_id(db_session)],
        "communityIds": [1],
    }, headers=csrf)
    assert created.status_code == 200, created.text
    account = created.json()["data"]
    assert account["source"] == "MANUAL"
    assert account["residentId"] == str(resident_id)
    assert account["mobileBound"] is True

    resident = await _fresh(db_session, Resident, resident_id)
    assert resident.user_id is not None
    user_id = resident.user_id

    # 解绑：只清除后台账号关联，平台账号本身保留
    detached = await client.put(f"{ADMIN_BASE}/admin-users/{account['id']}", json={
        "username": "community_staff",
        "realName": "社区员工",
        "phone": "",
        "residentId": None,
        "roleIds": [await _role_id(db_session)],
        "communityIds": [1],
    }, headers=csrf)
    assert detached.status_code == 200, detached.text
    assert detached.json()["data"]["residentId"] == ""
    user = await _fresh(db_session, PlatformUser, user_id)
    assert user is not None


@pytest.mark.asyncio
async def test_admin_user_link_resident_dedicated_endpoint(client, db_session):
    """用户管理操作列的「关联住户」走独立接口，不经过账号编辑表单。"""
    csrf = await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(name="关联测试住户", phone="13700009999"),
                             headers=csrf)
    assert resp.status_code == 200, resp.text
    resident_id = int(resp.json()["data"]["id"])

    created = await client.post(f"{ADMIN_BASE}/admin-users", json={
        "username": "link_only_staff",
        "password": "Staff@2026abc",
        "realName": "纯后台员工",
        "phone": "",
        "roleIds": [await _role_id(db_session)],
        "communityIds": [1],
    }, headers=csrf)
    assert created.status_code == 200, created.text
    account = created.json()["data"]
    assert account["residentId"] == ""

    linked = await client.put(f"{ADMIN_BASE}/admin-users/{account['id']}/resident",
                              json={"residentId": resident_id}, headers=csrf)
    assert linked.status_code == 200, linked.text
    linked_account = linked.json()["data"]
    assert linked_account["residentId"] == str(resident_id)
    assert linked_account["residentName"] == "关联测试住户"
    assert linked_account["communityName"]
    assert linked_account["mobileBound"] is True
    user_id = int(linked_account["userId"])

    # 编辑基础资料不提交 residentId 时，绑定关系保持不变
    updated = await client.put(f"{ADMIN_BASE}/admin-users/{account['id']}", json={
        "username": "link_only_staff",
        "realName": "纯后台员工（改名）",
        "phone": "",
        "roleIds": [await _role_id(db_session)],
        "communityIds": [1],
    }, headers=csrf)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["residentId"] == str(resident_id)

    unlinked = await client.put(f"{ADMIN_BASE}/admin-users/{account['id']}/resident",
                                json={"residentId": None}, headers=csrf)
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["data"]["residentId"] == ""
    assert unlinked.json()["data"]["mobileBound"] is False
    # 平台账号本身保留，不会被注销
    assert await _fresh(db_session, PlatformUser, user_id) is not None


@pytest.mark.asyncio
async def test_community_admin_sees_only_own_community(client, db_session):
    csrf = await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="13700001111"), headers=csrf)
    resident_id = int(resp.json()["data"]["id"])
    role_id = await _role_id(db_session)
    granted = await client.post(f"{ADMIN_BASE}/residents/{resident_id}/admin-account",
                                json={"roleIds": [role_id]}, headers=csrf)
    assert granted.status_code == 200, granted.text
    account = granted.json()["data"]["admin"]

    # 首登强制改密后使用社区管理员身份访问其他社区
    await client.post(f"{ADMIN_BASE}/auth/logout", headers=csrf)
    login = await client.post(f"{ADMIN_BASE}/auth/login", json={
        "username": account["username"],
        "password": granted.json()["data"]["initialPassword"],
    })
    assert login.status_code == 200, login.text
    change = await client.post(f"{ADMIN_BASE}/auth/password/change", json={
        "oldPassword": granted.json()["data"]["initialPassword"],
        "newPassword": "NewPass@2026ok",
    }, headers=admin_headers(client))
    assert change.status_code == 200, change.text

    me = await client.get(f"{ADMIN_BASE}/auth/me")
    admin_info = me.json()["data"]["admin"]
    assert admin_info["dataScope"] == "OWN_COMMUNITY"
    assert [item["id"] for item in admin_info["communities"]] == ["1"]

    own = await client.get(f"{ADMIN_BASE}/residents",
                           params={"communityId": 1})
    assert own.status_code == 200, own.text
    other = await client.get(f"{ADMIN_BASE}/residents",
                             params={"communityId": 2})
    assert other.status_code == 403
    assert other.json()["code"] == 40302


@pytest.mark.asyncio
async def test_assignable_flag_guard(client):
    csrf = await admin_login(client)
    invalid = await client.post(f"{ADMIN_BASE}/roles", json={
        "name": "全平台运营",
        "code": "all_scope_ops",
        "dataScope": "ALL",
        "assignableToResident": True,
    }, headers=csrf)
    assert invalid.status_code == 422
    assert invalid.json()["code"] == 42201

    valid = await client.post(f"{ADMIN_BASE}/roles", json={
        "name": "楼栋长",
        "code": "building_lead",
        "dataScope": "OWN_COMMUNITY",
        "assignableToResident": True,
    }, headers=csrf)
    assert valid.status_code == 200, valid.text
    assert valid.json()["data"]["assignableToResident"] is True
