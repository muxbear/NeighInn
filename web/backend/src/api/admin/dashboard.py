from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import get_permission_codes
from src.core.responses import not_implemented, ok
from src.db.models import (
    AuditLog,
    Certification,
    Community,
    Dispute,
    HelpRequest,
    Item,
    LifePost,
    Order,
    Report,
    Resident,
    User,
    Withdrawal,
)
from src.db.models.common import utcnow
from src.domain import enums as E

router = APIRouter(tags=["admin:dashboard"])


@router.get("/dashboard/summary")
async def summary(admin: CurrentAdmin, db: DbSession,
                  communityId: int | None = Query(default=None)):
    """工作台汇总：全部来自真实聚合（禁止硬编码）。"""
    users_total = int((await db.scalar(select(func.count()).select_from(User))) or 0)
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_new = int((await db.scalar(
        select(func.count()).select_from(User)
        .where(User.registered_at >= today_start))) or 0)
    items_on_sale = int((await db.scalar(
        select(func.count()).select_from(Item).where(Item.status == E.ItemStatus.ON_SALE))) or 0)
    orders_completed = int((await db.scalar(
        select(func.count()).select_from(Order).where(
            Order.status == E.OrderStatus.COMPLETED))) or 0)
    gmv = int((await db.scalar(
        select(func.coalesce(func.sum(Order.amount_cents), 0)).where(
            Order.trade_type == E.TradeType.MONETARY,
            Order.status == E.OrderStatus.COMPLETED))) or 0)
    gift_count = int((await db.scalar(
        select(func.count()).select_from(Order).where(
            Order.trade_type == E.TradeType.FREE_GIFT,
            Order.status == E.OrderStatus.COMPLETED))) or 0)
    barter_count = int((await db.scalar(
        select(func.count()).select_from(Order).where(
            Order.trade_type == E.TradeType.BARTER,
            Order.status == E.OrderStatus.COMPLETED))) or 0)

    owner_count = int((await db.scalar(
        select(func.count()).select_from(Resident).where(
            Resident.identity_type == "业主",
            Resident.certification_status == "VERIFIED"))) or 0)
    tenant_count = int((await db.scalar(
        select(func.count()).select_from(Resident).where(
            Resident.identity_type == "租户",
            Resident.certification_status == "VERIFIED"))) or 0)
    family_count = int((await db.scalar(
        select(func.count()).select_from(Resident).where(
            Resident.identity_type == "家属",
            Resident.certification_status == "VERIFIED"))) or 0)

    community = await db.get(Community, communityId) if communityId else None
    return ok({
        "community": {"id": str(community.id), "name": community.name} if community else None,
        "metrics": {
            "users": users_total,
            "todayNewUsers": today_new,
            "itemsOnSale": items_on_sale,
            "ordersCompleted": orders_completed,
            # GMV 仅货币担保支付实际成交口径；赠与/互换单独计件（SRS 9.2/W08-01）
            "gmvCents": gmv,
            "giftCompleted": gift_count,
            "barterCompleted": barter_count,
        },
        "distribution": {
            "owner": owner_count, "tenant": tenant_count, "family": family_count,
            "total": owner_count + tenant_count + family_count,
        },
        "todos": await _todos(db, admin),
    })


async def _todos(db: DbSession, admin: CurrentAdmin) -> list[dict]:
    """待办是业务表的实时投影（认证单等），不做单独待办表。

    每个待办带 permission，铃铛与工作台只展示当前管理员有权处理的项。
    """
    cert_rows = list((await db.execute(
        select(Certification.type, func.count(), func.min(Certification.submitted_at))
        .where(Certification.status == "PENDING")
        .group_by(Certification.type)
    )).all())
    cert_breakdown = {row[0]: int(row[1]) for row in cert_rows}
    pending_certs = sum(cert_breakdown.values())
    oldest_cert_at = min((row[2] for row in cert_rows if row[2]), default=None)
    latest_cert_id = await db.scalar(
        select(Certification.id).where(Certification.status == "PENDING")
        .order_by(Certification.submitted_at.desc(), Certification.id.desc()).limit(1))

    pending_items = int((await db.scalar(
        select(func.count()).select_from(Item).where(
            Item.status == E.ItemStatus.PENDING_REVIEW))) or 0)
    pending_life = int((await db.scalar(
        select(func.count()).select_from(LifePost).where(
            LifePost.status == "PENDING_REVIEW"))) or 0)
    open_reports = int((await db.scalar(
        select(func.count()).select_from(Report).where(Report.status == "OPEN"))) or 0)
    open_disputes = int((await db.scalar(
        select(func.count()).select_from(Dispute).where(
            Dispute.status.in_([E.DisputeStatus.OPEN, E.DisputeStatus.MEDIATING])))) or 0)
    pending_withdrawals = int((await db.scalar(
        select(func.count()).select_from(Withdrawal).where(
            Withdrawal.status == E.WithdrawalStatus.PENDING))) or 0)
    open_help = int((await db.scalar(
        select(func.count()).select_from(HelpRequest).where(
            HelpRequest.status == E.HelpStatus.OPEN))) or 0)

    cert_desc = (
        f"实名 {cert_breakdown.get('REALNAME', 0)} 项 · "
        f"住户认证 {cert_breakdown.get('OWNER_PROOF', 0)} 项"
        if pending_certs else "暂无待审核认证"
    )
    todos = [
        {"key": "certification", "icon": "ClipboardCheck", "color": "blue",
         "title": "住户认证待审核", "description": cert_desc,
         "count": pending_certs, "route": "/governance/verification",
         "permission": "community:resident:audit",
         "breakdown": cert_breakdown,
         "latestCertId": str(latest_cert_id) if latest_cert_id else "",
         "oldestPendingAt": int(oldest_cert_at.timestamp() * 1000) if oldest_cert_at else 0},
        {"key": "item", "icon": "ShoppingBag", "color": "orange", "title": "商品待审核",
         "description": "AI 质检后待人工复核", "count": pending_items,
         "route": "/community-operations/items", "permission": "community:item:review",
         "oldestPendingAt": 0},
        {"key": "life", "icon": "Coffee", "color": "violet", "title": "生活内容待审核",
         "description": "社区生活内容待复核", "count": pending_life,
         "route": "/community-operations/life?tab=PENDING_REVIEW",
         "permission": "community:life:review",
         "oldestPendingAt": 0},
        {"key": "report", "icon": "Flag", "color": "red", "title": "举报待处理",
         "description": "邻里举报待核实", "count": open_reports,
         "route": "/governance/reports", "permission": "governance:report:handle",
         "oldestPendingAt": 0},
        {"key": "dispute", "icon": "Gavel", "color": "orange", "title": "纠纷待调解",
         "description": "交易纠纷待介入", "count": open_disputes,
         "route": "/governance/disputes", "permission": "governance:dispute:mediate",
         "oldestPendingAt": 0},
        {"key": "withdrawal", "icon": "Banknote", "color": "green", "title": "提现待审核",
         "description": "业主提现申请待复核", "count": pending_withdrawals,
         "route": "/finance/withdrawals", "permission": "finance:withdrawal:review",
         "oldestPendingAt": 0},
        {"key": "help", "icon": "HandHeart", "color": "blue", "title": "互助待响应",
         "description": "邻里互助待撮合", "count": open_help,
         "route": "/community-operations/help", "permission": "community:help:match",
         "oldestPendingAt": 0},
    ]
    codes = set(await get_permission_codes(db, admin))
    return [todo for todo in todos if todo["permission"] in codes]


@router.get("/dashboard/trend")
async def trend(admin: CurrentAdmin, db: DbSession, days: int = Query(default=7)):
    """近 N 日注册与发布趋势（真实聚合）。"""
    labels, active, published = [], [], []
    for offset in range(days - 1, -1, -1):
        day = utcnow() - timedelta(days=offset)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        labels.append(day_start.strftime("%m/%d"))
        active.append(int((await db.scalar(
            select(func.count()).select_from(User).where(
                User.registered_at >= day_start, User.registered_at < day_end))) or 0))
        published.append(int((await db.scalar(
            select(func.count()).select_from(Item).where(
                Item.created_at >= day_start, Item.created_at < day_end))) or 0))
    return ok({"labels": labels, "active": active, "published": published})


@router.get("/dashboard/todos")
async def todos(admin: CurrentAdmin, db: DbSession):
    return ok(await _todos(db, admin))


@router.get("/dashboard/activities")
async def activities(admin: CurrentAdmin, db: DbSession, limit: int = Query(default=10)):
    """最新动态：来自真实审计与业务事件。"""
    rows = list((await db.execute(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars().all())
    return ok([{
        "id": str(row.id), "actor": row.actor_name, "action": row.action,
        "target": f"{row.resource_type} #{row.resource_id}" if row.resource_type else "",
        "time": int(row.created_at.timestamp() * 1000) if row.created_at else 0,
    } for row in rows])


@router.post("/dashboard/brief")
async def generate_brief(admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /dashboard/brief（运营简报生成，Phase 3 导出中心）")
