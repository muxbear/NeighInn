"""认证材料上传接口测试（MinIO 使用假客户端，不依赖外部服务）。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.db.models import FileObject
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_headers,
    admin_login,
    bearer,
    register_user,
)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 32


class FakeMinio:
    def __init__(self):
        self.calls = []
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def put_object(self, bucket, object_key, data, length, content_type=None):
        self.calls.append((bucket, object_key, length, content_type))
        payload = data.read() if hasattr(data, "read") else data
        self.objects[object_key] = (bytes(payload or b""), content_type)

    def get_object(self, bucket, object_key, offset=0, length=None):
        self.calls.append((bucket, object_key, 0, None))
        payload, _ = self.objects.get(object_key, (JPEG_BYTES, None))
        end = len(payload) if length is None else offset + length
        return _FakeReadable(payload[offset:end])

    def stat_object(self, bucket, object_key):
        payload, content_type = self.objects.get(object_key, (JPEG_BYTES, None))
        return SimpleNamespace(size=len(payload), content_type=content_type or "application/octet-stream")


class _FakeReadable:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._consumed = False

    def read(self, size: int = -1) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self._payload

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


@pytest.mark.asyncio
async def test_upload_private_material_records_file_object(client, db_session, monkeypatch):
    fake = FakeMinio()
    monkeypatch.setattr("src.api.c_end.uploads.get_minio", lambda: fake)
    account = await register_user(client)

    resp = await client.post(
        f"{C_BASE}/uploads",
        data={"scene": "REALNAME_ID"},
        files={"file": ("id-front.jpg", JPEG_BYTES, "image/jpeg")},
        headers=bearer(account["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["objectKey"].startswith("certifications/realname_id/")
    assert data["visibility"] == "private"
    assert fake.calls and fake.calls[0][0] == settings.minio_bucket_private

    record = await db_session.scalar(
        select(FileObject).where(FileObject.object_key == data["objectKey"]))
    assert record is not None
    assert record.content_type == "image/jpeg"
    assert record.uploaded_by == int(account["profile"]["id"])


@pytest.mark.asyncio
async def test_upload_rejects_wrong_material_type(client, monkeypatch):
    fake = FakeMinio()
    monkeypatch.setattr("src.api.c_end.uploads.get_minio", lambda: fake)
    account = await register_user(client)

    resp = await client.post(
        f"{C_BASE}/uploads",
        data={"scene": "REALNAME_ID"},
        files={"file": ("id.pdf", b"%PDF-1.7 test", "application/pdf")},
        headers=bearer(account["token"]),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001
    assert not fake.calls


@pytest.mark.asyncio
async def test_admin_uploads_life_media_to_public_bucket(client, db_session, monkeypatch):
    """管理端生活媒体上传：公开桶、类型识别、文件记录与可访问 URL。"""
    fake = FakeMinio()
    monkeypatch.setattr("src.api.admin.files.get_minio", lambda: fake)
    monkeypatch.setattr("src.api.admin.files.public_media_url",
                        lambda key: f"https://cdn.test/{key}")
    await admin_login(client)

    resp = await client.post(
        f"{ADMIN_BASE}/files/upload",
        data={"scene": "LIFE_IMAGE"},
        files={"file": ("life.jpg", JPEG_BYTES, "image/jpeg")},
        headers=admin_headers(client),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["objectKey"].startswith("uploads/life_image/")
    assert data["contentType"] == "image/jpeg"
    assert data["url"] == f"https://cdn.test/{data['objectKey']}"
    assert fake.calls and fake.calls[0][0] == settings.minio_bucket_public

    record = await db_session.scalar(
        select(FileObject).where(FileObject.object_key == data["objectKey"]))
    assert record is not None
    assert record.visibility == "public"
    assert record.content_type == "image/jpeg"

    # 短视频场景上传 MP4
    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"0" * 24
    video = await client.post(
        f"{ADMIN_BASE}/files/upload",
        data={"scene": "LIFE_VIDEO"},
        files={"file": ("clip.mp4", video_bytes, "video/mp4")},
        headers=admin_headers(client),
    )
    assert video.status_code == 200, video.text
    assert video.json()["data"]["objectKey"].startswith("uploads/life_video/")
    assert video.json()["data"]["objectKey"].endswith(".mp4")

    # 图片场景不能上传视频
    bad = await client.post(
        f"{ADMIN_BASE}/files/upload",
        data={"scene": "LIFE_IMAGE"},
        files={"file": ("clip.mp4", video_bytes, "video/mp4")},
        headers=admin_headers(client),
    )
    assert bad.status_code == 400


@pytest.mark.cert_materials
@pytest.mark.asyncio
async def test_realname_rejects_unowned_material_keys(client, monkeypatch):
    fake = FakeMinio()
    monkeypatch.setattr("src.api.c_end.uploads.get_minio", lambda: fake)
    account = await register_user(client)
    headers = bearer(account["token"])

    forged = await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/f.jpg", "backImage": "certs/b.jpg"},
        headers=headers,
    )
    assert forged.status_code == 400
    assert forged.json()["code"] == 40001

    keys = []
    for name in ("front.jpg", "back.jpg"):
        resp = await client.post(
            f"{C_BASE}/uploads",
            data={"scene": "REALNAME_ID"},
            files={"file": (name, JPEG_BYTES, "image/jpeg")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        keys.append(resp.json()["data"]["objectKey"])

    ok = await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": keys[0], "backImage": keys[1]},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_chat_media_upload_private_bucket_and_signed_proxy(
    client, db_session, monkeypatch
):
    """私信图片/视频：私有桶 + chat/ 前缀 + HMAC 签名同源代理。"""
    from src.core.storage import private_media_url, verify_private_media_signature

    fake = FakeMinio()
    monkeypatch.setattr("src.api.c_end.uploads.get_minio", lambda: fake)
    account = await register_user(client)
    headers = bearer(account["token"])

    image = await client.post(
        f"{C_BASE}/uploads",
        data={"scene": "CHAT_IMAGE"},
        files={"file": ("chat.jpg", JPEG_BYTES, "image/jpeg")},
        headers=headers,
    )
    assert image.status_code == 200, image.text
    image_data = image.json()["data"]
    assert image_data["objectKey"].startswith("chat/chat_image/")
    assert image_data["visibility"] == "private"
    assert fake.calls[-1][0] == settings.minio_bucket_private

    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"0" * 24
    video = await client.post(
        f"{C_BASE}/uploads",
        data={"scene": "CHAT_VIDEO"},
        files={"file": ("chat.mp4", video_bytes, "video/mp4")},
        headers=headers,
    )
    assert video.status_code == 200, video.text
    video_key = video.json()["data"]["objectKey"]
    assert video_key.startswith("chat/chat_video/") and video_key.endswith(".mp4")

    signed = private_media_url(image_data["objectKey"])
    assert signed.startswith("/api/v1/media/private/chat/chat_image/")
    assert "?e=" in signed and "&s=" in signed
    expires, sig = signed.split("?e=")[1].split("&s=")
    assert verify_private_media_signature(image_data["objectKey"], int(expires), sig)

    # 不带登录态也能按签名读取，返回私有桶内容。
    fetched = await client.get(signed)
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers["content-type"] == "image/jpeg"
    assert fetched.headers["accept-ranges"] == "bytes"
    assert fetched.headers["content-length"] == str(len(JPEG_BYTES))
    assert fetched.content == JPEG_BYTES
    assert fake.calls[-1][0] == settings.minio_bucket_private

    # 视频必须支持 Range/206：浏览器 <video> 起播与拖动依赖它。
    video_url = private_media_url(video_key)
    part = await client.get(video_url, headers={"Range": "bytes=0-7"})
    assert part.status_code == 206, part.text
    assert part.headers["content-type"] == "video/mp4"
    assert part.headers["accept-ranges"] == "bytes"
    assert part.headers["content-range"] == f"bytes 0-7/{len(video_bytes)}"
    assert part.headers["content-length"] == "8"
    assert part.content == video_bytes[:8]

    suffix = await client.get(video_url, headers={"Range": "bytes=-8"})
    assert suffix.status_code == 206
    assert suffix.content == video_bytes[-8:]

    beyond = await client.get(video_url, headers={"Range": f"bytes={len(video_bytes)}-"})
    assert beyond.status_code == 416
    assert beyond.headers["content-range"] == f"bytes */{len(video_bytes)}"

    head = await client.head(video_url)
    assert head.status_code == 200
    assert head.headers["accept-ranges"] == "bytes"
    assert head.headers["content-length"] == str(len(video_bytes))

    # 篡改签名 / 过期 / 非 chat 前缀一律 404。
    tampered = signed.rsplit("&s=", 1)[0] + "&s=" + ("0" * 64)
    assert (await client.get(tampered)).status_code == 404
    import time
    from urllib.parse import quote

    from src.core.storage import _chat_media_signature

    stale_exp = int(time.time()) - 10
    stale = (
        f"/api/v1/media/private/{quote(image_data['objectKey'], safe='/')}"
        f"?e={stale_exp}&s={_chat_media_signature(image_data['objectKey'], stale_exp)}"
    )
    assert (await client.get(stale)).status_code == 404
    assert private_media_url("certifications/realname_id/1/a.jpg") == ""

    # 公开通道不能读取私信媒体。
    assert (await client.get(
        f"{C_BASE}/media/{image_data['objectKey']}")).status_code == 404


@pytest.mark.asyncio
async def test_public_media_proxied_through_api(client, monkeypatch):
    """公开图片走同源代理：客户端不必能解析 MinIO 主机地址。"""
    from src.core.storage import public_media_url

    assert public_media_url("uploads/item_image/1/a.jpg") == (
        "/api/v1/media/uploads/item_image/1/a.jpg")
    assert public_media_url("https://cdn.example.com/a.jpg") == (
        "https://cdn.example.com/a.jpg")
    assert public_media_url("") == ""

    fake = FakeMinio()
    monkeypatch.setattr("src.api.c_end.uploads.get_minio", lambda: fake)
    resp = await client.get(f"{C_BASE}/media/uploads/item_image/1/a.jpg")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["cache-control"] == "public, max-age=604800"
    assert resp.content == JPEG_BYTES
    assert fake.calls and fake.calls[0][0] == settings.minio_bucket_public

    # 私有认证材料前缀不允许从公开通道读取
    resp = await client.get(f"{C_BASE}/media/certifications/realname_id/1/a.jpg")
    assert resp.status_code == 404
    # 路径穿越同样被拒绝
    resp = await client.get(f"{C_BASE}/media/uploads/../secret.jpg")
    assert resp.status_code in (404, 400)
