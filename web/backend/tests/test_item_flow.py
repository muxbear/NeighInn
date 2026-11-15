"""物品域集成测试（M03/M04 发布与 AI 质检 + W03-01 人工复核，对应 AC-02）。

覆盖：发布校验 → AI 质检（通过/驳回/转人工/快车道）→ 人工复核（通过/驳回/降级）→
上架可见性 → 违规下架/批量下架 → 留言/收藏/续期/距离。
"""

import pytest
from sqlalchemy import select

from src.db.models import AppNotification, Item
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_login,
    bearer,
    create_draft,
    register_user,
    submit_item,
    verified_user,
)


@pytest.mark.asyncio
async def test_create_requires_verified_owner(client):
    """BR-02/AC-03：未完成认证的账号无法发布（40304）。"""
    account = await register_user(client, "13911110001")
    resp = await client.post(f"{C_BASE}/items", json={
        "title": "测试物品", "tradeType": "MONETARY", "priceCents": 100,
        "qualityDesc": "质量说明超过二十个字的描述文本内容",
        "images": ["a.jpg", "b.jpg", "c.jpg"], "condition": "九九新",
    }, headers=bearer(account["token"]))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40304


@pytest.mark.asyncio
async def test_create_validation_rules(client):
    user = await verified_user(client, "13911110002")
    headers = bearer(user["token"])

    # 照片不足 3 张（BR-05）
    resp = await client.post(f"{C_BASE}/items", json={
        "title": "测试", "tradeType": "MONETARY", "priceCents": 100,
        "qualityDesc": "质量说明超过二十个字的描述文本内容", "images": ["a.jpg"],
        "condition": "九九新"}, headers=headers)
    assert resp.status_code == 400 and resp.json()["code"] == 40001

    # 质量说明不足 20 字（M03-01）
    resp = await client.post(f"{C_BASE}/items", json={
        "title": "测试", "tradeType": "MONETARY", "priceCents": 100,
        "qualityDesc": "太短", "images": ["a.jpg", "b.jpg", "c.jpg"],
        "condition": "九九新"}, headers=headers)
    assert resp.status_code == 400

    # 免费赠与价格必须为 0（BR-12）
    resp = await client.post(f"{C_BASE}/items", json={
        "title": "儿童绘本 30 册", "tradeType": "FREE_GIFT", "priceCents": 500,
        "qualityDesc": "九成新的儿童绘本，共三十册，无缺页无涂画内容完整。",
        "images": ["a.jpg", "b.jpg", "c.jpg"], "condition": "九九新"}, headers=headers)
    assert resp.status_code == 400

    # 互换必填期望交换描述（BR-13）
    resp = await client.post(f"{C_BASE}/items", json={
        "title": "露营折叠椅两把", "tradeType": "BARTER", "barterExpect": "",
        "qualityDesc": "八成新折叠椅，结构稳固无松动，收纳方便适合露营。",
        "images": ["a.jpg", "b.jpg", "c.jpg"], "condition": "轻微使用痕迹"}, headers=headers)
    assert resp.status_code == 400

    # 只能发布到本小区（BR-02/AC-03）
    resp = await client.post(f"{C_BASE}/items", json={
        "title": "测试", "tradeType": "MONETARY", "priceCents": 100,
        "qualityDesc": "质量说明超过二十个字的描述文本内容",
        "images": ["a.jpg", "b.jpg", "c.jpg"], "condition": "九九新",
        "communityId": 2}, headers=headers)
    assert resp.status_code == 422 and resp.json()["code"] == 42201


@pytest.mark.asyncio
async def test_publish_review_approve_and_visibility(client, db_session):
    """AC-02 主链路：达标物品经 AI + 人工复核后上架，买家可见。"""
    seller = await verified_user(client, "13911110003")
    buyer = await register_user(client, "13911110004")

    item_id = await create_draft(client, seller["token"])
    result = await submit_item(client, seller["token"], item_id)
    assert result["status"] == "PENDING_REVIEW"  # 3 张照片置信度 0.74 < 快车道阈值

    # 复核中物品对其他用户不可见（404）
    hidden = await client.get(f"{C_BASE}/items/{item_id}", headers=bearer(buyer["token"]))
    assert hidden.status_code == 404
    mine = await client.get(f"{C_BASE}/items/{item_id}", headers=bearer(seller["token"]))
    assert mine.status_code == 200

    # 管理端复核队列与 AI 报告
    csrf = await admin_login(client)
    queue = await client.get(f"{ADMIN_BASE}/items",
                             params={"status": "PENDING_REVIEW"})
    assert any(row["id"] == item_id for row in queue.json()["data"]["items"])

    audit = await client.get(f"{ADMIN_BASE}/items/{item_id}/ai-audit")
    report = audit.json()["data"]
    assert report["overall"] == "PASS"
    assert report["traceId"]
    assert len(report["dimensions"]) == 4  # 图像质量/图文一致性/合规性/成色建议（SRS 7）

    # 人工复核通过 + 加热门推荐（W03-01）
    resp = await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                             json={"decision": "APPROVE", "recommend": True}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "ON_SALE"
    assert resp.json()["data"]["recommended"] is True

    # 买家在信息流可见（本小区默认 feed）
    feed = await client.get(f"{C_BASE}/items", headers=bearer(buyer["token"]))
    assert any(row["id"] == item_id for row in feed.json()["data"]["items"])

    detail = (await client.get(f"{C_BASE}/items/{item_id}",
                               headers=bearer(buyer["token"]))).json()["data"]
    assert detail["status"] == "ON_SALE"
    assert detail["price"] == 128.0  # 分转元
    assert detail["type"] == "出售"
    assert detail["tradeTypeCode"] == "MONETARY"
    assert detail["seller"]["verified"] is True
    assert detail["aiVerified"] is True
    assert detail["viewCount"] == 1

    # 上架通知（M03/M01-04 类通知）
    note = await db_session.scalar(
        select(AppNotification)
        .where(AppNotification.user_id == int(seller["profile"]["id"]))
        .order_by(AppNotification.id.desc()))
    assert note is not None and "上架" in note.title


@pytest.mark.asyncio
async def test_fast_track_high_confidence_goes_on_sale_directly(client):
    """W03-01 快车道：高置信度（≥ 阈值）免人工复核直接上架。"""
    seller = await verified_user(client, "13911110005")
    item_id = await create_draft(
        client, seller["token"],
        images=[f"items/chair-{i}.jpg" for i in range(1, 10)],
        videoUrl="items/chair-video.mp4", invoices=["items/chair-invoice.jpg"],
    )
    result = await submit_item(client, seller["token"], item_id)
    assert result["status"] == "ON_SALE"  # 置信度 0.99 ≥ 0.95 阈值


@pytest.mark.asyncio
async def test_ai_fail_banned_keyword_and_resubmit(client):
    """AC-02：禁售品被 AI 正确拦截并给出改进建议（BR-04/A-03/A-08）。"""
    seller = await verified_user(client, "13911110006")
    item_id = await create_draft(client, seller["token"],
                                 title="转让管制刀具一把",
                                 qualityDesc="几乎全新的刀具，非常锋利，包装完整说明书齐全。")
    result = await submit_item(client, seller["token"], item_id)
    assert result["status"] == "AI_REJECTED"

    progress = (await client.get(f"{C_BASE}/items/{item_id}/audit-progress",
                                 headers=bearer(seller["token"]))).json()["data"]
    assert progress["status"] == "REJECTED"
    assert progress["report"]["passed"] is False
    assert any("禁售" in reason for reason in progress["rejectReasons"])
    assert progress["report"]["traceId"]

    # 编辑修改后重新提交（A-08：一键返回修改）
    edit = await client.put(f"{C_BASE}/items/{item_id}", json={
        "title": "转让户外多功能工具钳",
        "tradeType": "MONETARY", "priceCents": 12800,
        "qualityDesc": "九成新多功能工具钳，含钳子螺丝刀开瓶器，户外露营必备。",
        "images": ["items/tool-1.jpg", "items/tool-2.jpg", "items/tool-3.jpg"],
        "condition": "九九新"}, headers=bearer(seller["token"]))
    assert edit.status_code == 200
    assert edit.json()["data"]["status"] == "DRAFT"

    result = await submit_item(client, seller["token"], item_id)
    assert result["status"] == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_ai_fail_bad_photo_quality(client):
    """A-01：模糊/过暗照片被逐张识别并驳回（M03-05 改进建议）。"""
    seller = await verified_user(client, "13911110007")
    item_id = await create_draft(
        client, seller["token"],
        images=["items/blur-main.jpg", "items/dark-detail.jpg", "items/ok-3.jpg"])
    result = await submit_item(client, seller["token"], item_id)
    assert result["status"] == "AI_REJECTED"

    progress = (await client.get(f"{C_BASE}/items/{item_id}/audit-progress",
                                 headers=bearer(seller["token"]))).json()["data"]
    reasons = "；".join(progress["rejectReasons"])
    assert "模糊" in reasons and "过暗" in reasons


@pytest.mark.asyncio
async def test_ai_fail_description_condition_conflict(client):
    """A-02：图文不一致（描述全新 vs 成色有缺陷）被驳回。"""
    seller = await verified_user(client, "13911110008")
    item_id = await create_draft(
        client, seller["token"], title="全新未拆封电饭煲",
        condition="有功能缺陷",
        qualityDesc="全新未拆封，但加热功能异常需要维修后才能正常使用。")
    result = await submit_item(client, seller["token"], item_id)
    assert result["status"] == "AI_REJECTED"


@pytest.mark.asyncio
async def test_sensitive_content_goes_to_human_review(client):
    """A-01 注：疑似联系方式导流转人工复核而非直接驳回（避免误杀）。"""
    seller = await verified_user(client, "13911110009")
    item_id = await create_draft(
        client, seller["token"],
        qualityDesc="成色很好没有瑕疵，需要的邻居可以加我微信私聊详谈价格。")
    result = await submit_item(client, seller["token"], item_id)
    assert result["status"] == "PENDING_REVIEW"

    audit = (await client.get(f"{C_BASE}/items/{item_id}/audit-progress",
                              headers=bearer(seller["token"]))).json()["data"]
    assert audit["report"]["passed"] is True
    assert audit["report"]["risks"], "应包含导流风险提示"


@pytest.mark.asyncio
async def test_admin_reject_and_edit_resubmit_cycle(client, db_session):
    """W03-01：人工驳回（原因必填）→ 卖家修改 → 重新质检。"""
    seller = await verified_user(client, "13911110010")
    item_id = await create_draft(client, seller["token"])
    await submit_item(client, seller["token"], item_id)
    csrf = await admin_login(client)

    short = await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                              json={"decision": "REJECT", "reason": "差"}, headers=csrf)
    assert short.status_code == 400

    reason = "照片无法看清物品细节，请补充缺陷处特写照片"
    resp = await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                             json={"decision": "REJECT", "reason": reason}, headers=csrf)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "REJECTED"

    # 复核结论回流质检记录（A-10 标注样本）
    audit = (await client.get(f"{ADMIN_BASE}/items/{item_id}/ai-audit")).json()["data"]
    assert audit["decision"] == "REJECT"
    assert audit["reviewNote"] == reason


@pytest.mark.asyncio
async def test_admin_offline_and_batch_offline(client, db_session):
    """W03-03：违规下架（原因必填 + 通知）与巡检批量下架（成功/失败明细）。"""
    seller = await verified_user(client, "13911110011")
    item_a = await create_draft(client, seller["token"], title="九成新儿童平衡车")
    item_b = await create_draft(client, seller["token"], title="儿童绘本 30 册",
                                tradeType="FREE_GIFT", priceCents=0)
    for item_id in (item_a, item_b):
        await submit_item(client, seller["token"], item_id)
    csrf = await admin_login(client)
    for item_id in (item_a, item_b):
        await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                          json={"decision": "APPROVE"}, headers=csrf)

    # 下架原因必填
    no_reason = await client.post(f"{ADMIN_BASE}/items/{item_a}/offline",
                                  json={"reason": ""}, headers=csrf)
    assert no_reason.status_code == 400

    resp = await client.post(f"{ADMIN_BASE}/items/{item_b}/offline",
                             json={"reason": "接到举报：图片与实物严重不符"}, headers=csrf)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "OFF_SHELF"

    # 批量下架：一个不存在的 ID 进入失败明细
    resp = await client.post(f"{ADMIN_BASE}/items/batch-offline",
                             json={"ids": [int(item_a), 999999],
                                   "reason": "巡检抽检不合格"}, headers=csrf)
    data = resp.json()["data"]
    assert data["success"] == 1 and data["failed"] == 1
    assert data["failures"][0]["id"] == "999999"


@pytest.mark.asyncio
async def test_comments_and_favorite(client):
    """M05-01/BR-14：留言公开可见、违禁内容拦截、卖家可删恶意留言；收藏切换。"""
    seller = await verified_user(client, "13911110012")
    buyer = await register_user(client, "13911110013")
    item_id = await create_draft(client, seller["token"])
    await submit_item(client, seller["token"], item_id)
    csrf = await admin_login(client)
    await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                      json={"decision": "APPROVE"}, headers=csrf)

    # 正常留言
    resp = await client.post(f"{C_BASE}/items/{item_id}/comments",
                             json={"content": "请问最低多少钱出？"},
                             headers=bearer(buyer["token"]))
    assert resp.status_code == 200
    comment_id = resp.json()["data"]["id"]

    # 违禁留言被内容安全审核拦截（A-09）
    bad = await client.post(f"{C_BASE}/items/{item_id}/comments",
                            json={"content": "出售处方药，需要联系"},
                            headers=bearer(buyer["token"]))
    assert bad.status_code == 422 and bad.json()["code"] == 42201

    comments = (await client.get(f"{C_BASE}/items/{item_id}/comments",
                                 headers=bearer(buyer["token"]))).json()["data"]
    assert len(comments) == 1 and comments[0]["content"] == "请问最低多少钱出？"

    # 卖家删除恶意留言（BR-14）
    delete = await client.delete(f"{C_BASE}/comments/{comment_id}",
                                 headers=bearer(seller["token"]))
    assert delete.status_code == 200
    comments = (await client.get(f"{C_BASE}/items/{item_id}/comments",
                                 headers=bearer(buyer["token"]))).json()["data"]
    assert comments == []

    # 收藏切换
    fav = await client.post(f"{C_BASE}/items/{item_id}/favorite",
                            headers=bearer(buyer["token"]))
    assert fav.json()["data"]["favorite"] is True
    detail = (await client.get(f"{C_BASE}/items/{item_id}",
                               headers=bearer(buyer["token"]))).json()["data"]
    assert detail["favorite"] is True
    fav = await client.post(f"{C_BASE}/items/{item_id}/favorite",
                            headers=bearer(buyer["token"]))
    assert fav.json()["data"]["favorite"] is False


@pytest.mark.asyncio
async def test_renew_expired_item(client, db_session):
    """BR-07：到期物品续期后重新上架 30 天。"""
    from src.db.models.common import utcnow

    seller = await verified_user(client, "13911110014")
    item_id = await create_draft(client, seller["token"])
    await submit_item(client, seller["token"], item_id)
    csrf = await admin_login(client)
    await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                      json={"decision": "APPROVE"}, headers=csrf)

    item = await db_session.get(Item, int(item_id))
    item.status = "EXPIRED"
    item.expires_at = utcnow()
    await db_session.commit()

    resp = await client.post(f"{C_BASE}/items/{item_id}/renew",
                             headers=bearer(seller["token"]))
    assert resp.status_code == 200
    await db_session.refresh(item)
    assert item.status == "ON_SALE"
    assert item.expires_at > utcnow()


@pytest.mark.asyncio
async def test_distance_endpoint(client):
    """SRS 8.2：距离与三种耗时（降级标注预估）。"""
    seller = await verified_user(client, "13911110015")
    buyer = await verified_user(client, "13911110016", community_id=2)
    item_id = await create_draft(client, seller["token"])
    await submit_item(client, seller["token"], item_id)
    csrf = await admin_login(client)
    await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                      json={"decision": "APPROVE"}, headers=csrf)

    resp = await client.get(f"{C_BASE}/items/{item_id}/distance",
                            headers=bearer(buyer["token"]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["meters"] > 0
    assert data["distance"].startswith("约")
    assert data["walk"].startswith("步行")
    assert data["bike"].startswith("骑行")
    assert data["car"].startswith("驾车")
    assert data["estimated"] is True


@pytest.mark.asyncio
async def test_off_shelf_and_delete_guards(client):
    """上架中不可直接删除；下架后可删除。"""
    seller = await verified_user(client, "13911110017")
    item_id = await create_draft(client, seller["token"])
    await submit_item(client, seller["token"], item_id)
    csrf = await admin_login(client)
    await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                      json={"decision": "APPROVE"}, headers=csrf)

    bad = await client.delete(f"{C_BASE}/items/{item_id}", headers=bearer(seller["token"]))
    assert bad.status_code == 422

    off = await client.post(f"{C_BASE}/items/{item_id}/off-shelf",
                            headers=bearer(seller["token"]))
    assert off.status_code == 200
    delete = await client.delete(f"{C_BASE}/items/{item_id}", headers=bearer(seller["token"]))
    assert delete.status_code == 200


@pytest.mark.asyncio
async def test_category_management(client):
    """W04-03：类目树读取与新增（两级）。"""
    csrf = await admin_login(client)
    tree = (await client.get(f"{ADMIN_BASE}/item-categories")).json()["data"]
    assert len(tree) == 7  # 种子一级类目（SRS M02-01）
    assert any(node["name"] == "母婴用品" for node in tree)

    resp = await client.post(f"{ADMIN_BASE}/item-categories",
                             json={"name": "二手图书专区", "sort": 99}, headers=csrf)
    assert resp.status_code == 200
    dup = await client.post(f"{ADMIN_BASE}/item-categories",
                            json={"name": "二手图书专区"}, headers=csrf)
    assert dup.status_code == 409
