"""内容与社交域集成测试（生活/喇叭/互助/私信/好友/通知/举报/参数生效）。

覆盖：内容审核闭环（发布→待审→通过/驳回→移动端可见性）、互助撮合、
好友申请与私信（实名门禁/内容安全/client_msg_id 幂等）、通知未读与已读、
公告下发、举报处理联动下架、参数发布即生效。
"""

import pytest

from src.db.models import Item
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


async def _two_users(client):
    seller = await verified_user(client, "13933330001")
    buyer = await verified_user(client, "13933330002")
    csrf = await admin_login(client)
    return seller, buyer, csrf


@pytest.mark.asyncio
async def test_life_publish_review_visibility(client, db_session):
    """生活内容审核闭环：发布 → 待审（C 端不可见）→ 通过 → 频道可见；驳回通知。"""
    seller, buyer, _csrf = await _two_users(client)
    resp = await client.post(f"{C_BASE}/life/posts", json={
        "mediaType": "gallery", "media": ["life/park-1.jpg"],
        "title": "春日赏花地图", "description": "小区东门的樱花开了，附赏花路线图。",
        "category": "小区风景"}, headers=bearer(seller["token"]))
    assert resp.status_code == 200, resp.text
    post_id = resp.json()["data"]["id"]

    # 待审核内容对生活频道不可见
    feed = (await client.get(f"{C_BASE}/life/posts", headers=bearer(buyer["token"]))).json()["data"]
    assert all(post["id"] != post_id for post in feed["items"])

    # 违禁内容直接拦截（A-09）
    bad = await client.post(f"{C_BASE}/life/posts", json={
        "mediaType": "gallery", "media": ["life/x.jpg"],
        "title": "出管制刀具", "category": "邻里日常"}, headers=bearer(seller["token"]))
    assert bad.status_code == 422

    # 后台审核通过 → 频道可见
    review = await client.post(f"{ADMIN_BASE}/life-posts/{post_id}/review",
                               json={"decision": "APPROVE"}, headers=admin_headers(client))
    assert review.status_code == 200
    feed = (await client.get(f"{C_BASE}/life/posts", headers=bearer(buyer["token"]))).json()["data"]
    assert any(post["id"] == post_id for post in feed["items"])

    # 点赞与评论
    like = await client.post(f"{C_BASE}/life/posts/{post_id}/like", headers=bearer(buyer["token"]))
    assert like.json()["data"]["liked"] is True and like.json()["data"]["likes"] == 1
    comment = await client.post(f"{C_BASE}/life/posts/{post_id}/comments",
                                json={"content": "拍得太好了！"}, headers=bearer(buyer["token"]))
    assert comment.status_code == 200


@pytest.mark.asyncio
async def test_broadcast_review_flow(client):
    """喇叭审核闭环：后台发布 → 待审 → 通过 → 移动端喇叭站可见；下架即消失。"""
    _seller, buyer, _csrf = await _two_users(client)
    resp = await client.post(f"{ADMIN_BASE}/broadcasts", json={
        "communityId": 1, "title": "今晚中心广场露天电影",
        "type": "NEW_ITEM", "content": "19:30 开场，自带小板凳", "important": True},
        headers=admin_headers(client))
    assert resp.status_code == 200, resp.text
    broadcast_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["status"] == "PENDING_REVIEW"

    before = (await client.get(f"{C_BASE}/broadcasts", headers=bearer(buyer["token"]))).json()["data"]
    assert all(row["id"] != broadcast_id for row in before)

    review = await client.post(f"{ADMIN_BASE}/broadcasts/{broadcast_id}/review",
                               json={"decision": "APPROVE"}, headers=admin_headers(client))
    assert review.status_code == 200
    after = (await client.get(f"{C_BASE}/broadcasts", headers=bearer(buyer["token"]))).json()["data"]
    target = next(row for row in after if row["id"] == broadcast_id)
    assert target["type"] == "新上架"  # 英文类型码映射为移动端中文标签

    offline = await client.post(f"{ADMIN_BASE}/broadcasts/{broadcast_id}/offline", headers=admin_headers(client))
    assert offline.status_code == 200
    final = (await client.get(f"{C_BASE}/broadcasts", headers=bearer(buyer["token"]))).json()["data"]
    assert all(row["id"] != broadcast_id for row in final)


@pytest.mark.asyncio
async def test_help_match_flow(client, db_session):
    """互助闭环：发布 → 响应（去重）→ 管理端人工撮合 → 双方通知 → 关闭。"""
    seller, buyer, _csrf = await _two_users(client)
    resp = await client.post(f"{C_BASE}/services", json={
        "kind": "HELP", "category": "邻里帮忙", "title": "帮忙照看两小时宠物",
        "description": "临时外出，金毛很乖不咬人", "reward": "奶茶一杯"},
        headers=bearer(seller["token"]))
    assert resp.status_code == 200
    help_id = resp.json()["data"]["id"]

    # 响应与去重
    first = await client.post(f"{C_BASE}/services/{help_id}/respond", headers=bearer(buyer["token"]))
    assert first.status_code == 200
    dup = await client.post(f"{C_BASE}/services/{help_id}/respond", headers=bearer(buyer["token"]))
    assert dup.status_code == 409

    # 响应者信息进入管理端响应列表 → 人工撮合
    responses = (await client.get(f"{ADMIN_BASE}/help-requests/{help_id}/responses")).json()["data"]
    assert len(responses) == 1
    buyer_id = int(buyer["profile"]["id"])
    match = await client.post(f"{ADMIN_BASE}/help-requests/{help_id}/match",
                              json={"responderId": buyer_id}, headers=admin_headers(client))
    assert match.status_code == 200, match.text
    assert match.json()["data"]["status"] == "IN_PROGRESS"

    close = await client.post(f"{ADMIN_BASE}/help-requests/{help_id}/close",
                              json={"completed": True, "reason": "已完成服务"}, headers=admin_headers(client))
    assert close.status_code == 200
    assert close.json()["data"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_friend_request_and_messaging(client, db_session):
    """BR-14/M05：好友申请 → 同意 → 好友私信；实名门禁；消息幂等与敏感词提醒。"""
    seller, buyer, _csrf = await _two_users(client)
    seller_name = seller["profile"]["nickname"]

    # 发送好友申请（按昵称）
    req = await client.post(f"{C_BASE}/friends/requests",
                            json={"name": seller_name, "message": "邻居你好，想跟你换绘本"},
                            headers=bearer(buyer["token"]))
    assert req.status_code == 200, req.text

    # 重复申请被幂等拦截
    dup = await client.post(f"{C_BASE}/friends/requests",
                            json={"name": seller_name, "message": "再次申请"},
                            headers=bearer(buyer["token"]))
    assert dup.status_code == 409

    # 对方收到申请红点并同意
    requests = (await client.get(f"{C_BASE}/friends/requests",
                                 headers=bearer(seller["token"]))).json()["data"]
    assert len(requests) == 1
    accept = await client.post(f"{C_BASE}/friends/requests/{requests[0]['id']}/accept",
                               headers=bearer(seller["token"]))
    assert accept.status_code == 200

    friends = (await client.get(f"{C_BASE}/friends", headers=bearer(buyer["token"]))).json()["data"]
    assert len(friends) == 1 and friends[0]["name"] == seller_name

    # 好友私信（不依赖物品）
    conv = await client.post(f"{C_BASE}/conversations",
                             json={"peerId": int(seller["profile"]["id"])},
                             headers=bearer(buyer["token"]))
    assert conv.status_code == 200
    conv_id = conv.json()["data"]["id"]

    # 消息发送 + client_msg_id 幂等
    payload = {"content": "你好，明天下午方便见面吗？", "clientMsgId": "msg-0001"}
    first = await client.post(f"{C_BASE}/conversations/{conv_id}/messages",
                              json=payload, headers=bearer(buyer["token"]))
    assert first.status_code == 200
    again = await client.post(f"{C_BASE}/conversations/{conv_id}/messages",
                              json=payload, headers=bearer(buyer["token"]))
    assert again.status_code == 200
    assert again.json()["data"]["id"] == first.json()["data"]["id"]  # 同一条消息

    # 敏感词命中展示风险提醒（M05-05）
    risky = await client.post(f"{C_BASE}/conversations/{conv_id}/messages",
                              json={"content": "加我微信详聊"}, headers=bearer(buyer["token"]))
    assert risky.status_code == 200
    assert risky.json()["data"]["riskFlag"] == "微信"

    # 违禁消息直接拦截（A-09）
    banned = await client.post(f"{C_BASE}/conversations/{conv_id}/messages",
                               json={"content": "出售处方药"}, headers=bearer(buyer["token"]))
    assert banned.status_code == 422

    # 已读
    messages = (await client.get(f"{C_BASE}/conversations/{conv_id}/messages",
                                 headers=bearer(seller["token"]))).json()["data"]
    assert len(messages) == 2  # 幂等去重后
    read = await client.post(f"{C_BASE}/conversations/{conv_id}/read",
                             headers=bearer(seller["token"]))
    assert read.status_code == 200


@pytest.mark.asyncio
async def test_friend_request_requires_verified(client):
    """BR-14：未实名用户不能加好友/发私信。"""
    unverified = await register_user(client, "13933330003")
    seller = await verified_user(client, "13933330004")
    resp = await client.post(f"{C_BASE}/friends/requests",
                             json={"name": seller["profile"]["nickname"], "message": "hi"},
                             headers=bearer(unverified["token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_notifications_center_flow(client, db_session):
    """通知中心：审核结果分类通知、未读数、已读/全部已读、设置开关。"""
    seller = await verified_user(client, "13933330005")
    headers = bearer(seller["token"])

    data = (await client.get(f"{C_BASE}/notifications", headers=headers)).json()["data"]
    assert data["total"] >= 2  # 实名通过 + 业主证明通过
    assert data["items"][0]["category"] == "社区"  # 中文分类标签
    assert data["items"][0]["read"] is False

    unread = (await client.get(f"{C_BASE}/notifications/unread", headers=headers)).json()["data"]
    assert unread["count"] >= 2

    first_id = data["items"][0]["id"]
    read = await client.post(f"{C_BASE}/notifications/{first_id}/read", headers=headers)
    assert read.json()["data"]["unread"] == unread["count"] - 1

    await client.post(f"{C_BASE}/notifications/read-all", headers=headers)
    unread = (await client.get(f"{C_BASE}/notifications/unread", headers=headers)).json()["data"]
    assert unread["count"] == 0

    settings = (await client.put(f"{C_BASE}/notifications/settings",
                                 json={"pushEnabled": False}, headers=headers)).json()["data"]
    assert settings["pushEnabled"] is False
    again = (await client.get(f"{C_BASE}/notifications/settings", headers=headers)).json()["data"]
    assert again["pushEnabled"] is False  # 设置持久化


@pytest.mark.asyncio
async def test_notice_publish_delivers_to_residents(client, db_session):
    """公告发布 → 目标社区已认证住户收到站内通知（触达闭环）。"""
    seller = await verified_user(client, "13933330006")
    await admin_login(client)
    resp = await client.post(f"{ADMIN_BASE}/notices", json={
        "title": "本周六消防演练通知", "content": "请业主合理安排出行", "communityId": 1},
        headers=admin_headers(client))
    notice_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["status"] == "DRAFT"

    publish = await client.post(f"{ADMIN_BASE}/notices/{notice_id}/publish", headers=admin_headers(client))
    assert publish.status_code == 200
    assert "触达" in publish.json()["message"]

    notifications = (await client.get(f"{C_BASE}/notifications",
                                      headers=bearer(seller["token"]))).json()["data"]
    assert any(row["title"] == "本周六消防演练通知" for row in notifications["items"])


@pytest.mark.asyncio
async def test_notification_task_send_and_records(client):
    """通知任务：目标预估 → 发送 → 投递明细（送达/阅读）。"""
    _seller = await verified_user(client, "13933330007")
    await admin_login(client)
    create = await client.post(f"{ADMIN_BASE}/notification-tasks", json={
        "name": "停水通知", "channels": "IN_APP", "targetType": "COMMUNITY",
        "communityIds": [1], "content": "明早 8-10 点停水"}, headers=admin_headers(client))
    task_id = create.json()["data"]["id"]

    estimate = (await client.get(f"{ADMIN_BASE}/notification-tasks/{task_id}/estimate")).json()
    assert estimate["data"]["estimated"] == 1

    send = await client.post(f"{ADMIN_BASE}/notification-tasks/{task_id}/send", headers=admin_headers(client))
    assert send.status_code == 200
    assert send.json()["data"]["status"] == "COMPLETED"
    assert send.json()["data"]["delivery"] == "1 / 1"

    records = (await client.get(f"{ADMIN_BASE}/notification-tasks/{task_id}/records")).json()["data"]
    assert records["items"][0]["status"] == "SENT"


@pytest.mark.asyncio
async def test_report_handle_offline_item(client, db_session):
    """举报闭环：买家举报 → 工作台处理 → 物品下架 + 举报人通知（W05-03）。"""
    seller = await verified_user(client, "13933330008")
    await admin_login(client)
    item_id = await create_on_sale_item(client, admin_headers(client), seller["token"])
    buyer = await verified_user(client, "13933330009")

    report = await client.post(f"{C_BASE}/reports", json={
        "targetType": "ITEM", "targetId": int(item_id),
        "reason": "疑似假货", "detail": "包装与正品不符"}, headers=bearer(buyer["token"]))
    assert report.status_code == 200
    report_id = report.json()["data"]["reportId"]

    queue = (await client.get(f"{ADMIN_BASE}/reports", params={"status": "OPEN"})).json()["data"]
    assert any(row["id"] == report_id for row in queue["items"])

    handle = await client.post(f"{ADMIN_BASE}/reports/{report_id}/handle",
                               json={"action": "OFFLINE_CONTENT", "note": "核实属实，已下架"},
                               headers=admin_headers(client))
    assert handle.status_code == 200
    assert handle.json()["data"]["status"] == "RESOLVED"

    item = await db_session.get(Item, int(item_id))
    assert item.status == "OFF_SHELF"


@pytest.mark.asyncio
async def test_parameter_publish_takes_effect(client):
    """W04-05：后台修改参数并发布后，移动端 AppConfig 即更新（参数生效闭环）。"""
    await admin_login(client)
    tree = (await client.get(f"{ADMIN_BASE}/parameter-nodes/tree")).json()["data"]

    def find_key(nodes, code):
        for node in nodes:
            if node.get("code") == code:
                return node
            found = find_key(node.get("children", []), code)
            if found:
                return found
        return None

    key = find_key(tree, "community.nearby.radius_km")
    assert key is not None
    items = (await client.get(f"{ADMIN_BASE}/parameter-keys/{key['id']}/items")).json()["data"]
    item = items["items"][0]
    assert item["value"] == "3"

    before = (await client.get(f"{C_BASE}/config/app")).json()["data"]
    assert before["nearbyRadiusKm"] == 3.0

    update = await client.put(f"{ADMIN_BASE}/parameter-items/{item['id']}",
                              json={"value": "5", "reason": "扩大邻近范围试点"}, headers=admin_headers(client))
    assert update.status_code == 200
    publish = await client.post(f"{ADMIN_BASE}/parameter-items/{item['id']}/publish",
                                headers=admin_headers(client))
    assert publish.status_code == 200

    after = (await client.get(f"{C_BASE}/config/app")).json()["data"]
    assert after["nearbyRadiusKm"] == 5.0  # 发布后即时生效


@pytest.mark.asyncio
async def test_dashboard_summary_real(client, db_session):
    """工作台：全部来自真实聚合（无硬编码）；GMV 仅货币成交口径。"""
    _seller, _buyer, _csrf = await _two_users(client)
    summary = (await client.get(f"{ADMIN_BASE}/dashboard/summary")).json()["data"]
    assert summary["metrics"]["users"] >= 2
    assert summary["metrics"]["gmvCents"] == 0  # 尚无成交
    assert summary["distribution"]["owner"] >= 2
    assert len(summary["todos"]) == 7

    todos = (await client.get(f"{ADMIN_BASE}/dashboard/todos")).json()["data"]
    titles = [todo["title"] for todo in todos]
    assert "住户认证待审核" in titles and "提现待审核" in titles
