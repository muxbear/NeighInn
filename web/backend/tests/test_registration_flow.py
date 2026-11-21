"""注册与新人引导集成测试（M01-01 / AC-01 前置链路）。

覆盖：注册意图与登录意图分离、注册资料完善/跳过/完成、协议留痕、
已注册/未注册提示、注销冷却期。
"""

import pytest
from sqlalchemy import select

from src.core.security import hmac_index
from src.db.models import Resident, User
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    admin_login,
    bearer,
    login_user,
    register_user,
)


async def _send_code(client, phone: str) -> str:
    from src.services.auth_service import sms_code_store

    await sms_code_store.clear(phone)
    resp = await client.post(f"{C_BASE}/auth/sms-code", json={"phone": phone})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["mockCode"]


async def _register(client, phone: str) -> dict:
    code = await _send_code(client, phone)
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone,
        "code": code,
        "intent": "register",
        "agreed": True,
        "agreementVersion": "2026-11-01",
        "privacyVersion": "2026-11-01",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_register_creates_new_user_with_onboarding_new(client):
    phone = "13955550001"
    data = await _register(client, phone)
    assert data["isNewUser"] is True
    assert data["onboardingStatus"] == "NEW"
    assert data["profile"]["onboardingStatus"] == "NEW"
    assert data["profile"]["phone"] == "139****0001"
    assert data["profile"]["authStatus"] == "LOGGED_IN_UNVERIFIED"


@pytest.mark.asyncio
async def test_sms_mock_enabled_allows_registration_outside_dev(client, monkeypatch):
    """内网演示：SMS_MOCK_ENABLED=true 时非 dev 环境也回显验证码并完成注册。"""
    from src.core.config import settings

    phone = "13955550009"
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "sms_mock_enabled", True)

    code = await _send_code(client, phone)
    assert len(code) == 6
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone,
        "code": code,
        "intent": "register",
        "agreed": True,
        "agreementVersion": "2026-11-01",
        "privacyVersion": "2026-11-01",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["isNewUser"] is True


@pytest.mark.asyncio
async def test_login_rejects_unregistered_phone(client):
    phone = "13955550002"
    code = await _send_code(client, phone)
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone, "code": code, "intent": "login",
    })
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401
    assert "未注册" in resp.json()["message"]


@pytest.mark.asyncio
async def test_register_rejects_registered_phone(client):
    phone = "13955550003"
    first = await register_user(client, phone)
    assert first["isNewUser"] is True

    code = await _send_code(client, phone)
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone,
        "code": code,
        "intent": "register",
        "agreed": True,
        "agreementVersion": "2026-11-01",
        "privacyVersion": "2026-11-01",
    })
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901
    assert "已注册" in resp.json()["message"]

    # 登录入口仍可正常登录（同一手机号唯一账号）
    again = await login_user(client, phone)
    assert again["isNewUser"] is False
    assert again["profile"]["id"] == first["profile"]["id"]


@pytest.mark.asyncio
async def test_register_requires_agreement(client):
    phone = "13955550004"
    code = await _send_code(client, phone)
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone, "code": code, "intent": "register", "agreed": False,
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


@pytest.mark.asyncio
async def test_complete_registration_saves_profile_and_finishes(client, db_session):
    phone = "13955550005"
    data = await _register(client, phone)
    headers = bearer(data["accessToken"])

    resp = await client.post(f"{C_BASE}/auth/register/complete", json={
        "nickname": "小林",
        "avatarKey": "avatar-person-2",
        "intentCommunityId": 1,
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    profile = resp.json()["data"]
    assert profile["onboardingStatus"] == "PROFILE_COMPLETED"
    assert profile["nickname"] == "小林"
    assert profile["avatarPreset"] == "avatar-person-2"
    assert profile["intentCommunityId"] == "1"
    assert profile["intentCommunityName"] == "阳光花园小区"

    me = await client.get(f"{C_BASE}/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["onboardingStatus"] == "PROFILE_COMPLETED"

    done = await client.post(f"{C_BASE}/auth/register/complete", json={"finish": True},
                             headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["onboardingStatus"] == "COMPLETED"

    user = await db_session.scalar(select(User).where(User.phone_hash == hmac_index(phone)))
    assert user is not None
    assert user.agreement_version == "2026-11-01"
    assert user.privacy_version == "2026-11-01"
    assert user.agreed_at is not None

    # 注册完成即建立未认证住户档案，后台「社区业主」按小区可见。
    resident = await db_session.scalar(
        select(Resident).where(Resident.user_id == user.id))
    assert resident is not None
    assert resident.community_id == 1
    assert resident.name == "小林"
    assert resident.certification_status == "UNVERIFIED"
    assert resident.status == "ACTIVE"


@pytest.mark.asyncio
async def test_complete_registration_requires_intent_community(client):
    phone = "13955550008"
    data = await _register(client, phone)
    headers = bearer(data["accessToken"])

    resp = await client.post(f"{C_BASE}/auth/register/complete", json={
        "nickname": "未选小区",
    }, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001
    assert "入住小区" in resp.json()["message"]


@pytest.mark.asyncio
async def test_registered_user_visible_in_admin_residents(client):
    phone = "13955550009"
    data = await _register(client, phone)
    headers = bearer(data["accessToken"])
    resp = await client.post(f"{C_BASE}/auth/register/complete", json={
        "nickname": "后台可见住户",
        "intentCommunityId": 1,
    }, headers=headers)
    assert resp.status_code == 200, resp.text

    csrf = await admin_login(client)
    listed = await client.get(
        f"{ADMIN_BASE}/residents",
        params={"communityId": 1, "keyword": "后台可见住户"},
        headers=csrf,
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["nickname"] == "后台可见住户"
    assert items[0]["communityId"] == "1"
    assert items[0]["certification"] == "UNVERIFIED"

    summary = await client.get(
        f"{ADMIN_BASE}/residents/summary", params={"communityId": 1}, headers=csrf)
    assert summary.status_code == 200, summary.text
    assert summary.json()["data"]["pending"] >= 1


@pytest.mark.asyncio
async def test_complete_registration_skip_and_validation(client):
    phone = "13955550006"
    data = await _register(client, phone)
    headers = bearer(data["accessToken"])

    # 空昵称
    resp = await client.post(f"{C_BASE}/auth/register/complete", json={"nickname": "  "},
                             headers=headers)
    assert resp.status_code == 400
    # 非法头像
    resp = await client.post(f"{C_BASE}/auth/register/complete", json={
        "nickname": "邻居", "avatarKey": "not-an-avatar",
    }, headers=headers)
    assert resp.status_code == 400
    # 非法小区
    resp = await client.post(f"{C_BASE}/auth/register/complete", json={
        "nickname": "邻居", "intentCommunityId": 999999,
    }, headers=headers)
    assert resp.status_code == 400

    # 跳过资料：仍进入成功引导页
    resp = await client.post(f"{C_BASE}/auth/register/complete", json={"skip": True},
                             headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["onboardingStatus"] == "PROFILE_COMPLETED"


def test_onboarding_status_column_fits_all_values():
    """PostgreSQL 严格校验 varchar 长度：PROFILE_COMPLETED 必须装得下。

    SQLite 测试库不校验长度，需显式守护列宽，避免再次出现「完成注册」500。
    """
    values = ("NEW", "PROFILE_COMPLETED", "COMPLETED")
    column = User.__table__.c.onboarding_status
    assert column.type.length >= max(len(value) for value in values)


@pytest.mark.asyncio
async def test_cancelled_account_has_seven_day_cooldown(client, db_session):
    phone = "13955550007"
    data = await _register(client, phone)
    user = await db_session.scalar(select(User).where(User.phone_hash == hmac_index(phone)))
    assert user is not None
    user.status = "CANCELLED"
    await db_session.commit()

    code = await _send_code(client, phone)
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone,
        "code": code,
        "intent": "register",
        "agreed": True,
        "agreementVersion": "2026-11-01",
        "privacyVersion": "2026-11-01",
    })
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901
    assert "7 个自然日" in resp.json()["message"]
    assert data["profile"]["id"] == str(user.id)
