"""后台认证待办与统计接口测试。"""

import pytest

from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_login,
    bearer,
    first_pending_cert,
    register_user,
)


@pytest.mark.asyncio
async def test_certification_todo_counts_summary_and_disappears(client):
    account = await register_user(client)
    headers = bearer(account["token"])
    await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/id-front.jpg", "backImage": "certs/id-back.jpg"},
        headers=headers,
    )
    await client.post(
        f"{C_BASE}/auth/owner-proof",
        json={"communityId": 1, "identity": "owner",
              "images": ["certs/proof-front.jpg"]},
        headers=headers,
    )
    csrf = await admin_login(client)

    todos = (await client.get(f"{ADMIN_BASE}/dashboard/todos", headers=csrf)).json()["data"]
    cert_todo = next(item for item in todos if item["key"] == "certification")
    assert cert_todo["count"] == 2
    assert cert_todo["breakdown"] == {"REALNAME": 1, "OWNER_PROOF": 1}
    assert cert_todo["latestCertId"]

    summary = (await client.get(
        f"{ADMIN_BASE}/certifications/summary", headers=csrf)).json()["data"]
    assert summary["pending"] == 2
    assert summary["pendingRealname"] == 1
    assert summary["pendingOwner"] == 1

    # 审核队列支持按手机号精确检索，且待办随审批实时减少。
    realname = await first_pending_cert(client, csrf, "REALNAME")
    await client.post(
        f"{ADMIN_BASE}/certifications/{realname['id']}/approve", headers=csrf)
    todos = (await client.get(f"{ADMIN_BASE}/dashboard/todos", headers=csrf)).json()["data"]
    cert_todo = next(item for item in todos if item["key"] == "certification")
    assert cert_todo["count"] == 1
    assert cert_todo["breakdown"] == {"OWNER_PROOF": 1}

    owner = await first_pending_cert(client, csrf, "OWNER_PROOF")
    await client.post(
        f"{ADMIN_BASE}/certifications/{owner['id']}/approve", headers=csrf)
    todos = (await client.get(f"{ADMIN_BASE}/dashboard/todos", headers=csrf)).json()["data"]
    cert_todo = next(item for item in todos if item["key"] == "certification")
    assert cert_todo["count"] == 0


@pytest.mark.asyncio
async def test_certification_list_keyword_search(client):
    account = await register_user(client, "13900003333")
    await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/f.jpg", "backImage": "certs/b.jpg"},
        headers=bearer(account["token"]),
    )
    csrf = await admin_login(client)
    resp = await client.get(
        f"{ADMIN_BASE}/certifications",
        params={"status": "PENDING", "keyword": "13900003333"},
        headers=csrf,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total"] == 1
    assert resp.json()["data"]["items"][0]["typeLabel"] == "实名认证"
