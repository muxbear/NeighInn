"""冒烟测试：应用可导入、健康检查通过、OpenAPI 契约完整（双端前缀齐全）。"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.mark.asyncio
async def test_liveness():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_mobile_h5_cors_preflight(client):
    """移动端 H5（5191；兼容 Vite 默认 5173）必须通过 CORS 预检。"""
    for origin in ("http://localhost:5173", "http://localhost:5191"):
        resp = await client.options(
            "/api/v1/auth/sms-code",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-idempotency-key,x-trace-id",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["access-control-allow-origin"] == origin


def test_openapi_contract_surface():
    """契约骨架：C 端与管理端关键路径均已声明。"""
    spec = app.openapi()
    paths = set(spec["paths"].keys())

    # C 端契约（mobile/api/*.api.ts）
    c_end_required = {
        "/api/v1/auth/login/sms",
        "/api/v1/auth/realname",
        "/api/v1/auth/owner-proof",
        "/api/v1/home",
        "/api/v1/items",
        "/api/v1/items/{item_id}/audit-progress",
        "/api/v1/orders",
        "/api/v1/orders/{order_id}/dispute",
        "/api/v1/payments/prepay",
        "/api/v1/wallet",
        "/api/v1/wallet/withdrawals",
        "/api/v1/notifications",
        "/api/v1/conversations",
        "/api/v1/friends/requests",
        "/api/v1/communities/nearby",
        "/api/v1/uploads/presign",
        "/api/v1/reports",
    }
    # 管理端契约（web 前端调用面 + P0 缺口）
    admin_required = {
        "/api/v1/admin/auth/login",
        "/api/v1/admin/auth/login/2fa",
        "/api/v1/admin/dashboard/summary",
        "/api/v1/admin/certifications",
        "/api/v1/admin/certifications/{certification_id}/approve",
        "/api/v1/admin/items/{item_id}/ai-audit",
        "/api/v1/admin/items/{item_id}/review",
        "/api/v1/admin/finance/overview",
        "/api/v1/admin/finance/withdrawals/{withdrawal_id}/review",
        "/api/v1/admin/finance/adjustments",
        "/api/v1/admin/finance/orders",
        "/api/v1/admin/disputes/{dispute_id}/resolve",
        "/api/v1/admin/reports",
        "/api/v1/admin/users/{user_id}/penalties",
        "/api/v1/admin/audit-logs",
        "/api/v1/admin/exports",
    }
    missing = (c_end_required | admin_required) - paths
    assert not missing, f"OpenAPI 缺少契约路径: {sorted(missing)}"


def test_error_envelope_on_unknown_route():
    """统一错误响应 {code,message,data,traceId}。"""
    import asyncio

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/definitely-not-exists")

    response = asyncio.run(_run())
    body = response.json()
    assert body["code"] == 40401
    assert "traceId" in body
