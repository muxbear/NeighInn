"""C 端认证域集成测试（M01 + W02 联动，对应 AC-01）。

覆盖：注册登录 → 实名/业主证明提交 → 后台审核 → 小区绑定 → 状态机全链路。
"""

import pytest
from sqlalchemy import func, select

from src.db.models import AppNotification, AuditLog, Resident
from tests.conftest import (
    ADMIN_BASE,
    C_BASE,
    TEST_PHONE,
    admin_login,
    bearer,
    first_pending_cert,
    login_user,
    register_user,
    submit_owner_proof,
    verify_realname,
)


@pytest.mark.asyncio
async def test_sms_register_login_and_profile(client):
    result = await register_user(client)
    assert result["isNewUser"] is True
    assert result["profile"]["phone"] == "139****1111"  # 全链路脱敏（SRS 9.2）
    assert result["profile"]["authStatus"] == "LOGGED_IN_UNVERIFIED"

    # 再次登录：同一手机号唯一账号（M01-01）
    again = await login_user(client)
    assert again["isNewUser"] is False
    assert again["profile"]["id"] == result["profile"]["id"]

    me = await client.get(f"{C_BASE}/users/me", headers=bearer(result["token"]))
    assert me.status_code == 200
    assert me.json()["data"]["id"] == result["profile"]["id"]


@pytest.mark.asyncio
async def test_wrong_sms_code_rejected(client):
    await client.post(f"{C_BASE}/auth/sms-code", json={"phone": TEST_PHONE})
    resp = await client.post(f"{C_BASE}/auth/login/sms",
                             json={"phone": TEST_PHONE, "code": "000000"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


@pytest.mark.asyncio
async def test_sms_code_requires_provider_outside_dev(client, monkeypatch):
    """非 dev 环境未接短信通道时必须显式报错，避免“发送成功但收不到”。"""
    from src.core.config import settings

    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "sms_mock_enabled", False)
    resp = await client.post(f"{C_BASE}/auth/sms-code", json={"phone": TEST_PHONE})
    assert resp.status_code == 503
    assert resp.json()["code"] == 50301


@pytest.mark.asyncio
async def test_auth_status_transitions(client):
    result = await register_user(client)
    headers = bearer(result["token"])

    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "LOGGED_IN_UNVERIFIED"
    assert status["realnameVerified"] is False

    # 提交实名认证
    resp = await client.post(f"{C_BASE}/auth/realname",
                             json={"frontImage": "certs/id-front.jpg",
                                   "backImage": "certs/id-back.jpg", "faceToken": "ft"},
                             headers=headers)
    assert resp.status_code == 200, resp.text

    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "VERIFYING"

    # 重复提交被阻止（40901）
    dup = await client.post(f"{C_BASE}/auth/realname",
                            json={"frontImage": "a.jpg", "backImage": "b.jpg"},
                            headers=headers)
    assert dup.status_code == 409
    assert dup.json()["code"] == 40901


@pytest.mark.asyncio
async def test_owner_proof_allowed_without_realname(client):
    """实名与住户认证相互独立：未实名也可提交住户认证。"""
    result = await register_user(client)
    resp = await client.post(f"{C_BASE}/auth/owner-proof",
                             json={"communityId": 1, "identity": "owner",
                                   "images": ["a.jpg"]}, headers=bearer(result["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "PENDING"

    status = (await client.get(f"{C_BASE}/auth/status",
                               headers=bearer(result["token"]))).json()["data"]
    assert status["realname"]["status"] == "UNVERIFIED"
    assert status["owner"]["status"] == "PENDING"
    assert status["status"] == "PENDING_AUDIT"
    assert status["realnameVerified"] is False
    assert status["ownerVerified"] is False


@pytest.mark.asyncio
async def test_owner_only_approval_grants_owner_badge(client):
    """住户认证可独立审核通过；实名状态仍保持未认证。"""
    result = await register_user(client)
    await client.post(f"{C_BASE}/auth/owner-proof",
                      json={"communityId": 1, "identity": "owner",
                            "images": ["a.jpg"]}, headers=bearer(result["token"]))
    csrf = await admin_login(client)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    resp = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf)
    assert resp.status_code == 200, resp.text

    status = (await client.get(f"{C_BASE}/auth/status",
                               headers=bearer(result["token"]))).json()["data"]
    assert status["status"] == "VERIFIED_OWNER"
    assert status["ownerVerified"] is True
    assert status["realnameVerified"] is False
    assert status["owner"]["communityName"] == "阳光花园小区"

    profile = (await client.get(f"{C_BASE}/users/me",
                                headers=bearer(result["token"]))).json()["data"]
    assert profile["ownerVerified"] is True
    assert profile["realnameVerified"] is False
    assert profile["realnameStatus"] == "UNVERIFIED"
    assert profile["ownerStatus"] == "VERIFIED"


@pytest.mark.asyncio
async def test_owner_proof_submit_and_pending_status(client):
    result = await register_user(client)
    headers = bearer(result["token"])
    await client.post(f"{C_BASE}/auth/realname",
                      json={"frontImage": "certs/f.jpg", "backImage": "certs/b.jpg",
                            "faceToken": "ft"}, headers=headers)
    csrf = await admin_login(client)
    realname = await first_pending_cert(client, csrf, "REALNAME")
    await client.post(f"{ADMIN_BASE}/certifications/{realname['id']}/approve", headers=csrf)

    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "VERIFIED_UNOWNER"

    data = await submit_owner_proof(client, result["token"], community_id=1)
    assert data["status"] == "PENDING"
    assert data["auditHours"] == 24

    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "PENDING_AUDIT"

    # 不存在的小区被拒绝
    bad = await client.post(f"{C_BASE}/auth/owner-proof",
                            json={"communityId": 9999, "identity": "owner",
                                  "images": ["a.jpg"]}, headers=headers)
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_full_certification_flow_to_binding(client, db_session):
    """AC-01：注册 → 实名 → 业主证明 → 后台审核 → 绑定小区 全流程无阻断。"""
    result = await register_user(client)
    headers = bearer(result["token"])

    await client.post(f"{C_BASE}/auth/realname",
                      json={"frontImage": "certs/f.jpg", "backImage": "certs/b.jpg",
                            "faceToken": "ft"}, headers=headers)

    csrf = await admin_login(client)

    # 后台审核队列（W02）先审实名
    realname = await first_pending_cert(client, csrf, "REALNAME")
    assert realname["user"]["phone"] == "139****1111"  # 审核队列脱敏（W02-01）
    resp = await client.post(
        f"{ADMIN_BASE}/certifications/{realname['id']}/approve", headers=csrf)
    assert resp.status_code == 200, resp.text

    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "VERIFIED_UNOWNER"

    # 实名通过后才能提交业主证明（SRS 4.1 顺序）
    await submit_owner_proof(client, result["token"], community_id=1)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    assert proof["community"]["name"] == "阳光花园小区"  # 与移动端 Mock 夹具对齐

    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "PENDING_AUDIT"  # 实名已过，业主证明待审

    # 后台审核通过业主证明 → 账号与小区强绑定（BR-02/W02-02）
    resp = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf)
    assert resp.status_code == 200, resp.text

    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "VERIFIED_OWNER"
    assert status["realnameVerified"] and status["ownerVerified"]

    profile = (await client.get(f"{C_BASE}/users/me", headers=headers)).json()["data"]
    assert profile["communityName"] == "阳光花园小区"
    assert profile["verified"] is True

    mine = (await client.get(f"{C_BASE}/communities/mine", headers=headers)).json()["data"]
    assert len(mine) == 1
    assert mine[0]["name"] == "阳光花园小区"
    assert mine[0]["status"] == "已认证"

    # 审核结果通知（M01-04：站内信）
    notifications = (await db_session.execute(
        select(func.count()).select_from(AppNotification)
        .where(AppNotification.user_id == int(result["profile"]["id"]))
    )).scalar()
    assert notifications == 2

    # 审核动作全部留痕（W01-03/AC-08）
    audits = (await db_session.execute(
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.resource_type == "certification")
    )).scalar()
    assert audits == 2


@pytest.mark.asyncio
async def test_reject_requires_reason_and_notifies(client, db_session):
    result = await register_user(client)
    headers = bearer(result["token"])
    await client.post(f"{C_BASE}/auth/realname",
                      json={"frontImage": "certs/f.jpg", "backImage": "certs/b.jpg",
                            "faceToken": "ft"}, headers=headers)
    csrf = await admin_login(client)
    realname = await first_pending_cert(client, csrf, "REALNAME")
    await client.post(f"{ADMIN_BASE}/certifications/{realname['id']}/approve", headers=csrf)
    await submit_owner_proof(client, result["token"], community_id=2)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")

    # 原因过短被拒绝（守卫：≥10 字）
    short = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/reject",
        json={"reason": "不清楚"}, headers=csrf)
    assert short.status_code == 400
    assert short.json()["code"] == 40001

    reason = "房产证照片模糊无法辨认产权人信息，请在自然光下重新拍摄"
    resp = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/reject",
        json={"reason": reason}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["rejectCount"] == 1

    # 驳回原因可读且可重提（M01-04/M01-05）
    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["status"] == "REJECTED"
    assert status["rejectReason"] == reason
    assert status["canResubmit"] is True

    note = await db_session.scalar(
        select(AppNotification)
        .where(AppNotification.user_id == int(result["profile"]["id"]))
        .order_by(AppNotification.id.desc()))
    assert note is not None and "驳回" in note.title and reason in note.description


@pytest.mark.asyncio
async def test_supplement_resubmit_reuses_pending_cert(client):
    """要求补充材料后，用户重新提交应复用原审核单，不产生第二条待办。"""
    result = await register_user(client)
    headers = bearer(result["token"])
    first = await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/f.jpg", "backImage": "certs/b.jpg"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["data"]["certId"]

    csrf = await admin_login(client)
    cert = await first_pending_cert(client, csrf, "REALNAME")
    resp = await client.post(
        f"{ADMIN_BASE}/certifications/{cert['id']}/request-materials",
        json={"note": "请补充身份证国徽面清晰照片"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    status = (await client.get(f"{C_BASE}/auth/status", headers=headers)).json()["data"]
    assert status["realname"]["status"] == "SUPPLEMENT"
    assert "补充" in status["realname"]["rejectReason"]

    again = await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/f2.jpg", "backImage": "certs/b2.jpg"},
        headers=headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["data"]["certId"] == first_id

    queue = (await client.get(
        f"{ADMIN_BASE}/certifications",
        params={"status": "PENDING", "type": "REALNAME"}, headers=csrf,
    )).json()["data"]
    assert queue["total"] == 1
    assert queue["items"][0]["id"] == first_id


@pytest.mark.asyncio
async def test_idempotent_approve_returns_cached_result(client, db_session):
    result = await register_user(client)
    csrf = await admin_login(client)
    await verify_realname(client, csrf, result["token"])
    await submit_owner_proof(client, result["token"], community_id=1)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")

    idem_headers = {**csrf, "X-Idempotency-Key": "test-approve-0001"}
    first = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=idem_headers)
    assert first.status_code == 200, first.text

    second = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=idem_headers)
    assert second.status_code == 200, second.text
    assert second.json()["data"]["id"] == first.json()["data"]["id"]

    # 幂等重放不产生重复审计（SRS 8.3 幂等语义）
    audits = (await db_session.execute(
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.action == "certification.owner_proof.approve")
    )).scalar()
    assert audits == 1

    # 无幂等键的重复审核：状态机拒绝非法迁移（40904）
    third = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf)
    assert third.status_code == 409
    assert third.json()["code"] == 40904


@pytest.mark.asyncio
async def test_freeze_auto_off_shelves_items(client, db_session):
    """W02-04：冻结后该用户所有在售物品自动下架。"""
    from src.db.models import Item

    result = await register_user(client)
    csrf = await admin_login(client)
    await verify_realname(client, csrf, result["token"])
    await submit_owner_proof(client, result["token"], community_id=1)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    await client.post(f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf)

    user_id = int(result["profile"]["id"])
    db_session.add(Item(community_id=1, seller_id=user_id, title="九成新儿童平衡车",
                        trade_type="MONETARY", price_cents=12800, status="ON_SALE"))
    db_session.add(Item(community_id=1, seller_id=user_id, title="露营折叠椅两把",
                        trade_type="FREE_GIFT", price_cents=0, status="ON_SALE"))
    db_session.add(Item(community_id=1, seller_id=user_id, title="草稿箱物品",
                        trade_type="BARTER", price_cents=0, status="DRAFT"))
    await db_session.commit()

    resident = await db_session.scalar(
        select(Resident).where(Resident.user_id == user_id))
    resp = await client.post(f"{ADMIN_BASE}/residents/{resident.id}/freeze", headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["itemsOffShelves"] == 2  # 草稿不受影响

    items = (await db_session.execute(
        select(Item).where(Item.seller_id == user_id))).scalars().all()
    by_title = {item.title: item.status for item in items}
    assert by_title["九成新儿童平衡车"] == "OFF_SHELF"
    assert by_title["露营折叠椅两把"] == "OFF_SHELF"
    assert by_title["草稿箱物品"] == "DRAFT"

    # 解冻恢复认证（物品需手动重新上架）
    resp = await client.post(f"{ADMIN_BASE}/residents/{resident.id}/unfreeze", headers=csrf)
    assert resp.status_code == 200, resp.text
    await db_session.refresh(resident)
    assert resident.certification_status == "VERIFIED"


@pytest.mark.asyncio
async def test_revoke_certification(client, db_session):
    result = await register_user(client)
    csrf = await admin_login(client)
    await verify_realname(client, csrf, result["token"])
    await submit_owner_proof(client, result["token"], community_id=1)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    await client.post(f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf)

    resident = await db_session.scalar(
        select(Resident).where(Resident.user_id == int(result["profile"]["id"])))
    resp = await client.post(f"{ADMIN_BASE}/residents/{resident.id}/revoke", headers=csrf)
    assert resp.status_code == 200, resp.text
    await db_session.refresh(resident)
    assert resident.certification_status == "REVOKED"
    assert resident.certification_no == ""


@pytest.mark.asyncio
async def test_certification_queue_scoped_by_community(client):
    """后台认证队列按小区过滤：业主认证按目标小区，实名认证按申请人档案归属。

    实名认证单本身不绑定 community_id，选择小区后必须通过住户档案归属，
    否则「实名认证待审」会被整体过滤为空（顶部小区筛选上线后的回归保障）。
    """
    first = await register_user(client, "13900004444")
    await client.post(
        f"{C_BASE}/auth/register/complete",
        json={"nickname": "邻居甲", "intentCommunityId": 1},
        headers=bearer(first["token"]),
    )
    await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/f1.jpg", "backImage": "certs/b1.jpg"},
        headers=bearer(first["token"]),
    )
    await submit_owner_proof(client, first["token"], community_id=1)

    second = await register_user(client, "13900005555")
    await client.post(
        f"{C_BASE}/auth/register/complete",
        json={"nickname": "邻居乙", "intentCommunityId": 2},
        headers=bearer(second["token"]),
    )
    await client.post(
        f"{C_BASE}/auth/realname",
        json={"frontImage": "certs/f2.jpg", "backImage": "certs/b2.jpg"},
        headers=bearer(second["token"]),
    )
    await submit_owner_proof(client, second["token"], community_id=2)

    csrf = await admin_login(client)

    async def queue_names(params: dict) -> set[str]:
        resp = await client.get(f"{ADMIN_BASE}/certifications", params=params, headers=csrf)
        assert resp.status_code == 200, resp.text
        return {item["user"]["nickname"] for item in resp.json()["data"]["items"]}

    assert await queue_names({"status": "PENDING", "type": "REALNAME", "communityId": 1}) == {"邻居甲"}
    assert await queue_names({"status": "PENDING", "type": "OWNER_PROOF", "communityId": 1}) == {"邻居甲"}
    assert await queue_names({"status": "PENDING", "type": "REALNAME", "communityId": 2}) == {"邻居乙"}
    assert await queue_names({"status": "PENDING", "type": "OWNER_PROOF", "communityId": 2}) == {"邻居乙"}

    summary = (await client.get(
        f"{ADMIN_BASE}/certifications/summary",
        params={"communityId": 1}, headers=csrf,
    )).json()["data"]
    assert summary["pendingRealname"] == 1
    assert summary["pendingOwner"] == 1


@pytest.mark.asyncio
async def test_admin_endpoints_require_auth(client):
    resp = await client.get(f"{ADMIN_BASE}/certifications")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


@pytest.mark.asyncio
async def test_admin_write_requires_csrf(client):
    csrf = await admin_login(client)
    result = await register_user(client, "13900002222")
    await verify_realname(client, csrf, result["token"])
    await submit_owner_proof(client, result["token"], community_id=1)
    resp = await client.get(f"{ADMIN_BASE}/certifications",
                            params={"status": "PENDING", "type": "OWNER_PROOF"})
    cert_id = resp.json()["data"]["items"][0]["id"]
    # 缺 CSRF 头的写操作被拒绝
    resp = await client.post(f"{ADMIN_BASE}/certifications/{cert_id}/approve")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301


class _FakeMaterialObject:
    """模拟 MinIO get_object 返回的可读对象（只需 read/close/release_conn）。"""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class _FakeMinio:
    def __init__(self, payload: bytes):
        self._payload = payload

    def get_object(self, bucket: str, key: str) -> _FakeMaterialObject:
        from src.core.config import settings

        assert bucket == settings.minio_bucket_private
        return _FakeMaterialObject(self._payload)


@pytest.mark.asyncio
async def test_rejected_certification_can_be_reapproved(client):
    """已驳回的审核单可在「住户认证」页复核通过。

    场景：住户无法自行重新提交，或线下已补验纸质材料；管理员核对后
    应能直接恢复认证，而不是被“不能再次审核”卡住。
    """
    result = await register_user(client)
    await submit_owner_proof(client, result["token"], community_id=1)
    csrf = await admin_login(client)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")

    reason = "房产证照片模糊无法辨认产权人信息，请在自然光下重新拍摄"
    reject = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/reject",
        json={"reason": reason}, headers=csrf)
    assert reject.status_code == 200, reject.text

    approve = await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/approve", headers=csrf)
    assert approve.status_code == 200, approve.text
    assert approve.json()["data"]["status"] == "VERIFIED"
    assert approve.json()["data"]["rejectReason"] == ""

    status = (await client.get(f"{C_BASE}/auth/status",
                               headers=bearer(result["token"]))).json()["data"]
    assert status["status"] == "VERIFIED_OWNER"
    assert status["ownerVerified"] is True


@pytest.mark.asyncio
async def test_admin_manual_certification_for_unverified_resident(client, db_session):
    """未提交住户认证的住户，可由后台在「住户认证」页直接人工认证。"""
    account = await register_user(client)
    await client.post(
        f"{C_BASE}/auth/register/complete",
        json={"nickname": "邻居丙", "intentCommunityId": 1},
        headers=bearer(account["token"]),
    )
    csrf = await admin_login(client)

    candidates = (await client.get(
        f"{ADMIN_BASE}/certifications/candidates",
        params={"type": "OWNER_PROOF", "communityId": 1}, headers=csrf,
    )).json()["data"]
    target = next(item for item in candidates
                  if item["userId"] == account["profile"]["id"])
    assert target["eligible"] is True
    assert target["certificationStatus"] == "UNVERIFIED"

    resp = await client.post(
        f"{ADMIN_BASE}/residents/{target['id']}/certifications/OWNER_PROOF/verify",
        json={"identity": "owner", "note": "已线下核验房产证及身份证原件"},
        headers=csrf)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "VERIFIED"
    assert data["type"] == "OWNER_PROOF"
    assert data["community"]["id"] == "1"

    status = (await client.get(f"{C_BASE}/auth/status",
                               headers=bearer(account["token"]))).json()["data"]
    assert status["status"] == "VERIFIED_OWNER"
    assert status["ownerVerified"] is True

    resident = await db_session.get(Resident, int(target["id"]))
    await db_session.refresh(resident)
    assert resident.certification_status == "VERIFIED"
    assert resident.certification_no.startswith("YZ")
    assert resident.identity_type == "业主"

    # 已认证住户不再出现在人工认证候选列表
    again = (await client.get(
        f"{ADMIN_BASE}/certifications/candidates",
        params={"type": "OWNER_PROOF", "communityId": 1}, headers=csrf,
    )).json()["data"]
    assert all(item["id"] != target["id"] for item in again)

    audit = await db_session.scalar(select(AuditLog).where(
        AuditLog.action == "certification.owner_proof.manual-verify"))
    assert audit is not None
    assert audit.after_snapshot["note"] == "已线下核验房产证及身份证原件"


@pytest.mark.asyncio
async def test_admin_manual_certification_reuses_rejected_cert(client, db_session):
    """人工认证复用最近一张驳回审核单，不重复生成审核记录。"""
    account = await register_user(client)
    await client.post(
        f"{C_BASE}/auth/register/complete",
        json={"nickname": "邻居戊", "intentCommunityId": 1},
        headers=bearer(account["token"]),
    )
    await submit_owner_proof(client, account["token"], community_id=1)
    csrf = await admin_login(client)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    await client.post(
        f"{ADMIN_BASE}/certifications/{proof['id']}/reject",
        json={"reason": "证明材料与申请人信息不一致，请补充产权证明"}, headers=csrf)

    resident = await db_session.scalar(select(Resident).where(
        Resident.user_id == int(account["profile"]["id"])))
    resp = await client.post(
        f"{ADMIN_BASE}/residents/{resident.id}/certifications/OWNER_PROOF/verify",
        json={"note": "线下复核产权证明后通过"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["id"] == proof["id"]
    assert resp.json()["data"]["status"] == "VERIFIED"

    await db_session.refresh(resident)
    assert resident.certification_status == "VERIFIED"


@pytest.mark.asyncio
async def test_admin_manual_realname_verification(client):
    """身份认证（实名）同样支持后台人工认证。"""
    account = await register_user(client)
    await client.post(
        f"{C_BASE}/auth/register/complete",
        json={"nickname": "邻居丁", "intentCommunityId": 1},
        headers=bearer(account["token"]),
    )
    csrf = await admin_login(client)

    candidates = (await client.get(
        f"{ADMIN_BASE}/certifications/candidates",
        params={"type": "REALNAME", "communityId": 1}, headers=csrf,
    )).json()["data"]
    target = next(item for item in candidates
                  if item["userId"] == account["profile"]["id"])

    resp = await client.post(
        f"{ADMIN_BASE}/residents/{target['id']}/certifications/REALNAME/verify",
        json={"note": "线下核验身份证原件"}, headers=csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["type"] == "REALNAME"

    status = (await client.get(f"{C_BASE}/auth/status",
                               headers=bearer(account["token"]))).json()["data"]
    assert status["realnameVerified"] is True
    assert status["ownerVerified"] is False


@pytest.mark.asyncio
async def test_certification_material_streamed_through_api(client, monkeypatch):
    """审核页材料由后端同源返回，不依赖浏览器能访问 MinIO 主机。

    回归：签名 URL 以 MINIO_ENDPOINT（如 127.0.0.1:5206）为主机，
    审核人从外网访问后台时图片必然加载失败。
    """
    result = await register_user(client)
    await submit_owner_proof(client, result["token"], community_id=1)
    csrf = await admin_login(client)
    proof = await first_pending_cert(client, csrf, "OWNER_PROOF")
    # 列表页“N 份”不再恒为 0
    assert proof["materialsCount"] == 2

    detail = (await client.get(
        f"{ADMIN_BASE}/certifications/{proof['id']}")).json()["data"]
    assert len(detail["materials"]) == 2
    assert detail["materials"][0]["url"] == (
        f"/api/v1/admin/certifications/{proof['id']}/materials/0")

    payload = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    monkeypatch.setattr(
        "src.api.admin.residents.get_minio", lambda: _FakeMinio(payload))
    resp = await client.get(detail["materials"][0]["url"])
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content == payload

    # 越界索引返回 404，不泄漏其它对象
    resp = await client.get(
        f"{ADMIN_BASE}/certifications/{proof['id']}/materials/9")
    assert resp.status_code == 404
