"""认证材料上传接口测试（MinIO 使用假客户端，不依赖外部服务）。"""

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

    def put_object(self, bucket, object_key, data, length, content_type=None):
        self.calls.append((bucket, object_key, length, content_type))


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
