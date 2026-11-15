"""认证材料上传接口测试（MinIO 使用假客户端，不依赖外部服务）。"""

import pytest
from sqlalchemy import select

from src.db.models import FileObject
from tests.conftest import C_BASE, bearer, register_user

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
    assert fake.calls and fake.calls[0][0] == "ni-private"

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
