"""社区业主档案后台 CRUD（W02 / 后台详设 5.6.1）。

覆盖：新增（手机号脱敏与账号关联）、编辑（脱敏号码不覆盖、
后台可直接修正认证状态与信用分）、删除（保留认证单并解除档案引用）。
"""

import pytest
from sqlalchemy import func, select

from src.core.security import decrypt_field, hmac_index
from src.db.models import Certification, Item, PlatformUser, Resident
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


@pytest.mark.asyncio
async def test_resident_batch_delete(client, db_session):
    """批量删除人员档案：返回删除数量，关联认证单仅解除档案引用。"""
    csrf = await admin_login(client)
    account = await register_user(client)

    first = await client.post(f"{ADMIN_BASE}/residents",
                              json=_resident_payload(phone=TEST_PHONE), headers=csrf)
    second = await client.post(
        f"{ADMIN_BASE}/residents",
        json=_resident_payload(name="李叔叔", phone="13900004444"), headers=csrf)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_id = int(first.json()["data"]["id"])
    second_id = int(second.json()["data"]["id"])

    db_session.add(Certification(
        user_id=int(account["profile"]["id"]), resident_id=first_id,
        community_id=1, type="OWNER_PROOF", identity="owner"))
    await db_session.commit()
    cert_id = int(await db_session.scalar(
        select(Certification.id).where(Certification.resident_id == first_id)))

    empty = await client.post(f"{ADMIN_BASE}/residents/batch-delete",
                              json={"ids": []}, headers=csrf)
    assert empty.status_code == 400

    resp = await client.post(f"{ADMIN_BASE}/residents/batch-delete",
                             json={"ids": [first_id, second_id]}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["deleted"] == 2

    db_session.expire_all()
    assert await db_session.scalar(
        select(Resident.id).where(Resident.id.in_([first_id, second_id]))) is None
    cert = await db_session.get(Certification, cert_id)
    await db_session.refresh(cert)
    assert cert.resident_id is None


@pytest.mark.asyncio
async def test_delete_resident_cancel_account_frees_phone(client, db_session):
    """勾选注销账号：匿名化 platform_users 并清空手机号，原号码可重新注册。"""
    csrf = await admin_login(client)
    phone = "13900005555"
    account = await register_user(client, phone=phone)

    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone=phone), headers=csrf)
    assert resp.status_code == 200, resp.text
    resident_id = int(resp.json()["data"]["id"])

    resp = await client.delete(
        f"{ADMIN_BASE}/residents/{resident_id}",
        params={"cancelAccount": "true"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["accountCancelled"] is True

    db_session.expire_all()
    user = await db_session.get(PlatformUser, int(account["profile"]["id"]))
    await db_session.refresh(user)
    assert user.status == "CANCELLED"
    assert decrypt_field(user.phone_enc) == ""
    assert user.phone_hash != hmac_index(phone)
    assert user.nickname == "已注销用户"
    assert await db_session.scalar(
        select(Resident.id).where(Resident.id == resident_id)) is None

    # 手机号已释放：同一号码可重新注册为全新账号
    again = await register_user(client, phone=phone)
    assert again["isNewUser"] is True
    assert again["profile"]["id"] != account["profile"]["id"]


@pytest.mark.asyncio
async def test_delete_resident_cancel_account_blocked_by_business_data(client, db_session):
    """存在发布/交易等业务数据时禁止注销账号，且档案与账号都保持不变。"""
    csrf = await admin_login(client)
    phone = "13900006666"
    account = await register_user(client, phone=phone)
    user = await db_session.get(PlatformUser, int(account["profile"]["id"]))
    db_session.add(Item(community_id=1, seller_id=user.id,
                        title="测试物品", trade_type="FREE_GIFT"))
    await db_session.commit()

    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone=phone), headers=csrf)
    assert resp.status_code == 200, resp.text
    resident_id = int(resp.json()["data"]["id"])

    resp = await client.delete(
        f"{ADMIN_BASE}/residents/{resident_id}",
        params={"cancelAccount": "true"}, headers=csrf)
    assert resp.status_code == 422, resp.text
    assert "存在发布物品" in resp.json()["message"]

    db_session.expire_all()
    assert await db_session.scalar(
        select(Resident.id).where(Resident.id == resident_id)) is not None
    user = await db_session.get(PlatformUser, int(account["profile"]["id"]))
    await db_session.refresh(user)
    assert user.status == "ACTIVE"


@pytest.mark.asyncio
async def test_delete_resident_cancel_account_blocked_by_other_community(client, db_session):
    """账号在其他社区仍有档案时禁止注销，避免误伤跨社区账号。"""
    csrf = await admin_login(client)
    phone = "13900007777"
    account = await register_user(client, phone=phone)

    first = await client.post(f"{ADMIN_BASE}/residents",
                              json=_resident_payload(phone=phone), headers=csrf)
    second = await client.post(f"{ADMIN_BASE}/residents",
                               json=_resident_payload(phone=phone, communityId=2),
                               headers=csrf)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_id = int(first.json()["data"]["id"])

    resp = await client.delete(
        f"{ADMIN_BASE}/residents/{first_id}",
        params={"cancelAccount": "true"}, headers=csrf)
    assert resp.status_code == 422, resp.text
    assert "其他社区仍有住户档案" in resp.json()["message"]

    db_session.expire_all()
    assert await db_session.scalar(
        select(Resident.id).where(Resident.id == first_id)) is not None
    user = await db_session.get(PlatformUser, int(account["profile"]["id"]))
    await db_session.refresh(user)
    assert user.status == "ACTIVE"


@pytest.mark.asyncio
async def test_batch_delete_residents_cancel_accounts(client, db_session):
    """批量删除可同时注销关联账号；未绑定账号的档案正常删除。"""
    csrf = await admin_login(client)
    phones = ["13900008881", "13900008882"]
    accounts = [await register_user(client, phone=phone) for phone in phones]
    ids: list[int] = []
    for phone in phones:
        resp = await client.post(f"{ADMIN_BASE}/residents",
                                 json=_resident_payload(phone=phone), headers=csrf)
        assert resp.status_code == 200, resp.text
        ids.append(int(resp.json()["data"]["id"]))
    resp = await client.post(f"{ADMIN_BASE}/residents",
                             json=_resident_payload(phone="13900008883"), headers=csrf)
    assert resp.status_code == 200, resp.text
    ids.append(int(resp.json()["data"]["id"]))

    resp = await client.post(f"{ADMIN_BASE}/residents/batch-delete",
                             json={"ids": ids, "cancelAccounts": True}, headers=csrf)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["deleted"] == 3
    assert data["cancelledAccounts"] == 2

    db_session.expire_all()
    for account in accounts:
        user = await db_session.get(PlatformUser, int(account["profile"]["id"]))
        await db_session.refresh(user)
        assert user.status == "CANCELLED"
        assert decrypt_field(user.phone_enc) == ""
    assert await db_session.scalar(
        select(Resident.id).where(Resident.id.in_(ids))) is None

    again = await register_user(client, phone=phones[0])
    assert again["isNewUser"] is True


@pytest.mark.asyncio
async def test_batch_delete_cancel_accounts_all_or_nothing(client, db_session):
    """批量注销时任一账号不满足条件，整批不执行（档案与账号均保留）。"""
    csrf = await admin_login(client)
    ok_phone, blocked_phone = "13900009991", "13900009992"
    ok_account = await register_user(client, phone=ok_phone)
    blocked_account = await register_user(client, phone=blocked_phone)
    blocked_user = await db_session.get(
        PlatformUser, int(blocked_account["profile"]["id"]))
    db_session.add(Item(community_id=1, seller_id=blocked_user.id,
                        title="测试物品", trade_type="FREE_GIFT"))
    await db_session.commit()

    ids: list[int] = []
    for phone in (ok_phone, blocked_phone):
        resp = await client.post(f"{ADMIN_BASE}/residents",
                                 json=_resident_payload(phone=phone), headers=csrf)
        assert resp.status_code == 200, resp.text
        ids.append(int(resp.json()["data"]["id"]))

    resp = await client.post(f"{ADMIN_BASE}/residents/batch-delete",
                             json={"ids": ids, "cancelAccounts": True}, headers=csrf)
    assert resp.status_code == 422, resp.text
    assert "存在发布物品" in resp.json()["message"]

    db_session.expire_all()
    assert await db_session.scalar(
        select(func.count()).select_from(Resident).where(Resident.id.in_(ids))) == 2
    for account in (ok_account, blocked_account):
        user = await db_session.get(PlatformUser, int(account["profile"]["id"]))
        await db_session.refresh(user)
        assert user.status == "ACTIVE"
