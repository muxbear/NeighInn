"""集成测试基座：SQLite 内存库（StaticPool）+ 依赖覆盖 + 幂等种子。

生产库为 PostgreSQL（JSONB/BigInteger），测试库为 SQLite（JSON/Integer），
模型层通过类型变体（src/db/models/common.py）保证两库行为等价。
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# 测试固定使用进程内会话/验证码存储，避免依赖外部 Redis 或污染其数据。
os.environ["REDIS_URL"] = ""
os.environ["SMS_CODE_BACKEND"] = "memory"

from src.db.base import Base, get_db
from src.db.seed import seed_if_empty
from src.main import app


@pytest.fixture()
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_maker(engine):
    """请求级会话工厂（与生产 get_db 一致：每个请求独立会话）。
    StaticPool 保证内存库在会话间共享，commit 后互可见。"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as seed_session:
        await seed_if_empty(seed_session)
    yield maker


@pytest.fixture()
async def db_session(session_maker):
    """测试断言专用会话。"""
    async with session_maker() as session:
        yield session


@pytest.fixture()
async def client(session_maker, db_session):
    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------- 通用流程辅助

C_BASE = "/api/v1"
ADMIN_BASE = "/api/v1/admin"
TEST_PHONE = "13900001111"


async def register_user(client: AsyncClient, phone: str = TEST_PHONE) -> dict:
    """短信注册全流程：返回 {token, profile}。
    测试内清理验证码与冷却（模块级存储跨用例共享）。"""
    from src.services.auth_service import sms_code_store

    await sms_code_store.clear(phone)
    resp = await client.post(f"{C_BASE}/auth/sms-code", json={"phone": phone})
    assert resp.status_code == 200, resp.text
    code = resp.json()["data"]["mockCode"]
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone,
        "code": code,
        "intent": "register",
        "agreed": True,
        "agreementVersion": "test-v1",
        "privacyVersion": "test-v1",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return {
        "token": data["accessToken"],
        "refresh": data["refreshToken"],
        "profile": data["profile"],
        "isNewUser": data["isNewUser"],
        "onboardingStatus": data["onboardingStatus"],
    }


async def login_user(client: AsyncClient, phone: str = TEST_PHONE) -> dict:
    """已注册用户短信登录：返回 {token, profile}。"""
    from src.services.auth_service import sms_code_store

    await sms_code_store.clear(phone)
    resp = await client.post(f"{C_BASE}/auth/sms-code", json={"phone": phone})
    assert resp.status_code == 200, resp.text
    code = resp.json()["data"]["mockCode"]
    resp = await client.post(f"{C_BASE}/auth/login/sms", json={
        "phone": phone,
        "code": code,
        "intent": "login",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return {
        "token": data["accessToken"],
        "refresh": data["refreshToken"],
        "profile": data["profile"],
        "isNewUser": data["isNewUser"],
        "onboardingStatus": data["onboardingStatus"],
    }


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def admin_login(client: AsyncClient, username: str = "admin",
                      password: str = "Admin@2025") -> dict:
    """管理员登录：httpx 自动保存会话 Cookie；返回带 CSRF 头的 headers。"""
    resp = await client.post(f"{ADMIN_BASE}/auth/login",
                             json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    csrf = resp.json()["data"]["csrfToken"]
    return {"x-csrf-token": csrf}


def admin_headers(client: AsyncClient) -> dict:
    """实时读取当前会话的 CSRF Cookie（避免多次登录后旧头过期）。"""
    return {"x-csrf-token": client.cookies.get("ni_csrf", "")}


async def submit_owner_proof(client: AsyncClient, token: str, community_id: int = 1) -> dict:
    resp = await client.post(
        f"{C_BASE}/auth/owner-proof",
        json={"communityId": community_id, "identity": "owner",
              "images": ["certs/proof-front.jpg", "certs/proof-back.jpg"]},
        headers=bearer(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def verify_realname(client: AsyncClient, csrf_headers: dict, token: str) -> None:
    """实名提交 + 后台审核通过（业主证明的前置条件，SRS 4.1）。"""
    resp = await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/id-front.jpg", "backImage": "certs/id-back.jpg",
              "faceToken": "ft"},
        headers=bearer(token),
    )
    assert resp.status_code == 200, resp.text
    cert = await first_pending_cert(client, csrf_headers, "REALNAME")
    resp = await client.post(
        f"{ADMIN_BASE}/certifications/{cert['id']}/approve", headers=csrf_headers)
    assert resp.status_code == 200, resp.text


async def first_pending_cert(client: AsyncClient, csrf_headers: dict,
                             cert_type: str = "OWNER_PROOF") -> dict:
    resp = await client.get(f"{ADMIN_BASE}/certifications",
                            params={"status": "PENDING", "type": cert_type})
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert items, f"审核队列为空（type={cert_type}）"
    return items[0]


async def verified_user(client: AsyncClient, phone: str, community_id: int = 1) -> dict:
    """注册 + 实名通过 + 业主证明通过（后台审核）的完整认证用户。"""
    csrf = await admin_login(client)
    account = await register_user(client, phone)
    await verify_realname(client, csrf, account["token"])
    await submit_owner_proof(client, account["token"], community_id)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    resp = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf)
    assert resp.status_code == 200, resp.text
    return {**account, "communityId": community_id}


DEFAULT_DRAFT = {
    "title": "九成新儿童平衡车",
    "tradeType": "MONETARY",
    "priceCents": 12800,
    "barterExpect": "",
    "condition": "九九新",
    "category": "母婴用品",
    "qualityDesc": "孩子只骑过三次，车身无划痕，刹车灵敏，附赠护具一套。",
    "images": ["items/bike-1.jpg", "items/bike-2.jpg", "items/bike-3.jpg"],
    "invoices": [],
    "videoUrl": "",
    "expectTime": "工作日晚上",
}


async def create_draft(client: AsyncClient, token: str, **overrides) -> str:
    payload = {**DEFAULT_DRAFT, **overrides}
    resp = await client.post(f"{C_BASE}/items", json=payload, headers=bearer(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


async def submit_item(client: AsyncClient, token: str, item_id: str) -> dict:
    resp = await client.post(f"{C_BASE}/items/{item_id}/submit", headers=bearer(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def create_on_sale_item(client: AsyncClient, csrf: dict, token: str,
                              **overrides) -> str:
    """创建并通过 AI + 人工复核上架的物品，返回 item_id。"""
    item_id = await create_draft(client, token, **overrides)
    result = await submit_item(client, token, item_id)
    if result["status"] == "PENDING_REVIEW":
        resp = await client.post(f"{ADMIN_BASE}/items/{item_id}/review",
                                 json={"decision": "APPROVE"}, headers=csrf)
        assert resp.status_code == 200, resp.text
    return item_id


async def create_order(client: AsyncClient, token: str, item_id: str,
                       **overrides) -> dict:
    payload = {"itemId": int(item_id), **overrides}
    resp = await client.post(f"{C_BASE}/orders", json=payload, headers=bearer(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def pay_order(client: AsyncClient, token: str, order_id: str) -> dict:
    """预支付 + Mock 渠道回调完成托管。"""
    resp = await client.post(f"{C_BASE}/payments/prepay",
                             json={"orderId": int(order_id), "method": "wechat"},
                             headers=bearer(token))
    assert resp.status_code == 200, resp.text
    params = resp.json()["data"]["payParams"]
    txn_no = params["mockPayUrl"].rsplit("/", 1)[-1]
    resp = await client.post(f"{C_BASE}/payments/mock-callback",
                             json={"txnNo": txn_no, "sign": params["sign"]})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


APPOINTMENT_ISO = "2026-11-20T14:00:00"


async def make_appointment(client: AsyncClient, token: str, order_id: str) -> None:
    resp = await client.post(
        f"{C_BASE}/orders/{order_id}/appointment",
        json={"time": APPOINTMENT_ISO, "place": "物业中心", "note": ""},
        headers=bearer(token))
    assert resp.status_code == 200, resp.text


async def both_confirm_satisfied(client: AsyncClient, buyer_token: str,
                                 seller_token: str, order_id: str) -> dict:
    resp = await client.post(f"{C_BASE}/orders/{order_id}/confirm",
                             json={"satisfied": True}, headers=bearer(buyer_token))
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"{C_BASE}/orders/{order_id}/confirm",
                             json={"satisfied": True}, headers=bearer(seller_token))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]
