from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.deps import CurrentUser, DbSession
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, ok
from src.db.models import Item, LifePost, Report, User
from src.services.auth_service import bound_resident

router = APIRouter(tags=["c:reports"])

TARGET_MODELS = {
    "ITEM": Item,
    "USER": User,
    "LIFE_POST": LifePost,
}


class ReportIn(BaseModel):
    targetType: str  # ITEM / USER / CONVERSATION / COMMENT / MESSAGE / LIFE_POST
    targetId: int
    reason: str
    detail: str = ""
    images: list[str] = []


@router.post("/reports")
async def submit_report(payload: ReportIn, user: CurrentUser, db: DbSession):
    """举报（M04-03 → W03-04/W05-03 处理工作台）。对象存在性校验后入队。"""
    if payload.targetType not in TARGET_MODELS and payload.targetType not in (
            "CONVERSATION", "COMMENT", "MESSAGE"):
        raise ApiError(ERR_PARAM, "举报对象类型不合法", 400)
    if len(payload.reason.strip()) < 2:
        raise ApiError(ERR_PARAM, "请填写举报原因", 400)

    model = TARGET_MODELS.get(payload.targetType)
    target = await db.get(model, payload.targetId) if model else None
    if model and not target:
        raise ApiError(ERR_NOT_FOUND, "举报对象不存在", 404)

    resident = await bound_resident(db, user.id)
    report = Report(
        community_id=resident.community_id if resident else None,
        reporter_id=user.id,
        target_type=payload.targetType,
        target_id=payload.targetId,
        reason=payload.reason.strip(),
        detail=payload.detail[:500],
        evidence=payload.images[:9],
        status="OPEN",
    )
    db.add(report)

    from src.core.audit import write_outbox

    await write_outbox(db, event_type="ReportSubmitted", aggregate_type="report",
                       aggregate_id=report.id,
                       payload={"targetType": payload.targetType,
                                "targetId": payload.targetId, "reason": report.reason})
    await db.commit()
    return ok({"success": True, "reportId": str(report.id)}, "举报已提交，平台将尽快处理")
