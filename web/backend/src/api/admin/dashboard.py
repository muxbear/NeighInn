from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from datetime import time as dtime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import and_, case, func, or_, select

from src.api.utils import epoch_ms
from src.core.config import settings
from src.core.deps import CurrentAdmin, DbSession
from src.core.permissions import (
    allowed_community_ids,
    assert_community_allowed,
    community_scope_conditions,
    get_permission_codes,
)
from src.core.responses import ERR_NOT_FOUND, ApiError, not_implemented, ok
from src.db.models import (
    Broadcast,
    Certification,
    Community,
    Dispute,
    HelpRequest,
    Item,
    ItemComment,
    LifeComment,
    LifePost,
    Notice,
    Order,
    Report,
    Resident,
    User,
    Withdrawal,
)
from src.db.models.common import utcnow
from src.domain import enums as E

router = APIRouter(tags=["admin:dashboard"])


# ---------------------------------------------------------------- 业务时区
# 数据库统一存 naive UTC；「今日」「近 N 日」必须按运营所在时区切分自然日，
# 否则 UTC 日界会让中国区用户在 00:00-08:00 看到错误的“今日新增”。

def _business_tz() -> tzinfo:
    try:
        return ZoneInfo(settings.business_timezone)
    except Exception:  # noqa: BLE001 - 配置错误时退化为 UTC+8，保证看板可用
        return timezone(timedelta(hours=8))


def _local_today() -> date:
    return datetime.now(_business_tz()).date()


def _utc_day_start(day: date) -> datetime:
    start = datetime.combine(day, dtime.min, tzinfo=_business_tz())
    return start.astimezone(UTC).replace(tzinfo=None)


def _day_buckets(days: int) -> list[tuple[str, datetime, datetime]]:
    today = _local_today()
    buckets = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        buckets.append((day.strftime("%m/%d"), _utc_day_start(day),
                        _utc_day_start(day + timedelta(days=1))))
    return buckets


async def _daily_counts(
    db: DbSession,
    model,
    ts_column,
    buckets: list[tuple[str, datetime, datetime]],
    *,
    conditions: list = (),
    joins: list = (),
) -> list[int]:
    """一次查询完成 N 个自然日的条件计数，避免逐日往返数据库。"""
    sums = [
        func.sum(case((and_(ts_column >= start, ts_column < end), 1), else_=0))
        for _, start, end in buckets
    ]
    stmt = select(*sums).select_from(model)
    for target, onclause in joins:
        stmt = stmt.join(target, onclause)
    stmt = stmt.where(
        ts_column >= buckets[0][1], ts_column < buckets[-1][2], *conditions,
    )
    row = (await db.execute(stmt)).one()
    return [int(value or 0) for value in row]


# ---------------------------------------------------------------- 公共查询

async def _resolve_community(db: DbSession, admin: CurrentAdmin,
                             community_id: int | None) -> Community | None:
    if not community_id:
        return None
    await assert_community_allowed(db, admin, community_id)
    community = await db.get(Community, community_id)
    if community is None:
        raise ApiError(ERR_NOT_FOUND, "社区不存在", 404)
    return community


async def _count(db: DbSession, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return int((await db.scalar(stmt)) or 0)


def _scoped(model, community_id: int | None) -> list:
    """按社区收敛聚合口径；未选择社区时统计全平台。"""
    return [model.community_id == community_id] if community_id else []


# ---------------------------------------------------------------- 工作台

@router.get("/dashboard/summary")
async def summary(admin: CurrentAdmin, db: DbSession,
                  communityId: int | None = Query(default=None)):
    """工作台汇总：全部来自真实聚合（禁止硬编码）。"""
    community = await _resolve_community(db, admin, communityId)
    cid = int(community.id) if community else None
    today_start = _utc_day_start(_local_today())
    active_since = _utc_day_start(_local_today() - timedelta(days=6))

    platform_users = await _count(db, User)
    if cid:
        users = await _count(db, Resident, Resident.community_id == cid,
                             Resident.status != "LEFT")
        today_new = await _count(
            db, Resident, Resident.community_id == cid,
            Resident.status != "LEFT", Resident.created_at >= today_start,
        )
        active_stmt = select(func.count(func.distinct(User.id))).select_from(User).where(
            User.id.in_(select(Resident.user_id).where(
                Resident.community_id == cid, Resident.user_id.is_not(None))),
            User.last_active_at >= active_since,
        )
    else:
        users = platform_users
        today_new = await _count(db, User, User.registered_at >= today_start)
        active_stmt = select(func.count()).select_from(User).where(
            User.last_active_at >= active_since)
    active_users = int((await db.scalar(active_stmt)) or 0)

    item_filters = _scoped(Item, cid)
    order_filters = _scoped(Order, cid)
    life_filters = _scoped(LifePost, cid)

    items_on_sale = await _count(db, Item, Item.status == E.ItemStatus.ON_SALE, *item_filters)
    pending_items = await _count(
        db, Item, Item.status == E.ItemStatus.PENDING_REVIEW, *item_filters)
    pending_life = await _count(
        db, LifePost, LifePost.status == "PENDING_REVIEW", *life_filters)
    orders_completed = await _count(
        db, Order, Order.status == E.OrderStatus.COMPLETED, *order_filters)
    gmv = int((await db.scalar(
        select(func.coalesce(func.sum(Order.amount_cents), 0)).where(
            Order.trade_type == E.TradeType.MONETARY,
            Order.status == E.OrderStatus.COMPLETED, *order_filters))) or 0)
    gift_count = await _count(
        db, Order, Order.trade_type == E.TradeType.FREE_GIFT,
        Order.status == E.OrderStatus.COMPLETED, *order_filters)
    barter_count = await _count(
        db, Order, Order.trade_type == E.TradeType.BARTER,
        Order.status == E.OrderStatus.COMPLETED, *order_filters)

    identity_stmt = select(Resident.identity_type, func.count()).where(
        Resident.certification_status == "VERIFIED")
    if cid:
        identity_stmt = identity_stmt.where(Resident.community_id == cid)
    identity_counts = {
        str(row[0]): int(row[1])
        for row in (await db.execute(identity_stmt.group_by(Resident.identity_type))).all()
    }
    owner = identity_counts.get("业主", 0)
    tenant = identity_counts.get("租户", 0)
    family = identity_counts.get("家属", 0)
    business = identity_counts.get("商务人员", 0)
    staff = identity_counts.get("教职工", 0)
    student = identity_counts.get("学生", 0)

    todos = await _todos(db, admin, cid)

    return ok({
        "community": {"id": str(community.id), "name": community.name} if community else None,
        "scope": "COMMUNITY" if community else "PLATFORM",
        "generatedAt": epoch_ms(utcnow()),
        "metrics": {
            "users": users,
            "platformUsers": platform_users,
            "todayNewUsers": today_new,
            "activeUsers": active_users,
            "activeRate": round(active_users * 100 / users, 1) if users else 0.0,
            "itemsOnSale": items_on_sale,
            "pendingReviews": pending_items + pending_life,
            "ordersCompleted": orders_completed,
            # GMV 仅货币担保支付实际成交口径；赠与/互换单独计件（SRS 9.2/W08-01）
            "gmvCents": gmv,
            "giftCompleted": gift_count,
            "barterCompleted": barter_count,
        },
        "distribution": {
            "owner": owner, "tenant": tenant, "family": family, "business": business,
            "staff": staff, "student": student,
            "total": owner + tenant + family + business + staff + student,
        },
        "todos": todos,
    })


async def _todos(db: DbSession, admin: CurrentAdmin,
                 community_id: int | None = None) -> list[dict]:
    """待办是业务表的实时投影（认证单等），不做单独待办表。

    每个待办带 permission，铃铛与工作台只展示当前管理员有权处理的项。
    """
    cert_filters = [Certification.status == "PENDING"]
    if community_id:
        # 实名认证是平台级审核（无 community_id），在任一社区工作台都必须可见，
        # 否则默认进入某个社区后永远看不到实名待办。
        cert_filters.append(or_(
            Certification.community_id == community_id,
            Certification.community_id.is_(None),
        ))
    cert_rows = list((await db.execute(
        select(Certification.type, func.count(), func.min(Certification.submitted_at))
        .where(*cert_filters)
        .group_by(Certification.type)
    )).all())
    cert_breakdown = {row[0]: int(row[1]) for row in cert_rows}
    pending_certs = sum(cert_breakdown.values())
    oldest_cert_at = min((row[2] for row in cert_rows if row[2]), default=None)
    latest_cert_id = await db.scalar(
        select(Certification.id).where(*cert_filters)
        .order_by(Certification.submitted_at.desc(), Certification.id.desc()).limit(1))

    item_filters = [Item.status == E.ItemStatus.PENDING_REVIEW]
    life_filters = [LifePost.status == "PENDING_REVIEW"]
    report_filters = [Report.status == "OPEN"]
    dispute_filters = [Dispute.status.in_(
        [E.DisputeStatus.OPEN, E.DisputeStatus.MEDIATING])]
    help_filters = [HelpRequest.status == E.HelpStatus.OPEN]
    service_filters = [HelpRequest.kind == "OFFER",
                       HelpRequest.status == E.HelpStatus.PENDING_REVIEW]
    withdrawal_filters = [Withdrawal.status == E.WithdrawalStatus.PENDING]

    if community_id:
        item_filters.append(Item.community_id == community_id)
        life_filters.append(LifePost.community_id == community_id)
        report_filters.append(Report.community_id == community_id)
        dispute_filters.append(Dispute.community_id == community_id)
        help_filters.append(HelpRequest.community_id == community_id)
        service_filters.append(HelpRequest.community_id == community_id)
        withdrawal_filters.append(Withdrawal.user_id.in_(select(Resident.user_id).where(
            Resident.community_id == community_id, Resident.user_id.is_not(None))))

    pending_items = await _count(db, Item, *item_filters)
    pending_life = await _count(db, LifePost, *life_filters)
    open_reports = await _count(db, Report, *report_filters)
    open_disputes = await _count(db, Dispute, *dispute_filters)
    pending_withdrawals = await _count(db, Withdrawal, *withdrawal_filters)
    open_help = await _count(db, HelpRequest, *help_filters)
    pending_help_services = await _count(db, HelpRequest, *service_filters)
    pending_help_service_community = await db.scalar(
        select(HelpRequest.community_id)
        .where(*service_filters)
        .order_by(HelpRequest.id.desc()).limit(1))
    # 移动端「申请添加小区」：社区档案 PENDING 即待审批（数据范围内计数）。
    app_allowed = await allowed_community_ids(db, admin)
    app_filters = [Community.status == "PENDING",
                   *community_scope_conditions(app_allowed, Community.id)]
    pending_community_apps = await _count(db, Community, *app_filters)
    oldest_app_at = await db.scalar(
        select(func.min(Community.updated_at)).where(*app_filters))

    cert_desc = (
        f"实名 {cert_breakdown.get('REALNAME', 0)} 项 · "
        f"住户认证 {cert_breakdown.get('OWNER_PROOF', 0)} 项"
        if pending_certs else "暂无待审核认证"
    )
    todos = [
        {"key": "community_application", "icon": "MapPin", "color": "green",
         "title": "小区添加待审批", "description": "移动端提交的小区添加申请",
         "count": pending_community_apps,
         "route": "/community-management/maintenance?status=PENDING",
         "permission": "community:maintenance:view",
         "oldestPendingAt": epoch_ms(oldest_app_at)},
        {"key": "certification", "icon": "ClipboardCheck", "color": "blue",
         "title": "住户认证待审核", "description": cert_desc,
         "count": pending_certs, "route": "/governance/verification",
         "permission": "community:resident:audit",
         "breakdown": cert_breakdown,
         "latestCertId": str(latest_cert_id) if latest_cert_id else "",
         "oldestPendingAt": epoch_ms(oldest_cert_at)},
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
        {"key": "help_service", "icon": "ShieldCheck", "color": "green",
         "title": "邻里服务待审核", "description": "移动端发布的邻里服务待处理",
         "count": pending_help_services,
         "route": (
             f"/community-operations/help?kind=OFFER&tab=PENDING_REVIEW"
             f"&communityId={int(pending_help_service_community)}"
             if pending_help_service_community else
             "/community-operations/help?kind=OFFER&tab=PENDING_REVIEW"
         ),
         "communityId": (int(pending_help_service_community)
                         if pending_help_service_community else None),
         "permission": "community:help:review", "oldestPendingAt": 0},
    ]
    codes = set(await get_permission_codes(db, admin))
    return [todo for todo in todos if todo["permission"] in codes]


@router.get("/dashboard/trend")
async def trend(admin: CurrentAdmin, db: DbSession,
                days: int = Query(default=7, ge=1, le=30),
                communityId: int | None = Query(default=None)):
    """近 N 日真实趋势：新增注册、内容创建（物品/生活/喇叭）、内容互动（留言）。"""
    community = await _resolve_community(db, admin, communityId)
    cid = int(community.id) if community else None
    buckets = _day_buckets(days)

    if cid:
        new_users = await _daily_counts(
            db, Resident, Resident.created_at, buckets,
            conditions=[Resident.community_id == cid, Resident.status != "LEFT"])
    else:
        new_users = await _daily_counts(db, User, User.registered_at, buckets)

    items = await _daily_counts(
        db, Item, Item.created_at, buckets, conditions=_scoped(Item, cid))
    life_posts = await _daily_counts(
        db, LifePost, LifePost.created_at, buckets, conditions=_scoped(LifePost, cid))
    broadcasts = await _daily_counts(
        db, Broadcast, Broadcast.created_at, buckets, conditions=_scoped(Broadcast, cid))
    content_published = [a + b + c for a, b, c in zip(items, life_posts, broadcasts, strict=True)]

    life_comments = await _daily_counts(
        db, LifeComment, LifeComment.created_at, buckets,
        conditions=_scoped(LifePost, cid),
        joins=[(LifePost, LifePost.id == LifeComment.post_id)])
    item_comments = await _daily_counts(
        db, ItemComment, ItemComment.created_at, buckets,
        conditions=_scoped(Item, cid),
        joins=[(Item, Item.id == ItemComment.item_id)])
    interactions = [a + b for a, b in zip(life_comments, item_comments, strict=True)]

    return ok({
        "scope": "COMMUNITY" if community else "PLATFORM",
        "days": days,
        "labels": [label for label, _, _ in buckets],
        "newUsers": new_users,
        "contentPublished": content_published,
        "interactions": interactions,
    })


@router.get("/dashboard/todos")
async def todos(admin: CurrentAdmin, db: DbSession,
                communityId: int | None = Query(default=None)):
    community = await _resolve_community(db, admin, communityId)
    return ok(await _todos(db, admin, int(community.id) if community else None))


def _event(kind: str, row_id, actor: str | None, action: str, target: str | None,
           ts: datetime | None, tone: str) -> dict:
    actor_name = (actor or "").strip() or "邻居"
    return {
        "id": f"{kind}:{row_id}",
        "kind": kind,
        "actor": actor_name,
        "action": action,
        "target": target or "",
        "time": epoch_ms(ts),
        "tone": tone,
        "_sortAt": ts or datetime.min,
    }


@router.get("/dashboard/activities")
async def activities(admin: CurrentAdmin, db: DbSession,
                     limit: int = Query(default=6, ge=1, le=20),
                     communityId: int | None = Query(default=None)):
    """最新动态：社区真实业务事件（认证/发布/交易/求助/公告/报修/反馈）。

    此前该接口只读取管理端审计日志，展示的是管理员操作，与“社区内刚刚发生的
    事情”语义不符；现改为跨业务表聚合移动端产生的真实事件。
    """
    community = await _resolve_community(db, admin, communityId)
    cid = int(community.id) if community else None
    events: list[dict] = []

    cert_stmt = select(
        Certification.id, Certification.type, Certification.submitted_at,
        User.nickname,
    ).join(User, User.id == Certification.user_id, isouter=True)
    if cid:
        cert_stmt = cert_stmt.where(Certification.community_id == cid)
    for row in (await db.execute(
            cert_stmt.order_by(Certification.submitted_at.desc()).limit(limit))).all():
        action = "提交了实名认证" if row[1] == "REALNAME" else "提交了住户认证"
        events.append(_event("certification", row[0], row[3], action, "", row[2], "violet"))

    item_stmt = select(Item.id, Item.title, Item.created_at, User.nickname).join(
        User, User.id == Item.seller_id, isouter=True).where(Item.status != E.ItemStatus.DRAFT)
    if cid:
        item_stmt = item_stmt.where(Item.community_id == cid)
    for row in (await db.execute(
            item_stmt.order_by(Item.created_at.desc()).limit(limit))).all():
        events.append(_event("item", row[0], row[3], "发布了闲置物品", row[1], row[2], "mint"))

    life_stmt = select(LifePost.id, LifePost.title, LifePost.created_at, User.nickname).join(
        User, User.id == LifePost.author_id, isouter=True)
    if cid:
        life_stmt = life_stmt.where(LifePost.community_id == cid)
    for row in (await db.execute(
            life_stmt.order_by(LifePost.created_at.desc()).limit(limit))).all():
        events.append(_event("life", row[0], row[3], "发布了生活动态", row[1], row[2], "peach"))

    # 喇叭由后台管理员发布，author_id 属于 admin_users 命名空间，不能与 users 关联。
    broadcast_stmt = select(Broadcast.id, Broadcast.title, Broadcast.created_at)
    if cid:
        broadcast_stmt = broadcast_stmt.where(Broadcast.community_id == cid)
    for row in (await db.execute(
            broadcast_stmt.order_by(Broadcast.created_at.desc()).limit(limit))).all():
        events.append(_event("broadcast", row[0], "运营中心",
                             "发布了社区喇叭", row[1], row[2], "blue"))

    help_stmt = select(
        HelpRequest.id, HelpRequest.title, HelpRequest.kind,
        HelpRequest.created_at, User.nickname,
    ).join(User, User.id == HelpRequest.requester_id, isouter=True)
    if cid:
        help_stmt = help_stmt.where(HelpRequest.community_id == cid)
    for row in (await db.execute(
            help_stmt.order_by(HelpRequest.created_at.desc()).limit(limit))).all():
        action = "发起了邻里求助" if row[2] == "HELP" else "发布了邻里服务"
        events.append(_event("help", row[0], row[4], action, row[1], row[3], "mint"))

    order_ts = func.coalesce(Order.completed_at, Order.updated_at)
    order_stmt = select(
        Order.id, Order.order_no, order_ts, User.nickname,
    ).join(User, User.id == Order.buyer_id, isouter=True).where(
        Order.status == E.OrderStatus.COMPLETED)
    if cid:
        order_stmt = order_stmt.where(Order.community_id == cid)
    for row in (await db.execute(
            order_stmt.order_by(order_ts.desc()).limit(limit))).all():
        events.append(_event("order", row[0], row[3], "完成了交易", row[1], row[2], "violet"))

    notice_ts = func.coalesce(Notice.published_at, Notice.created_at)
    notice_stmt = select(Notice.id, Notice.title, notice_ts).where(
        Notice.status == "PUBLISHED")
    if cid:
        notice_stmt = notice_stmt.where(
            or_(Notice.community_id == cid, Notice.community_id.is_(None)))
    for row in (await db.execute(
            notice_stmt.order_by(notice_ts.desc()).limit(limit))).all():
        events.append(_event("notice", row[0], "运营中心", "发布了社区公告",
                             row[1], row[2], "blue"))

    events.sort(key=lambda item: item["_sortAt"], reverse=True)
    result = events[:limit]
    for item in result:
        item.pop("_sortAt", None)
    return ok(result)


@router.post("/dashboard/brief")
async def generate_brief(admin: CurrentAdmin, db: DbSession):
    raise not_implemented("POST /dashboard/brief（运营简报生成，Phase 3 导出中心）")
