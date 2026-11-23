"""移动端申请添加小区 → 后台社区运维审批闭环。

覆盖：申请落 PENDING 档案、C 端审核前不可见、后台待办计数、通过后 C 端可选、
驳回后可重新申请、街道归属校验与重复申请拦截。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.db.models import Community, Region
from tests.conftest import ADMIN_BASE, C_BASE, admin_login, bearer, register_user

APPLY_NAME = "申请测试花园"


async def _region_id(db_session, code: str) -> int:
    region = await db_session.scalar(select(Region).where(Region.code == code))
    assert region is not None
    return int(region.id)


async def _apply(client, token: str, name: str, region_id: int, street_id: int | None = None):
    payload = {"name": name, "regionId": region_id}
    if street_id:
        payload["streetId"] = street_id
    return await client.post(f"{C_BASE}/communities/apply", json=payload,
                             headers=bearer(token))


@pytest.mark.asyncio
async def test_apply_community_pending_then_admin_approves(client, db_session):
    account = await register_user(client, "13988880001")
    xihu = await _region_id(db_session, "330106")
    wenxin = await _region_id(db_session, "330106001")

    # 街道不属于该区县 → 拒绝
    bad = await _apply(client, account["token"], APPLY_NAME, xihu,
                       await _region_id(db_session, "330102001"))
    assert bad.status_code == 400

    resp = await _apply(client, account["token"], APPLY_NAME, xihu, wenxin)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "PENDING"
    assert data["regionPath"].endswith("文新街道")

    # 重复申请被拦截
    dup = await _apply(client, account["token"], APPLY_NAME, xihu, wenxin)
    assert dup.status_code == 409
    assert dup.json()["code"] == 40901

    # C 端收录前不可见
    search = await client.get(f"{C_BASE}/communities/search",
                              params={"keyword": APPLY_NAME},
                              headers=bearer(account["token"]))
    assert search.status_code == 200
    assert all(row["name"] != APPLY_NAME for row in search.json()["data"])

    # 后台社区运维可见待审批记录
    csrf = await admin_login(client)
    listing = await client.get(f"{ADMIN_BASE}/communities",
                               params={"status": "PENDING", "pageSize": 50})
    assert listing.status_code == 200, listing.text
    row = next(item for item in listing.json()["data"]["items"] if item["name"] == APPLY_NAME)
    assert row["status"] == "PENDING"

    # 待办提醒包含「小区添加待审批」
    todos = (await client.get(f"{ADMIN_BASE}/dashboard/todos")).json()["data"]
    todo = next(item for item in todos if item["key"] == "community_application")
    assert todo["count"] >= 1
    assert todo["route"].startswith("/community-management/maintenance")

    # 审批通过 → 正常运营，C 端立即可选
    approve = await client.post(f"{ADMIN_BASE}/communities/{row['id']}/review",
                                json={"decision": "APPROVE"}, headers=csrf)
    assert approve.status_code == 200, approve.text
    assert approve.json()["data"]["status"] == "OPERATING"

    search = await client.get(f"{C_BASE}/communities/search",
                              params={"keyword": APPLY_NAME},
                              headers=bearer(account["token"]))
    assert [item["name"] for item in search.json()["data"]] == [APPLY_NAME]

    todos = (await client.get(f"{ADMIN_BASE}/dashboard/todos")).json()["data"]
    todo = next(item for item in todos if item["key"] == "community_application")
    assert todo["count"] == 0

    # 非待审批状态不能重复审批
    again = await client.post(f"{ADMIN_BASE}/communities/{row['id']}/review",
                              json={"decision": "APPROVE"}, headers=csrf)
    assert again.status_code == 422


@pytest.mark.asyncio
async def test_rejected_application_can_resubmit(client, db_session):
    account = await register_user(client, "13988880002")
    xihu = await _region_id(db_session, "330106")

    resp = await _apply(client, account["token"], "驳回后重提花园", xihu)
    assert resp.status_code == 200, resp.text
    community_id = int(resp.json()["data"]["id"])

    csrf = await admin_login(client)
    reject = await client.post(f"{ADMIN_BASE}/communities/{community_id}/review",
                               json={"decision": "REJECT", "note": "名称与区划不符"},
                               headers=csrf)
    assert reject.status_code == 200, reject.text
    assert reject.json()["data"]["status"] == "REJECTED"

    db_session.expire_all()
    community = await db_session.get(Community, community_id)
    assert community.status == "REJECTED"

    # 驳回后允许重新提交同名申请
    again = await _apply(client, account["token"], "驳回后重提花园", xihu)
    assert again.status_code == 200, again.text
    assert again.json()["data"]["status"] == "PENDING"
