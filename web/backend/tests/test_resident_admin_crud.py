"""社区业主档案后台 CRUD（W02 / 后台详设 5.6.1）。

覆盖：新增（手机号脱敏与账号关联）、编辑（脱敏号码不覆盖、
后台可直接修正认证状态与信用分）、删除（保留认证单并解除档案引用）。
"""

import pytest
from sqlalchemy import select

from src.core.security import decrypt_field
from src.db.models import Certification, Resident
from tests.conftest import ADMIN_BASE, TEST_PHONE, admin_login, register_user


def _resident_payload(**overrides) -> dict:
    payload = {
        "communityId": 1,
        "name": "王阿姨",
        "gender": "女",
        "phone": "13800008888",
        "identity": "业主",
        "building": "8 栋 1 单元 902",
        "relationship": "房屋产权人",
        "certification": "未认证",
        "certificationNo": "",
        "level": "普通用户",
        "status": "正常",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_resident_create_update_delete(client, db_session):
    csrf = await admin_login(client)

    account = await register_user(client)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="13900001111"), headers=csrf)
    assert resp.status_code == 200, resp.text
    created = resp.json()["data"]
    resident_id = int(created["id"])
    assert created["name"] == "王阿姨"
    assert created["phone"] == "139****1111"  # 全链路脱敏（SRS 9.2）
    assert created["userId"] == account["profile"]["id"]  # 按手机号关联 C 端账号

    # 同社区手机号唯一，重复建档 409
    dup = await client.post(f"{ADMIN_BASE}/residents",
                            json=_resident_payload(phone="13900001111"), headers=csrf)
    assert dup.status_code == 409
    assert dup.json()["code"] == 40901

    # 编辑：基本信息落库；提交脱敏手机号视为不修改
    resp = await client.put(f"{ADMIN_BASE}/residents/{resident_id}", json=_resident_payload(
        name="王阿姨（修改）", phone="139****1111", identity="家属",
        building="9 栋 2 单元 301", relationship="同住家属", level="活跃用户",
    ), headers=csrf)
    assert resp.status_code == 200, resp.text
    updated = resp.json()["data"]
    assert updated["name"] == "王阿姨（修改）"
    assert updated["identity"] == "家属"
    assert updated["level"] == "活跃用户"

    resident = await db_session.get(Resident, resident_id)
    await db_session.refresh(resident)
    assert decrypt_field(resident.phone_enc) == "13900001111"
    assert resident.phone_hash

    # 后台允许直接修正认证状态（不走审核状态机），并同步信用分 / 身份认证状态
    resp = await client.put(f"{ADMIN_BASE}/residents/{resident_id}",
                            json={"certification": "已认证"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["certification"] == "VERIFIED"
    assert resp.json()["data"]["certificationNo"].startswith("YZ")

    resp = await client.put(f"{ADMIN_BASE}/residents/{resident_id}",
                            json={"certification": "待审核", "creditScore": 88,
                                  "realnameStatus": "已认证"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["certification"] == "PENDING"
    assert resp.json()["data"]["creditScore"] == 88
    assert resp.json()["data"]["creditLevel"] == "良好"
    assert resp.json()["data"]["realnameStatus"] == "VERIFIED"

    # 删除：认证审核单保留历史，仅解除档案引用
    db_session.add(Certification(user_id=resident.user_id, resident_id=resident_id,
                                 community_id=1, type="OWNER_PROOF", identity="family"))
    await db_session.commit()
    cert_id = (await db_session.scalar(
        select(Certification.id).where(Certification.resident_id == resident_id)))

    resp = await client.delete(f"{ADMIN_BASE}/residents/{resident_id}", headers=csrf)
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    remaining = await db_session.scalar(
        select(Resident).where(Resident.id == resident_id))
    assert remaining is None
    cert = await db_session.get(Certification, cert_id)
    await db_session.refresh(cert)
    assert cert.resident_id is None


@pytest.mark.asyncio
async def test_resident_create_validation(client):
    csrf = await admin_login(client)

    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(name="  "), headers=csrf)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001

    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="12345"), headers=csrf)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001

    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(identity="访客"), headers=csrf)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_resident_cert_status_override_and_materials(client, db_session):
    """后台可直改认证状态/信用分，并预览、删除认证材料。"""
    csrf = await admin_login(client)
    await register_user(client, phone=TEST_PHONE)
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone=TEST_PHONE), headers=csrf)
    assert resp.status_code == 200, resp.text
    resident_id = int(resp.json()["data"]["id"])
    resident = await db_session.get(Resident, resident_id)

    realname = Certification(user_id=resident.user_id, resident_id=resident_id,
                             type="REALNAME", identity="owner", status="PENDING",
                             materials=["certs/a.jpg", "certs/b.jpg"])
    owner = Certification(user_id=resident.user_id, resident_id=resident_id,
                          community_id=1, type="OWNER_PROOF", identity="owner",
                          status="PENDING")
    db_session.add_all([realname, owner])
    await db_session.commit()

    resp = await client.put(
        f"{ADMIN_BASE}/residents/{resident_id}",
        json={"realnameStatus": "已认证", "creditScore": 100, "certification": "已认证"},
        headers=csrf)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["realnameStatus"] == "VERIFIED"
    assert data["creditScore"] == 100
    assert data["certification"] == "VERIFIED"
    for cert, expected in ((realname, "VERIFIED"), (owner, "VERIFIED")):
        await db_session.refresh(cert)
        assert cert.status == expected

    resp = await client.get(
        f"{ADMIN_BASE}/residents/{resident_id}/certifications/REALNAME/materials",
        headers=csrf)
    assert resp.status_code == 200, resp.text
    materials = resp.json()["data"]["materials"]
    assert [item["objectKey"] for item in materials] == ["certs/a.jpg", "certs/b.jpg"]
    assert materials[0]["label"] == "身份证人像面"

    resp = await client.delete(
        f"{ADMIN_BASE}/residents/{resident_id}/certifications/REALNAME/materials",
        params={"objectKey": "certs/a.jpg"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert [item["objectKey"] for item in resp.json()["data"]["materials"]] == ["certs/b.jpg"]
