from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.config import settings
from src.core.deps import CurrentUser, DbSession
from src.core.responses import (
    ERR_CONFLICT,
    ERR_DEPENDENCY,
    ERR_NOT_FOUND,
    ERR_PARAM,
    ERR_UNAUTHORIZED,
    ApiError,
    ok,
)
from src.core.security import decode_token, issue_access_token, issue_refresh_token, mask_phone
from src.db.models import Certification
from src.services import auth_service as svc
from src.services.auth_service import sms_code_store

router = APIRouter(tags=["c:auth"])
logger = logging.getLogger(__name__)


class SmsCodeIn(BaseModel):
    phone: str


class LoginSmsIn(BaseModel):
    phone: str
    code: str
    # login：仅登录，未注册手机号提示去注册；register：仅注册，已注册手机号提示去登录。
    intent: Literal["login", "register"] = "login"
    agreed: bool = False
    agreementVersion: str = ""
    privacyVersion: str = ""
    deviceId: str = ""


class RegisterCompleteIn(BaseModel):
    nickname: str | None = None
    avatarKey: str | None = None
    intentCommunityId: int | None = None
    skip: bool = False
    finish: bool = False


class RefreshIn(BaseModel):
    refreshToken: str


class RealnameIn(BaseModel):
    frontImage: str
    backImage: str
    faceToken: str = ""


class OwnerProofIn(BaseModel):
    communityId: int
    identity: str = "owner"  # owner / tenant / family（M01-03）
    images: list[str] = []


@router.post("/auth/sms-code")
async def send_sms_code(payload: SmsCodeIn):
    svc.validate_phone(payload.phone)
    if settings.app_env != "dev":
        # 真实短信通道尚未接入：显式报错，避免前端收到“发送成功”却永远收不到验证码。
        raise ApiError(ERR_DEPENDENCY, "短信通道尚未接入，暂无法发送验证码", 503)
    code, cooldown = await sms_code_store.issue(payload.phone)
    # 仅开发环境回显/记录验证码（NF-06：生产绝不返回或记录验证码本体）。
    logger.info("开发环境短信验证码 %s -> %s", mask_phone(payload.phone), code)
    return ok({"cooldown": cooldown, "mockCode": code}, "验证码已发送")


@router.post("/auth/login/sms")
async def login_by_sms(payload: LoginSmsIn, db: DbSession):
    """手机号验证码登录/注册（M01-01）。

    intent=login：仅登录，未注册手机号返回 40401，引导用户走注册页；
    intent=register：仅注册，已注册手机号返回 40901，引导用户去登录。
    注册即登录：注册成功后直接签发 token，移动端继续完善资料。
    """
    svc.validate_phone(payload.phone)
    if not await sms_code_store.verify(payload.phone, payload.code):
        raise ApiError(ERR_UNAUTHORIZED, "验证码错误或已过期", 401)

    existing = await svc.find_user_by_phone(db, payload.phone)

    if payload.intent == "register":
        if existing:
            if existing.status == "FROZEN":
                raise ApiError(ERR_UNAUTHORIZED, "账号不可用", 401)
            if existing.status == "CANCELLED":
                svc.assert_phone_can_register(existing)
            raise ApiError(ERR_CONFLICT, "该手机号已注册，请直接登录", 409)
        if not payload.agreed or not payload.agreementVersion or not payload.privacyVersion:
            raise ApiError(ERR_PARAM, "请先阅读并同意用户协议与隐私政策", 400)
        user, is_new = await svc.get_or_create_user_by_phone(db, payload.phone)
    else:
        if not existing:
            raise ApiError(ERR_NOT_FOUND, "该手机号尚未注册，请先注册", 404)
        if existing.status != "ACTIVE":
            raise ApiError(ERR_UNAUTHORIZED, "账号不可用", 401)
        user, is_new = existing, False

    if payload.agreed:
        svc.record_agreement(user, payload.agreementVersion, payload.privacyVersion)

    await db.commit()
    profile = await svc.serialize_profile(db, user)
    return ok({
        **svc.issue_token_pair(user),
        "profile": profile,
        "isNewUser": is_new,
        "onboardingStatus": user.onboarding_status or "COMPLETED",
    }, "注册成功" if is_new else "登录成功")


@router.post("/auth/register/complete")
async def complete_registration(
    payload: RegisterCompleteIn, user: CurrentUser, db: DbSession
):
    """新人引导：保存昵称/头像/意向小区，或跳过；finish=true 关闭成功引导页。"""
    profile = await svc.complete_registration(
        db,
        user,
        nickname=payload.nickname,
        avatar_key=payload.avatarKey,
        intent_community_id=payload.intentCommunityId,
        skip=payload.skip,
        finish=payload.finish,
    )
    message = "注册引导已完成" if payload.finish else "注册资料已保存"
    return ok(profile, message)


@router.post("/auth/login/one-click")
async def login_by_one_click(db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /auth/login/one-click（需运营商认证 SDK 联调）")


@router.post("/auth/login/wechat")
async def login_by_wechat(db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /auth/login/wechat（需微信开放平台联调）")


@router.post("/auth/token/refresh")
async def refresh_token(payload: RefreshIn, db: DbSession):
    user_id = decode_token(payload.refreshToken, expected_type="refresh")
    if not user_id:
        raise ApiError(ERR_UNAUTHORIZED, "Refresh Token 已失效", 401)
    from src.db.models import User

    user = await db.get(User, user_id)
    if not user or user.status != "ACTIVE":
        raise ApiError(ERR_UNAUTHORIZED, "账号不可用", 401)
    return ok({
        "accessToken": issue_access_token(user.id),
        "refreshToken": issue_refresh_token(user.id),
    })


@router.post("/auth/logout")
async def logout(user: CurrentUser, db: DbSession):
    # 无状态 JWT：客户端丢弃令牌即可；如需强制下线，接入 Redis 令牌黑名单。
    return ok({"success": True}, "已退出登录")


@router.get("/auth/status")
async def auth_status(user: CurrentUser, db: DbSession):
    return ok(await svc.compute_auth_status(db, user))


@router.post("/auth/realname")
async def submit_realname(payload: RealnameIn, user: CurrentUser, db: DbSession):
    """实名认证（M01-02）：身份证正反面 + 活体人脸。
    材料为上传后的对象键（私有桶）；生成审核单进入后台队列（W02-01）。"""
    if not payload.frontImage or not payload.backImage:
        raise ApiError(ERR_PARAM, "请上传身份证正反面照片", 400)
    await svc.assert_no_pending_certification(db, user.id, "REALNAME")
    cert = Certification(
        user_id=user.id,
        type="REALNAME",
        materials=[payload.frontImage, payload.backImage],
        auto_result={"faceToken": bool(payload.faceToken)},
        status="PENDING",
        trace_id=uuid.uuid4().hex[:16],
    )
    db.add(cert)
    await db.commit()
    return ok({"status": "PENDING", "message": "实名认证已提交，预计 24 小时内完成审核"})


@router.post("/auth/owner-proof")
async def submit_owner_proof(payload: OwnerProofIn, user: CurrentUser, db: DbSession):
    """业主证明（M01-03）：物业居住证明/房产证/租赁合同 + 小区选择。
    每次提交生成审核单进入后台审核队列（W02-02）。"""
    from src.db.models import Community

    if not payload.images:
        raise ApiError(ERR_PARAM, "请上传至少 1 份证明材料", 400)
    # SRS 4.1 流程顺序：实名认证 → 业主证明（服务端强校验）
    realname = await svc.latest_certification(db, user.id, "REALNAME")
    if not realname or realname.status != "VERIFIED":
        raise ApiError(40302, "请先完成实名认证后再提交业主证明", 403)
    community = await db.get(Community, payload.communityId)
    if not community or community.status != "OPERATING":
        raise ApiError(ERR_PARAM, "所选小区不存在或已停用", 400)
    await svc.assert_no_pending_certification(db, user.id, "OWNER_PROOF")
    cert = Certification(
        user_id=user.id,
        type="OWNER_PROOF",
        community_id=payload.communityId,
        identity=payload.identity,
        materials=payload.images[:5],
        status="PENDING",
        trace_id=uuid.uuid4().hex[:16],
    )
    db.add(cert)
    await db.commit()
    return ok({"status": "PENDING", "auditHours": 24})


@router.post("/auth/appeal")
async def submit_appeal(user: CurrentUser, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("POST /auth/appeal（M01-05 申诉通道，Phase 2）")


@router.delete("/auth/account")
async def cancel_account(user: CurrentUser, db: DbSession):
    from src.core.responses import not_implemented

    raise not_implemented("DELETE /auth/account（BR-10 注销匿名化，Phase 2）")
