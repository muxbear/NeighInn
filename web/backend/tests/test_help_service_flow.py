"""邻里互助全流程：求助直发、服务送审、后台分类处理与媒体编辑/删除。"""

from __future__ import annotations

import pytest

from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_headers,
    bearer,
    verified_user,
)


def _service_payload(kind: str, title: str, **overrides) -> dict:
    payload = {
        "kind": kind,
        "category": "邻里帮忙",
        "title": title,
        "description": "同小区邻居之间互助，请在公共区域交接并注意安全。",
        "expectedTime": "本周内",
        "location": "8 号楼大堂",
        "reward": "邻里互助",
        "media": ["uploads/public/help-1.jpg", "uploads/public/help-2.jpg"],
        "mediaType": "GALLERY",
        "coverKey": "uploads/public/help-1.jpg",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_help_service_review_and_management_flow(client, db_session):
    account = await verified_user(client, "13900002222")
    token = account["token"]

    # 1. 求助默认直接发布，并立即可在移动端列表看到。
    help_resp = await client.post(
        f"{C_BASE}/services", json=_service_payload("HELP", "帮忙代取一次快递"),
        headers=bearer(token))
    assert help_resp.status_code == 200, help_resp.text
    help_data = help_resp.json()["data"]
    assert help_data["status"] == "OPEN"
    assert help_data["mediaKeys"] == ["uploads/public/help-1.jpg", "uploads/public/help-2.jpg"]
    help_id = help_data["id"]

    visible = (await client.get(f"{C_BASE}/services", headers=bearer(token))).json()["data"]
    assert any(row["id"] == help_id for row in visible["items"])

    # 2. 邻里服务进入待审核，审核前移动端不可见。
    offer_resp = await client.post(
        f"{C_BASE}/services",
        json=_service_payload("OFFER", "可提供小学语文辅导", media=["uploads/public/offer.mp4"],
                              mediaType="VIDEO", coverKey="uploads/public/offer.mp4"),
        headers=bearer(token))
    assert offer_resp.status_code == 200, offer_resp.text
    offer_data = offer_resp.json()["data"]
    offer_id = offer_data["id"]
    assert offer_data["status"] == "PENDING_REVIEW"

    visible = (await client.get(f"{C_BASE}/services", headers=bearer(token))).json()["data"]
    assert all(row["id"] != offer_id for row in visible["items"])

    mixed = await client.post(
        f"{C_BASE}/services",
        json=_service_payload("OFFER", "图片视频混排测试", media=[
            "uploads/public/help-1.jpg", "uploads/public/offer.mp4",
        ]),
        headers=bearer(token))
    assert mixed.status_code == 400
    assert "不能混排" in mixed.json()["message"]

    # 3. 后台按类型/状态分类查询，并出现「邻里服务待审核」消息通知。
    listing = await client.get(f"{ADMIN_BASE}/help-requests",
                               params={"kind": "OFFER", "status": "PENDING_REVIEW"})
    assert listing.status_code == 200, listing.text
    rows = listing.json()["data"]["items"]
    assert any(row["id"] == offer_id for row in rows)

    todos = (await client.get(f"{ADMIN_BASE}/dashboard/todos")).json()["data"]
    service_todo = next((item for item in todos if item["key"] == "help_service"), None)
    assert service_todo is not None
    assert service_todo["count"] >= 1
    assert "kind=OFFER" in service_todo["route"]
    assert service_todo["communityId"] is not None
    assert f"communityId={service_todo['communityId']}" in service_todo["route"]

    # 4. 全字段编辑：标题、分类、时间、地点、酬谢、类型与图片/视频均可改。
    update = await client.put(
        f"{ADMIN_BASE}/help-requests/{offer_id}",
        json={
            "kind": "OFFER",
            "category": "学习陪伴",
            "title": "退休教师可辅导小学语文（已更新）",
            "description": "每周六下午可提供一对一辅导，地点在小区活动室。",
            "expectedTime": "周六 14:00–16:00",
            "location": "小区活动室 2 楼",
            "reward": "邻里价 80 元/次",
            "urgent": True,
            "media": ["uploads/public/offer-2.jpg", "uploads/public/offer-3.jpg"],
            "mediaType": "GALLERY",
            "coverKey": "uploads/public/offer-3.jpg",
        },
        headers=admin_headers(client))
    assert update.status_code == 200, update.text
    updated = update.json()["data"]
    assert updated["title"].endswith("（已更新）")
    assert updated["category"] == "学习陪伴"
    assert updated["urgent"] is True
    assert updated["mediaKeys"] == ["uploads/public/offer-2.jpg", "uploads/public/offer-3.jpg"]
    assert updated["coverKey"] == "uploads/public/offer-3.jpg"

    # 5. 审核通过后服务进入待响应并展示到移动端。
    review = await client.post(
        f"{ADMIN_BASE}/help-requests/{offer_id}/review",
        json={"decision": "APPROVE"}, headers=admin_headers(client))
    assert review.status_code == 200, review.text
    assert review.json()["data"]["status"] == "OPEN"
    visible = (await client.get(f"{C_BASE}/services", params={"kind": "提供"},
                                headers=bearer(token))).json()["data"]
    assert any(row["id"] == offer_id for row in visible["items"])

    # 6. 驳回必须填写原因，且驳回后移动端不可见。
    rejected_resp = await client.post(
        f"{C_BASE}/services", json=_service_payload("OFFER", "可提供上门保洁"),
        headers=bearer(token))
    rejected_id = rejected_resp.json()["data"]["id"]
    bad_reject = await client.post(
        f"{ADMIN_BASE}/help-requests/{rejected_id}/review",
        json={"decision": "REJECT", "reason": "不行"}, headers=admin_headers(client))
    assert bad_reject.status_code == 400
    good_reject = await client.post(
        f"{ADMIN_BASE}/help-requests/{rejected_id}/review",
        json={"decision": "REJECT", "reason": "请补充保洁服务资质与收费标准"},
        headers=admin_headers(client))
    assert good_reject.status_code == 200
    assert good_reject.json()["data"]["status"] == "REJECTED"

    # 7. 单条删除与批量删除。
    single = await client.delete(f"{ADMIN_BASE}/help-requests/{rejected_id}",
                                 headers=admin_headers(client))
    assert single.status_code == 200, single.text

    batch_ids = []
    for index in range(2):
        created = await client.post(
            f"{C_BASE}/services",
            json=_service_payload("HELP", f"批量删除测试求助 {index}"),
            headers=bearer(token))
        batch_ids.append(int(created.json()["data"]["id"]))
    batch = await client.post(f"{ADMIN_BASE}/help-requests/batch-delete",
                              json={"ids": batch_ids}, headers=admin_headers(client))
    assert batch.status_code == 200, batch.text
    result = batch.json()["data"]
    assert set(result["deleted"]) == {str(item) for item in batch_ids}
    assert result["failed"] == []

    remaining = (await client.get(f"{ADMIN_BASE}/help-requests",
                                  params={"kind": "HELP"})).json()["data"]["items"]
    remaining_ids = {int(row["id"]) for row in remaining}
    assert not remaining_ids.intersection(batch_ids)


@pytest.mark.asyncio
async def test_help_overview_uses_real_metrics(client):
    """互助概览按真实数据聚合：今日求助、待响应、本周完成与社区信用分。"""
    requester = await verified_user(client, "13900003333")
    helper = await verified_user(client, "13900004444")
    csrf = admin_headers(client)

    completed = await client.post(
        f"{C_BASE}/services",
        json=_service_payload("HELP", "帮忙接送孩子", category="接送照看"),
        headers=bearer(requester["token"]))
    assert completed.status_code == 200, completed.text
    completed_id = completed.json()["data"]["id"]

    pending = await client.post(
        f"{C_BASE}/services",
        json=_service_payload("HELP", "借用家用梯子", category="物品借用"),
        headers=bearer(requester["token"]))
    assert pending.status_code == 200, pending.text

    offer = await client.post(
        f"{C_BASE}/services",
        json=_service_payload("OFFER", "可提供小学语文辅导", category="学习陪伴"),
        headers=bearer(requester["token"]))
    assert offer.status_code == 200, offer.text

    responded = await client.post(
        f"{C_BASE}/services/{completed_id}/respond", headers=bearer(helper["token"]))
    assert responded.status_code == 200, responded.text
    matched = await client.post(
        f"{ADMIN_BASE}/help-requests/{completed_id}/match",
        json={"responderId": int(helper["profile"]["id"])}, headers=csrf)
    assert matched.status_code == 200, matched.text
    closed = await client.post(
        f"{ADMIN_BASE}/help-requests/{completed_id}/close",
        json={"completed": True, "reason": "已完成"}, headers=csrf)
    assert closed.status_code == 200, closed.text

    overview = (await client.get(
        f"{ADMIN_BASE}/operations/overview",
        params={"module": "help", "communityId": 1},
        headers=csrf,
    )).json()["data"]
    metrics = overview["metrics"]
    assert overview["total"] == 3
    assert overview["statusCounts"] == {"OPEN": 1, "PENDING_REVIEW": 1, "COMPLETED": 1}
    assert metrics["todayHelp"] == 2
    assert metrics["urgentHelp"] == 0
    assert metrics["pendingResponse"] == 1
    assert metrics["pendingAvgMinutes"] >= 0
    assert metrics["weekCompleted"] == 1
    assert metrics["weekClosed"] == 0
    assert metrics["completionRate"] == 100.0
    assert metrics["creditScore"] == 100.0
