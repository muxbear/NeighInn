"""管理端会话 Cookie 的 Secure 属性：按实际访问协议自动判定。

回归背景：APP_ENV=prod 且管理端以纯 HTTP 暴露时，Cookie 若固定带 Secure，
浏览器会直接丢弃，登录成功后所有管理接口 401，前端闪回登录页。
"""

import pytest

from src.core.config import settings
from tests.conftest import ADMIN_BASE

LOGIN_BODY = {"username": "admin", "password": "Admin@2025"}


def _session_cookie_header(resp) -> str:
    for header in resp.headers.get_list("set-cookie"):
        if header.startswith(f"{settings.session_cookie_name}="):
            return header
    raise AssertionError(f"未找到会话 Cookie：{resp.headers.get_list('set-cookie')}")


@pytest.mark.asyncio
async def test_http_login_cookie_without_secure(client):
    resp = await client.post(f"{ADMIN_BASE}/auth/login", json=LOGIN_BODY)
    assert resp.status_code == 200, resp.text
    assert "secure" not in _session_cookie_header(resp).lower()


@pytest.mark.asyncio
async def test_https_forwarded_login_cookie_with_secure(client):
    resp = await client.post(
        f"{ADMIN_BASE}/auth/login",
        json=LOGIN_BODY,
        headers={"x-forwarded-proto": "https"},
    )
    assert resp.status_code == 200, resp.text
    assert "secure" in _session_cookie_header(resp).lower()
    csrf = next(header for header in resp.headers.get_list("set-cookie")
                if header.startswith("ni_csrf="))
    assert "secure" in csrf.lower()


@pytest.mark.asyncio
async def test_explicit_override_wins(client, monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    resp = await client.post(f"{ADMIN_BASE}/auth/login", json=LOGIN_BODY)
    assert resp.status_code == 200, resp.text
    assert "secure" in _session_cookie_header(resp).lower()
