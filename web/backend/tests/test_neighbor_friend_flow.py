"""邻居好友体系集成测试。

覆盖：双认证门禁、同小区隐式好友、跨小区隔离、拉黑/解除、
会话去重、消息分页/幂等/已读、WS 信封格式。
"""

from __future__ import annotations

import json

import pytest

from src.core.config import settings
from src.core.ws_manager import WsManager
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_login,
    bearer,
    first_pending_cert,
    register_user,
    submit_owner_proof,
    verified_user,
    verify_realname,
)


async def _dual_users(client):
    first = await verified_user(client, "13955550001", community_id=1)
    second = await verified_user(client, "13955550002", community_id=1)
    return first, second


@pytest.mark.asyncio
async def test_friend_eligibility_requires_both_certifications(client):
    """仅实名或仅住户认证都不满足好友功能资格。"""
    csrf = await admin_login(client)

    unverified = await register_user(client, "13955551001")
    resp = await client.get(f"{C_BASE}/friends", headers=bearer(unverified["token"]))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40304
    assert resp.json()["data"]["reasonCode"] == "REALNAME_REQUIRED"

    realname_only = await register_user(client, "13955551002")
    await verify_realname(client, csrf, realname_only["token"])
    resp = await client.get(f"{C_BASE}/friends", headers=bearer(realname_only["token"]))
    assert resp.status_code == 403
    assert resp.json()["data"]["reasonCode"] == "OWNER_PROOF_REQUIRED"

    owner_only = await register_user(client, "13955551003")
    await submit_owner_proof(client, owner_only["token"], community_id=1)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    approve = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf
    )
    assert approve.status_code == 200, approve.text
    resp = await client.get(f"{C_BASE}/friends", headers=bearer(owner_only["token"]))
    assert resp.status_code == 403
    assert resp.json()["data"]["reasonCode"] == "REALNAME_REQUIRED"

    eligibility = (await client.get(
        f"{C_BASE}/friends/eligibility", headers=bearer(owner_only["token"])
    )).json()["data"]
    assert eligibility["eligible"] is False
    assert eligibility["ownerVerified"] is True
    assert eligibility["realnameVerified"] is False


@pytest.mark.asyncio
async def test_implicit_neighbors_and_cross_community_isolation(client):
    """同小区双认证自动互为邻居；不同小区互不可见。"""
    first, second = await _dual_users(client)
    third = await verified_user(client, "13955550003", community_id=2)

    first_friends = (await client.get(
        f"{C_BASE}/friends", headers=bearer(first["token"])
    )).json()["data"]
    names = {row["name"] for row in first_friends["items"]}
    assert second["profile"]["nickname"] in names
    assert third["profile"]["nickname"] not in names
    assert first_friends["total"] >= 1

    # 静态路由 /friends/requests 不能被 /friends/{peer_id:int} 吞掉
    legacy = await client.get(f"{C_BASE}/friends/requests", headers=bearer(first["token"]))
    assert legacy.status_code == 200
    assert isinstance(legacy.json()["data"], list)

    conv = await client.post(
        f"{C_BASE}/conversations",
        json={"peerId": int(third["profile"]["id"])},
        headers=bearer(first["token"]),
    )
    assert conv.status_code == 403


@pytest.mark.asyncio
async def test_block_and_unblock_flow(client):
    """拉黑后双向隐藏、消息阻断；解除后恢复。"""
    first, second = await _dual_users(client)
    second_id = int(second["profile"]["id"])

    conv = await client.post(
        f"{C_BASE}/conversations", json={"peerId": second_id},
        headers=bearer(first["token"]),
    )
    assert conv.status_code == 200, conv.text
    conv_id = conv.json()["data"]["id"]

    detail_before = await client.get(
        f"{C_BASE}/friends/{second_id}", headers=bearer(first["token"])
    )
    assert detail_before.status_code == 200
    assert detail_before.json()["data"]["relation"] == "FRIEND"
    assert detail_before.json()["data"]["canMessage"] is True

    block = await client.post(
        f"{C_BASE}/friends/{second_id}/block",
        json={"reason": "测试拉黑", "source": "CHAT"},
        headers=bearer(first["token"]),
    )
    assert block.status_code == 200, block.text

    detail_blocked = await client.get(
        f"{C_BASE}/friends/{second_id}", headers=bearer(first["token"])
    )
    assert detail_blocked.status_code == 200
    assert detail_blocked.json()["data"]["relation"] == "BLOCKED"
    assert detail_blocked.json()["data"]["blockedByMe"] is True

    first_friends = (await client.get(
        f"{C_BASE}/friends", headers=bearer(first["token"])
    )).json()["data"]
    second_friends = (await client.get(
        f"{C_BASE}/friends", headers=bearer(second["token"])
    )).json()["data"]
    assert all(row["userId"] != str(second_id) for row in first_friends["items"])
    assert all(row["userId"] != first["profile"]["id"] for row in second_friends["items"])

    blocked = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={"content": "还在吗", "clientMsgId": "blocked-1"},
        headers=bearer(second["token"]),
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == 40305

    blocks = (await client.get(
        f"{C_BASE}/friends/blocks", headers=bearer(first["token"])
    )).json()["data"]
    assert blocks["total"] == 1

    # 好友会话从双方会话列表隐藏
    first_convs = (await client.get(
        f"{C_BASE}/conversations", headers=bearer(first["token"])
    )).json()["data"]
    second_convs = (await client.get(
        f"{C_BASE}/conversations", headers=bearer(second["token"])
    )).json()["data"]
    assert all(item["id"] != conv_id for item in first_convs)
    assert all(item["id"] != conv_id for item in second_convs)

    unblock = await client.delete(
        f"{C_BASE}/friends/{second_id}/block", headers=bearer(first["token"])
    )
    assert unblock.status_code == 200, unblock.text

    restored = (await client.get(
        f"{C_BASE}/friends", headers=bearer(first["token"])
    )).json()["data"]
    assert any(row["userId"] == str(second_id) for row in restored["items"])

    sent = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={"content": "解除了", "clientMsgId": "unblocked-1"},
        headers=bearer(second["token"]),
    )
    assert sent.status_code == 200, sent.text


@pytest.mark.asyncio
async def test_conversation_dedupe_remark_and_message_pagination(client):
    """双向创建会话复用同一条；备注生效；消息分页与已读游标正确。"""
    first, second = await _dual_users(client)
    first_id = int(first["profile"]["id"])
    second_id = int(second["profile"]["id"])

    first_conv = await client.post(
        f"{C_BASE}/conversations", json={"peerId": second_id},
        headers=bearer(first["token"]),
    )
    second_conv = await client.post(
        f"{C_BASE}/conversations", json={"peerId": first_id},
        headers=bearer(second["token"]),
    )
    assert first_conv.status_code == 200 and second_conv.status_code == 200
    conv_id = first_conv.json()["data"]["id"]
    assert second_conv.json()["data"]["id"] == conv_id

    remark = await client.put(
        f"{C_BASE}/friends/{second_id}/remark",
        json={"remark": "二楼王姐"},
        headers=bearer(first["token"]),
    )
    assert remark.status_code == 200, remark.text
    friends = (await client.get(
        f"{C_BASE}/friends", headers=bearer(first["token"])
    )).json()["data"]
    row = next(item for item in friends["items"] if item["userId"] == str(second_id))
    assert row["name"] == "二楼王姐"

    for index in range(5):
        resp = await client.post(
            f"{C_BASE}/conversations/{conv_id}/messages",
            json={"content": f"消息 {index}", "clientMsgId": f"page-{index}"},
            headers=bearer(second["token"]),
        )
        assert resp.status_code == 200, resp.text

    latest = (await client.get(
        f"{C_BASE}/conversations/{conv_id}/messages",
        params={"limit": 2},
        headers=bearer(first["token"]),
    )).json()["data"]
    assert [item["content"] for item in latest["items"]] == ["消息 3", "消息 4"]
    assert latest["hasMoreBefore"] is True

    first_seq = latest["items"][0]["seq"]
    older = (await client.get(
        f"{C_BASE}/conversations/{conv_id}/messages",
        params={"beforeSeq": first_seq, "limit": 2},
        headers=bearer(first["token"]),
    )).json()["data"]
    assert [item["content"] for item in older["items"]] == ["消息 1", "消息 2"]

    after = (await client.get(
        f"{C_BASE}/conversations/{conv_id}/messages",
        params={"afterSeq": first_seq, "limit": 10},
        headers=bearer(first["token"]),
    )).json()["data"]
    assert [item["content"] for item in after["items"]] == ["消息 4"]

    read = await client.post(
        f"{C_BASE}/conversations/{conv_id}/read",
        json={"lastSeq": latest["items"][-1]["seq"]},
        headers=bearer(first["token"]),
    )
    assert read.status_code == 200, read.text

    conversations = (await client.get(
        f"{C_BASE}/conversations", headers=bearer(first["token"])
    )).json()["data"]
    conv = next(item for item in conversations if item["id"] == conv_id)
    assert conv["unread"] == 0


@pytest.mark.asyncio
async def test_emoji_message_and_idempotency_conflict(client):
    """Unicode 表情消息可发送；同一 clientMsgId 不同内容返回 40902。"""
    first, second = await _dual_users(client)
    conv = await client.post(
        f"{C_BASE}/conversations",
        json={"peerId": int(second["profile"]["id"])},
        headers=bearer(first["token"]),
    )
    conv_id = conv.json()["data"]["id"]

    emoji = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={"type": "TEXT", "content": "你好 😊", "clientMsgId": "emoji-1"},
        headers=bearer(first["token"]),
    )
    assert emoji.status_code == 200, emoji.text
    assert emoji.json()["data"]["content"] == "你好 😊"

    conflict = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={"type": "TEXT", "content": "不同内容", "clientMsgId": "emoji-1"},
        headers=bearer(first["token"]),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 40902


@pytest.mark.asyncio
async def test_image_and_video_messages_return_signed_media_url(client):
    """图片/小视频消息：必须是 chat/ 媒体键；下发签名地址；列表预览为[图片]/[视频]。"""
    first, second = await _dual_users(client)
    conv = await client.post(
        f"{C_BASE}/conversations",
        json={"peerId": int(second["profile"]["id"])},
        headers=bearer(first["token"]),
    )
    conv_id = conv.json()["data"]["id"]
    headers = bearer(first["token"])

    # 缺少媒体键 / 非 chat 前缀一律拒绝。
    missing = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={"type": "IMAGE", "clientMsgId": "img-0"},
        headers=headers,
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == 40001

    forged = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={
            "type": "IMAGE",
            "image": "uploads/item_image/1/a.jpg",
            "clientMsgId": "img-0",
        },
        headers=headers,
    )
    assert forged.status_code == 400

    image_key = "chat/chat_image/1/a.jpg"
    image = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={
            "type": "IMAGE",
            "clientMsgId": "img-1",
            "image": image_key,
            "extra": {"width": 800, "height": 600},
        },
        headers=headers,
    )
    assert image.status_code == 200, image.text
    image_data = image.json()["data"]
    assert image_data["type"] == "IMAGE"
    assert image_data["imageKey"] == image_key
    assert image_data["image"].startswith("/api/v1/media/private/chat/chat_image/")
    assert "?e=" in image_data["image"] and "&s=" in image_data["image"]
    assert image_data["extra"] == {"width": 800, "height": 600}

    # 同一 clientMsgId 换文件属于幂等冲突。
    conflict = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={
            "type": "IMAGE",
            "clientMsgId": "img-1",
            "image": "chat/chat_image/1/b.jpg",
        },
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 40902

    # 超过 60 秒的小视频拒绝。
    too_long = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={
            "type": "VIDEO",
            "clientMsgId": "vid-0",
            "image": "chat/chat_video/1/v.mp4",
            "extra": {"duration": 61},
        },
        headers=headers,
    )
    assert too_long.status_code == 400
    assert "60" in too_long.json()["message"]

    video = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={
            "type": "VIDEO",
            "clientMsgId": "vid-1",
            "image": "chat/chat_video/1/v.mp4",
            "extra": {"duration": 12.5, "size": 12345},
        },
        headers=headers,
    )
    assert video.status_code == 200, video.text
    assert video.json()["data"]["image"].startswith(
        "/api/v1/media/private/chat/chat_video/")

    conversations = (await client.get(
        f"{C_BASE}/conversations", headers=bearer(second["token"])
    )).json()["data"]
    row = next(item for item in conversations if item["id"] == conv_id)
    assert row["lastMessage"] == "[视频]"
    assert row["lastMessageType"] == "VIDEO"

    # 对方拉取消息时同样拿到可播放/可预览的签名地址。
    page = (await client.get(
        f"{C_BASE}/conversations/{conv_id}/messages",
        headers=bearer(second["token"]),
    )).json()["data"]
    types = {item["type"]: item for item in page["items"]}
    assert types["IMAGE"]["image"].startswith("/api/v1/media/private/")
    assert types["VIDEO"]["imageKey"] == "chat/chat_video/1/v.mp4"


@pytest.mark.asyncio
async def test_message_rate_limit(client, monkeypatch):
    """超过每分钟发送上限返回 42901。"""
    monkeypatch.setattr(settings, "neighbor_message_rate_per_minute", 2)
    first, second = await _dual_users(client)
    conv = await client.post(
        f"{C_BASE}/conversations",
        json={"peerId": int(second["profile"]["id"])},
        headers=bearer(first["token"]),
    )
    conv_id = conv.json()["data"]["id"]

    for index in range(2):
        resp = await client.post(
            f"{C_BASE}/conversations/{conv_id}/messages",
            json={"content": f"限流 {index}", "clientMsgId": f"rate-{index}"},
            headers=bearer(first["token"]),
        )
        assert resp.status_code == 200, resp.text

    limited = await client.post(
        f"{C_BASE}/conversations/{conv_id}/messages",
        json={"content": "第三条", "clientMsgId": "rate-2"},
        headers=bearer(first["token"]),
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == 42901


@pytest.mark.asyncio
async def test_ws_send_returns_ack(client, session_maker, monkeypatch):
    """WebSocket MSG_SEND 落库后返回 MSG_ACK；HTTP 可读到同一条消息。"""
    first, second = await _dual_users(client)
    conv = await client.post(
        f"{C_BASE}/conversations",
        json={"peerId": int(second["profile"]["id"])},
        headers=bearer(first["token"]),
    )
    conv_id = conv.json()["data"]["id"]

    from src.api.c_end import ws as ws_module

    monkeypatch.setattr(ws_module, "SessionLocal", session_maker)

    class FakeSocket:
        def __init__(self) -> None:
            self.frames: list[str] = []

        async def send_text(self, text: str) -> None:
            self.frames.append(text)

    socket = FakeSocket()
    await ws_module._handle_send(
        socket,  # type: ignore[arg-type]
        int(first["profile"]["id"]),
        {
            "conversationId": conv_id,
            "content": "WS 通道消息",
            "clientMsgId": "ws-ack-1",
            "type": "TEXT",
        },
    )
    frame = json.loads(socket.frames[-1])
    assert frame["action"] == "MSG_ACK"
    assert frame["payload"]["clientMsgId"] == "ws-ack-1"
    assert frame["payload"]["seq"] == 1

    messages = (await client.get(
        f"{C_BASE}/conversations/{conv_id}/messages",
        headers=bearer(second["token"]),
    )).json()["data"]
    assert any(item["content"] == "WS 通道消息" for item in messages["items"])


@pytest.mark.asyncio
async def test_ws_push_envelope_uses_action_payload():
    """WebSocket 下行统一 action/payload 信封。"""
    class FakeSocket:
        def __init__(self) -> None:
            self.frames: list[str] = []

        async def send_text(self, text: str) -> None:
            self.frames.append(text)

    manager = WsManager()
    socket = FakeSocket()
    manager.connect(7, socket)  # type: ignore[arg-type]
    delivered = await manager.push(7, "MSG_PUSH", {"conversationId": "1"})
    assert delivered == 1
    frame = json.loads(socket.frames[0])
    assert frame["action"] == "MSG_PUSH"
    assert frame["payload"] == {"conversationId": "1"}
    assert "type" not in frame
