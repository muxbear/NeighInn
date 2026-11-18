"""Phase 2 集成测试：社区运维、用户管理与处置、角色权限、管理员账号、
报表导出、WebSocket 实时通道。

对应：W04-01（社区 CRUD）、W07（用户处置）、W01-02（RBAC 自助管理）、W08-03（导出）、
移动端详设 10.3（WS 帧协议）。
"""

import pytest
from sqlalchemy import select

from src.db.models import Item, Role, User
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_headers,
    admin_login,
    bearer,
    create_on_sale_item,
    register_user,
    verified_user,
)


async def _admin_region_children(client, parent_id: int | None = None) -> list[dict]:
    url = (f"{ADMIN_BASE}/regions/roots" if parent_id is None
           else f"{ADMIN_BASE}/regions/{parent_id}/children")
    resp = await client.get(url, headers=admin_headers(client))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_community_crud_and_status(client):
    """W04-01：社区新增（区县必填、经纬度选填）/编辑/停用；停用后移动端不可见。"""
    await admin_login(client)

    # 区县必填（经纬度已改为选填）
    bad = await client.post(f"{ADMIN_BASE}/communities",
                            json={"name": "测试社区"}, headers=admin_headers(client))
    assert bad.status_code == 400

    provinces = await _admin_region_children(client)
    zhejiang = next(node for node in provinces if node["name"] == "浙江省")
    hangzhou = (await _admin_region_children(client, int(zhejiang["id"])))[0]
    xihu = next(node for node in await _admin_region_children(client, int(hangzhou["id"]))
                if node["name"] == "西湖区")
    wenxin = next(node for node in await _admin_region_children(client, int(xihu["id"]))
                  if node["name"] == "文新街道")

    create = await client.post(f"{ADMIN_BASE}/communities", json={
        "name": "银杏湾社区", "type": "商品房社区", "address": "文新街道银杏湾",
        "longitude": 120.112, "latitude": 30.292,
        "regionId": int(xihu["id"]), "streetId": int(wenxin["id"]),
        "households": 1200, "population": 3200}, headers=admin_headers(client))
    assert create.status_code == 200, create.text
    community_id = create.json()["data"]["id"]
    assert create.json()["data"]["code"].startswith("SQ")

    update = await client.put(f"{ADMIN_BASE}/communities/{community_id}",
                              json={"name": "银杏湾社区（东区）", "households": 1500,
                                    "population": 3600, "longitude": 120.112,
                                    "latitude": 30.292}, headers=admin_headers(client))
    assert update.status_code == 200
    assert update.json()["data"]["name"] == "银杏湾社区（东区）"

    # 停用后移动端搜索不可见（status != OPERATING）
    await client.patch(f"{ADMIN_BASE}/communities/{community_id}/status",
                       json={"status": "SUSPENDED"}, headers=admin_headers(client))
    user = await verified_user(client, "13944440001")
    results = (await client.get(f"{C_BASE}/communities/search",
                                params={"keyword": "银杏湾"},
                                headers=bearer(user["token"]))).json()["data"]
    assert all(row["name"] != "银杏湾社区（东区）" for row in results)


@pytest.mark.asyncio
async def test_user_management_and_penalties(client, db_session):
    """W07：用户检索（手机号哈希精确）、处置联动下架、解除恢复。"""
    seller = await verified_user(client, "13944440002")
    await admin_login(client)
    item_id = await create_on_sale_item(client, admin_headers(client), seller["token"])

    # 按完整手机号精确检索（脱敏存储，不明文索引）
    found = (await client.get(f"{ADMIN_BASE}/users",
                              params={"keyword": "13944440002"})).json()["data"]
    assert found["total"] == 1
    user_id = found["items"][0]["id"]
    assert "****" in found["items"][0]["phone"]

    # 详情 360°
    detail = (await client.get(f"{ADMIN_BASE}/users/{user_id}")).json()["data"]
    assert detail["certificationStatus"] == "VERIFIED"
    assert detail["publishCount"] == 1

    # 处置原因必填
    bad = await client.post(f"{ADMIN_BASE}/users/{user_id}/penalties",
                            json={"type": "MUTE", "reason": "违规"},
                            headers=admin_headers(client))
    assert bad.status_code == 400

    # 封禁：账号冻结 + 在售物品自动下架（W02-04 联动）
    ban = await client.post(f"{ADMIN_BASE}/users/{user_id}/penalties",
                            json={"type": "BAN",
                                  "reason": "多次售假且拒不配合调解"},
                            headers=admin_headers(client))
    assert ban.status_code == 200
    assert "已下架" in ban.json()["message"]

    user = await db_session.get(User, int(user_id))
    assert user.status == "FROZEN"
    item = await db_session.get(Item, int(item_id))
    assert item.status == "OFF_SHELF"

    # 解除封禁恢复账号
    penalties = (await client.get(f"{ADMIN_BASE}/users/{user_id}/penalties")).json()["data"]
    revoke = await client.post(
        f"{ADMIN_BASE}/users/{user_id}/penalties/{penalties[0]['id']}/revoke",
        headers=admin_headers(client))
    assert revoke.status_code == 200
    await db_session.refresh(user)
    assert user.status == "ACTIVE"

    # 被封禁期间不能发布（处置联动）
    await client.post(f"{ADMIN_BASE}/users/{user_id}/penalties",
                      json={"type": "PUBLISH_LIMIT", "reason": "短期限制发布"},
                      headers=admin_headers(client))
    blocked = await client.post(f"{C_BASE}/items", json={
        "title": "测试物品", "tradeType": "MONETARY", "priceCents": 100,
        "qualityDesc": "质量说明超过二十个字的描述文本内容",
        "images": ["a.jpg", "b.jpg", "c.jpg"], "condition": "九九新"},
        headers=bearer(seller["token"]))
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_roles_and_permission_grant(client, db_session):
    """W01-02：角色 CRUD、权限授予（非法权限码拦截）、超管保护。"""
    await admin_login(client)

    create = await client.post(f"{ADMIN_BASE}/roles",
                               json={"name": "社区志愿者", "dataScope": "OWN_COMMUNITY"},
                               headers=admin_headers(client))
    assert create.status_code == 200
    role_id = create.json()["data"]["id"]

    # 授予权限
    grant = await client.put(f"{ADMIN_BASE}/roles/{role_id}/permissions",
                             json={"permissions": ["dashboard:view", "community:item:view"]},
                             headers=admin_headers(client))
    assert grant.status_code == 200
    assert grant.json()["data"]["permissions"] == ["community:item:view", "dashboard:view"]

    # 非法权限码被拦截
    bad = await client.put(f"{ADMIN_BASE}/roles/{role_id}/permissions",
                           json={"permissions": ["not:a:permission"]},
                           headers=admin_headers(client))
    assert bad.status_code == 400

    perms = (await client.get(f"{ADMIN_BASE}/roles/{role_id}/permissions")).json()["data"]
    assert "community:item:view" in perms["permissions"]

    # 超管权限不可修改
    super_role = await db_session.scalar(select(Role).where(Role.code == "super_admin"))
    locked = await client.put(f"{ADMIN_BASE}/roles/{super_role.id}/permissions",
                              json={"permissions": []}, headers=admin_headers(client))
    assert locked.status_code == 422

    # 有成员的角色不可删除（先建管理员加入角色）
    admin_create = await client.post(f"{ADMIN_BASE}/admin-users", json={
        "username": "volunteer01", "password": "Volunteer@2025", "realName": "志愿者小王",
        "roleIds": [int(role_id)]}, headers=admin_headers(client))
    assert admin_create.status_code == 200
    delete_role = await client.delete(f"{ADMIN_BASE}/roles/{role_id}",
                                      headers=admin_headers(client))
    assert delete_role.status_code == 422

    # 权限树可读取（供角色配置页）
    tree = (await client.get(f"{ADMIN_BASE}/permissions/tree")).json()["data"]
    assert any(group["label"] == "community" for group in tree)


@pytest.mark.asyncio
async def test_admin_user_management(client, db_session):
    """管理员账号：创建（密码强度校验）/编辑/重置密码/超管保护。"""
    await admin_login(client)

    weak = await client.post(f"{ADMIN_BASE}/admin-users",
                             json={"username": "weak01", "password": "123456",
                                   "realName": "弱密码"}, headers=admin_headers(client))
    assert weak.status_code == 400

    create = await client.post(f"{ADMIN_BASE}/admin-users", json={
        "username": "operator01", "password": "Operator@2025A", "realName": "运营小李",
        "roleIds": []}, headers=admin_headers(client))
    assert create.status_code == 200
    admin_id = create.json()["data"]["id"]

    # 重置密码（当前仍是超管会话）
    reset = await client.post(f"{ADMIN_BASE}/admin-users/{admin_id}/reset-password",
                              json={"password": "Operator@2025B"}, headers=admin_headers(client))
    assert reset.status_code == 200

    # 新管理员用新密码可登录
    relogin = await client.post(f"{ADMIN_BASE}/auth/login",
                                json={"username": "operator01", "password": "Operator@2025B"})
    assert relogin.status_code == 200

    # 无权限管理员执行账号管理被拒（RBAC 生效）
    denied = await client.post(f"{ADMIN_BASE}/admin-users/{admin_id}/reset-password",
                               json={"password": "Operator@2025C"},
                               headers=admin_headers(client))
    assert denied.status_code == 403

    # 切回超管
    await admin_login(client)

    # 超管不可停用（系统至少保留 1 个可用超管）
    from src.db.models import AdminUser

    super_admin_id = (await db_session.scalar(
        select(AdminUser.id).where(AdminUser.username == "admin")))
    disable_super = await client.patch(f"{ADMIN_BASE}/admin-users/{super_admin_id}/status",
                                       json={"status": "DISABLED"},
                                       headers=admin_headers(client))
    assert disable_super.status_code == 422


@pytest.mark.asyncio
async def test_admin_user_unlock_and_delete(client, db_session):
    """管理员账号：手机号脱敏、登录锁定解除、单删/批量删除与超管保护。"""
    from datetime import timedelta

    from src.db.models import AdminUser
    from src.db.models.common import utcnow

    await admin_login(client)
    created = []
    for username in ("batch01", "batch02"):
        resp = await client.post(f"{ADMIN_BASE}/admin-users", json={
            "username": username, "password": "Batch@2025Pass", "realName": username,
            "phone": "13800001111"}, headers=admin_headers(client))
        assert resp.status_code == 200, resp.text
        created.append(resp.json()["data"])
    ids = [row["id"] for row in created]
    assert created[0]["phone"] == "138****1111"
    assert created[0]["locked"] is False

    # 模拟连续登录失败锁定 → 解锁清除锁定与失败次数
    row = await db_session.get(AdminUser, int(ids[0]))
    row.locked_until = utcnow() + timedelta(minutes=15)
    row.failed_attempts = 3
    await db_session.commit()
    unlock = await client.post(f"{ADMIN_BASE}/admin-users/{ids[0]}/unlock",
                               headers=admin_headers(client))
    assert unlock.status_code == 200, unlock.text
    assert unlock.json()["data"]["locked"] is False
    await db_session.refresh(row)
    assert row.failed_attempts == 0
    assert row.locked_until is None

    # 单个物理删除
    delete = await client.delete(f"{ADMIN_BASE}/admin-users/{ids[0]}",
                                 headers=admin_headers(client))
    assert delete.status_code == 200, delete.text
    db_session.expunge_all()
    assert await db_session.get(AdminUser, int(ids[0])) is None

    # 批量物理删除
    batch = await client.post(f"{ADMIN_BASE}/admin-users/batch-delete",
                              json={"ids": [int(ids[1])]}, headers=admin_headers(client))
    assert batch.status_code == 200, batch.text
    assert batch.json()["data"]["deleted"] == 1
    db_session.expunge_all()
    assert await db_session.get(AdminUser, int(ids[1])) is None

    # 超级管理员不可删除
    super_id = await db_session.scalar(
        select(AdminUser.id).where(AdminUser.username == "admin"))
    blocked = await client.delete(f"{ADMIN_BASE}/admin-users/{super_id}",
                                  headers=admin_headers(client))
    assert blocked.status_code == 422


@pytest.mark.asyncio
async def test_resource_pages_tree_detail_and_resource(client):
    """资源管理：页面树、页面详情、页面资源列表与新增资源。"""
    await admin_login(client)
    tree = (await client.get(f"{ADMIN_BASE}/pages/tree")).json()["data"]
    assert tree
    routes = [item["route"] for group in tree for item in group["items"]]
    assert "/system/resources" in routes
    assert "/system/users" in routes
    assert len(routes) == len(set(routes)), "同一路由不应重复展示"

    system_group = next(group for group in tree if group["label"] == "系统管理")
    page = next(item for item in system_group["items"] if item["route"] == "/system/resources")
    detail = (await client.get(f"{ADMIN_BASE}/pages/{page['id']}")).json()["data"]
    assert detail["code"] == "system:resource"
    assert detail["statusLabel"] == "页面已启用"
    assert detail["permissionCount"] >= 2

    resources = (await client.get(
        f"{ADMIN_BASE}/pages/{page['id']}/resources")).json()["data"]
    assert "system:resource:create" in [row["permissionCode"] for row in resources]

    created = await client.post(
        f"{ADMIN_BASE}/pages/{page['id']}/resources",
        json={"name": "导出资源清单", "type": "按钮"}, headers=admin_headers(client))
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["permissionCode"] == "system:resource:custom1"
    assert data["status"] == "启用"

    # 新资源进入权限表，可在权限树中用于角色授权
    tree_perms = (await client.get(f"{ADMIN_BASE}/permissions/tree")).json()["data"]
    codes = [item["code"] for group in tree_perms for item in group["items"]]
    assert "system:resource:custom1" in codes


@pytest.mark.asyncio
async def test_export_flow(client):
    """W08-03：导出任务生成 CSV（默认脱敏）→ 下载写审计。"""
    await verified_user(client, "13944440003")
    await admin_login(client)

    create = await client.post(f"{ADMIN_BASE}/exports", json={"type": "USERS"},
                               headers=admin_headers(client))
    assert create.status_code == 200, create.text
    job_id = create.json()["data"]["id"]
    assert create.json()["data"]["rows"] >= 1

    download = await client.get(f"{ADMIN_BASE}/exports/{job_id}/download")
    assert download.status_code == 200
    content = download.text
    assert "手机号(脱敏)" in content
    assert "139****0003" in content  # 脱敏，不含明文

    # 下载行为入审计


    # 通过审计列表验证（不直接查库）
    logs = (await client.get(f"{ADMIN_BASE}/audit-logs",
                             params={"action": "export.download"})).json()["data"]
    assert logs["total"] >= 1


@pytest.mark.asyncio
async def test_websocket_auth_and_ping(client):
    """WS 握手鉴权与心跳（详设 10.3）：无 token → 4401 关闭；合法 token → PONG。"""
    pytest.importorskip("httpx_ws")
    from httpx import AsyncClient
    from httpx_ws import aconnect_ws
    from httpx_ws.transport import ASGIWebSocketTransport

    from src.main import app

    transport = ASGIWebSocketTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ws_client:
        # 无 token 拒绝（4401 关闭）
        from httpx_ws import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            async with aconnect_ws("/api/v1/ws", ws_client) as _ws:
                await _ws.receive_text()

        user = await register_user(client, "13944440005")
        async with aconnect_ws(f"/api/v1/ws?token={user['token']}", ws_client) as ws:
            import json

            first = json.loads(await ws.receive_text())
            assert first["type"] == "PONG"
            await ws.send_text(json.dumps({"type": "PING", "data": {}}))
            pong = json.loads(await ws.receive_text())
            assert pong["type"] == "PONG"
