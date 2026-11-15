from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from src.api.utils import paginate
from src.core.audit import write_audit
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import require_permission
from src.core.responses import ERR_NOT_FOUND, ERR_PARAM, ApiError, ok, paginated
from src.core.security import decrypt_field, mask_phone
from src.db.models import ExportJob, Item, Order, PaymentTransaction, User
from src.db.models.common import utcnow

router = APIRouter(tags=["admin:exports"])

ExportPerm = Depends(require_permission("reporting:export:create"))
ViewPerm = Depends(require_permission("reporting:export:view"))

EXPORT_DIR = Path(tempfile.gettempdir()) / "neighinn-exports"


class ExportIn(BaseModel):
    type: str  # USERS / ORDERS / TRANSACTIONS / AUDIT_LOGS / ITEMS
    communityId: int | None = None


EXPORT_TYPES = ("USERS", "ORDERS", "TRANSACTIONS", "AUDIT_LOGS", "ITEMS")


@router.post("/exports", dependencies=[ExportPerm])
async def create_export(payload: ExportIn, request: Request,
                        admin: CurrentAdmin, db: DbSession):
    """新建导出任务（W08-03）：默认脱敏；同步生成（开发规模）；下载写审计。
    生产改造：投递 Worker 异步生成 → 私有桶存储（7 天过期），明文导出需双人审批。"""
    if payload.type not in EXPORT_TYPES:
        raise ApiError(ERR_PARAM, f"导出类型不合法（{'/'.join(EXPORT_TYPES)}）", 400)
    job = ExportJob(type=payload.type, params={"communityId": payload.communityId},
                    status="GENERATING", requested_by=admin.id)
    db.add(job)
    await db.flush()

    rows = await _generate_rows(db, payload.type, payload.communityId)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"export-{job.id}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        for row in rows:
            writer.writerow(row)
    job.status = "COMPLETED"
    job.completed_at = utcnow()
    await write_audit(db, request, actor=admin, action="export.create",
                      resource_type="export_job", resource_id=job.id,
                      before=None, after={"type": payload.type, "rows": len(rows)})
    await db.commit()
    return ok({"id": str(job.id), "status": job.status, "rows": len(rows) - 1},
              f"导出完成，共 {len(rows) - 1} 条")


async def _generate_rows(db: DbSession, export_type: str, community_id: int | None) -> list[list]:
    """默认脱敏（手机号打码、姓名保留）；资金流水不含渠道账号明文。"""
    if export_type == "USERS":
        stmt = select(User).order_by(User.id)
        rows = [["ID", "昵称", "手机号(脱敏)", "实名状态", "信用分", "注册时间"]]
        for user in (await db.execute(stmt)).scalars().all():
            rows.append([user.id, user.nickname, mask_phone(decrypt_field(user.phone_enc)),
                         user.realname_status, user.credit_score,
                         user.registered_at.strftime("%Y-%m-%d %H:%M") if user.registered_at else ""])
        return rows
    if export_type == "ORDERS":
        stmt = select(Order).order_by(Order.id)
        rows = [["订单号", "交易方式", "金额(元)", "状态", "托管状态", "创建时间"]]
        for order in (await db.execute(stmt)).scalars().all():
            rows.append([order.order_no, order.trade_type, order.amount_cents / 100,
                         order.status, order.escrow_status,
                         order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else ""])
        return rows
    if export_type == "TRANSACTIONS":
        stmt = select(PaymentTransaction).order_by(PaymentTransaction.id)
        rows = [["流水号", "类型", "金额(元)", "渠道", "状态", "对账状态", "时间"]]
        for txn in (await db.execute(stmt)).scalars().all():
            rows.append([txn.txn_no, txn.type, txn.amount_cents / 100, txn.channel,
                         txn.status, txn.recon_status,
                         txn.created_at.strftime("%Y-%m-%d %H:%M") if txn.created_at else ""])
        return rows
    if export_type == "AUDIT_LOGS":
        from src.db.models import AuditLog

        stmt = select(AuditLog).order_by(AuditLog.id)
        rows = [["ID", "操作人", "动作", "对象", "结果", "IP", "追踪号", "时间"]]
        for log in (await db.execute(stmt)).scalars().all():
            rows.append([log.id, log.actor_name, log.action,
                         f"{log.resource_type}/{log.resource_id}", log.result, log.ip,
                         log.trace_id,
                         log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else ""])
        return rows
    # ITEMS
    stmt = select(Item).order_by(Item.id)
    if community_id:
        stmt = stmt.where(Item.community_id == community_id)
    rows = [["ID", "标题", "交易方式", "价格(元)", "状态", "创建时间"]]
    for item in (await db.execute(stmt)).scalars().all():
        rows.append([item.id, item.title, item.trade_type, item.price_cents / 100,
                     item.status, item.created_at.strftime("%Y-%m-%d %H:%M") if item.created_at else ""])
    return rows


@router.get("/exports", dependencies=[ViewPerm])
async def list_exports(admin: CurrentAdmin, db: DbSession,
                       page: int = Query(default=1), pageSize: int = Query(default=20)):
    stmt = select(ExportJob).order_by(ExportJob.id.desc())
    rows, total = await paginate(db, stmt, page, pageSize)
    return paginated([{
        "id": str(row.id), "type": row.type, "params": row.params, "status": row.status,
        "createdAt": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
        "completedAt": int(row.completed_at.timestamp() * 1000) if row.completed_at else 0,
    } for row in rows], page, pageSize, total)


@router.get("/exports/{job_id}")
async def export_detail(job_id: int, admin: CurrentAdmin, db: DbSession):
    job = await db.get(ExportJob, job_id)
    if not job:
        raise ApiError(ERR_NOT_FOUND, "导出任务不存在", 404)
    return ok({"id": str(job.id), "type": job.type, "params": job.params,
               "status": job.status})


@router.get("/exports/{job_id}/download", dependencies=[ViewPerm])
async def download_export(job_id: int, request: Request,
                          admin: CurrentAdmin, db: DbSession):
    """下载写审计（W08-03）。"""
    job = await db.get(ExportJob, job_id)
    if not job:
        raise ApiError(ERR_NOT_FOUND, "导出任务不存在", 404)
    path = EXPORT_DIR / f"export-{job.id}.csv"
    if job.status != "COMPLETED" or not path.exists():
        raise ApiError(ERR_NOT_FOUND, "文件不存在或已过期", 404)
    await write_audit(db, request, actor=admin, action="export.download",
                      resource_type="export_job", resource_id=job.id,
                      before=None, after={"type": job.type})
    await db.commit()
    content = path.read_bytes()
    return StreamingResponse(
        io.BytesIO(content), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=export-{job.id}.csv"})
