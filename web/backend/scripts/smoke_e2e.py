"""端到端冒烟脚本（对运行中的统一服务端执行真实 HTTP 流程）。

用法：先启动服务（uv run python run.py 或 DEBUG=false ... uvicorn），再执行
    uv run python scripts/smoke_e2e.py

覆盖：注册登录 → 实名提交 → 管理端登录（Cookie+CSRF）→ 审核通过 → 业主证明 →
审核通过 → 绑定查询 → 首页聚合。全链路断言统一响应信封与状态机。
"""

from __future__ import annotations

import http.cookiejar
import json
import urllib.request

BASE = "http://127.0.0.1:5193"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(method: str, path: str, body: dict | None = None, token: str | None = None,
         csrf: bool = False) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if csrf:
        for cookie in cj:
            if cookie.name == "ni_csrf":
                headers["X-CSRF-Token"] = cookie.value
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    with opener.open(request) as response:
        return json.loads(response.read())


def main() -> None:
    import time

    # 每次运行使用唯一手机号（注册幂等性要求）
    phone = f"139{int(time.time()) % 100000000:08d}"
    masked = f"{phone[:3]}****{phone[-4:]}"

    # 健康检查
    assert call("GET", "/health/live")["status"] == "ok"

    # C 端：注册登录（注册意图；登录意图不会自动建号）
    code = call("POST", "/api/v1/auth/sms-code", {"phone": phone})["data"]["mockCode"]
    login = call("POST", "/api/v1/auth/login/sms", {
        "phone": phone,
        "code": code,
        "intent": "register",
        "agreed": True,
        "agreementVersion": "smoke-v1",
        "privacyVersion": "smoke-v1",
    })["data"]
    access = login["accessToken"]
    assert login["isNewUser"] is True
    assert login["onboardingStatus"] == "NEW"
    assert login["profile"]["authStatus"] == "LOGGED_IN_UNVERIFIED"
    assert login["profile"]["phone"] == masked
    print("✓ 注册登录（脱敏手机号展示）")

    # 新人引导：完善资料（头像/昵称）
    onboard = call("POST", "/api/v1/auth/register/complete", {
        "nickname": "冒烟邻居", "avatarKey": "avatar-person-1",
    }, token=access)["data"]
    assert onboard["onboardingStatus"] == "PROFILE_COMPLETED"
    assert onboard["nickname"] == "冒烟邻居"
    print("✓ 注册新人引导（资料完善）")

    # 实名认证提交
    realname = call("POST", "/api/v1/auth/realname",
                    {"frontImage": "certs/f.jpg", "backImage": "certs/b.jpg", "faceToken": "ft"},
                    token=access)["data"]
    assert realname["status"] == "PENDING"
    print("✓ 实名认证提交 → PENDING")

    # 管理端登录 + CSRF
    admin = call("POST", "/api/v1/admin/auth/login",
                 {"username": "admin", "password": "Admin@2025"})["data"]
    assert admin["admin"]["isSuperAdmin"] is True
    assert len(admin["admin"]["permissions"]) >= 80
    print(f"✓ 管理端登录（{len(admin['admin']['permissions'])} 项权限）")

    # 审核队列：实名通过
    queue = call("GET", "/api/v1/admin/certifications?status=PENDING&type=REALNAME")["data"]
    cert = next((item for item in queue["items"] if item["user"]["phone"] == masked), None)
    assert cert is not None, "审核队列中未找到本用户的实名审核单"
    approved = call("POST", f"/api/v1/admin/certifications/{cert['id']}/approve", {}, csrf=True)
    assert approved["code"] == 0
    status = call("GET", "/api/v1/auth/status", token=access)["data"]
    assert status["status"] == "VERIFIED_UNOWNER"
    print("✓ 实名审核通过 → VERIFIED_UNOWNER")

    # 业主证明 → 审核 → 绑定
    proof = call("POST", "/api/v1/auth/owner-proof",
                 {"communityId": 1, "identity": "owner", "images": ["certs/p1.jpg"]},
                 token=access)["data"]
    assert proof["status"] == "PENDING"
    queue = call("GET", "/api/v1/admin/certifications?status=PENDING&type=OWNER_PROOF")["data"]
    cert = next((item for item in queue["items"] if item["user"]["phone"] == masked), None)
    assert cert is not None, "审核队列中未找到本用户的业主证明审核单"
    assert cert["community"]["name"] == "阳光花园小区"
    call("POST", f"/api/v1/admin/certifications/{cert['id']}/approve", {}, csrf=True)
    status = call("GET", "/api/v1/auth/status", token=access)["data"]
    assert status["status"] == "VERIFIED_OWNER"
    mine = call("GET", "/api/v1/communities/mine", token=access)["data"]
    assert mine[0]["name"] == "阳光花园小区" and mine[0]["status"] == "已认证"
    print("✓ 业主证明审核通过 → VERIFIED_OWNER，小区已绑定")

    # 首页聚合（认证通过通知入账）
    home = call("GET", "/api/v1/home", token=access)["data"]
    assert home["community"]["name"] == "阳光花园小区"
    assert home["notificationUnread"] >= 2
    assert len(home["zones"]) == 4
    print(f"✓ 首页聚合（未读通知 {home['notificationUnread']} 条，四专属区就位）")

    # 通知中心
    notifications = call("GET", "/api/v1/notifications", token=access)["data"]
    assert notifications["total"] >= 2
    assert notifications["items"][0]["category"] == "社区"
    print("✓ 通知中心（审核结果分类入账）")

    print("\n全部通过：认证闭环 AC-01 在真实 HTTP 链路上成立")


if __name__ == "__main__":
    main()
