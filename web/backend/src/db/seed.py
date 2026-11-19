"""平台种子数据（幂等：按唯一编码存在即跳过）。

设计原则：
- 与移动端 Mock 夹具对齐（小区名、类目、热词），保证端到端联调语义一致；
- 区划/类目/字典/参数为生产初始化必需数据；角色/权限为 RBAC 基线；
- 超管账号仅开发环境使用（admin / Admin@2025），生产部署必须替换并开启 2FA；
- 不含任何演示业务数据（物品/订单/用户），演示数据脚本与生产隔离。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import hash_password
from src.db.models import (
    AdminUser,
    Community,
    Dictionary,
    DictionaryItem,
    HotKeyword,
    ItemCategory,
    ParameterItem,
    ParameterKey,
    Permission,
    Region,
    Role,
    admin_user_roles,
    role_permissions,
)

# ---------------------------------------------------------------- 行政区划

# 全国 31 个省级行政区；浙江省保留既有夹具编码，北京市与陕西省下钻到街道。
# 数据源：modood/Administrative-divisions-of-China（dist/pcas-code.json，2023-09-13）。
REGION_DATA_PATH = Path(__file__).with_name("data") / "regions.json"
with REGION_DATA_PATH.open(encoding="utf-8") as _region_file:
    _REGION_ITEMS = json.load(_region_file)

REGIONS = [
    # (name, level, code, parent_code, sort)
    (item["name"], item["level"], item["code"], item["parentCode"], item["sort"])
    for item in _REGION_ITEMS
]

# 与移动端 Mock（mobile/config/mock/data.ts）对齐的小区夹具。
# 首条「阳光花园小区」为移动端默认本小区；其余为邻近小区（约 3km 内）。
COMMUNITIES = [
    # (name, code, type, street_code, address, lng, lat, households, population)
    ("阳光花园小区", "SQ3301060001", "商品房社区", "330106001", "文新街道阳光花园", 120.1050, 30.2890, 2106, 4582),
    ("梧桐里", "SQ3301060002", "商品房社区", "330106001", "文新街道梧桐里", 120.1085, 30.2871, 1680, 3600),
    ("悦府家园", "SQ3301060003", "商品房社区", "330106002", "西溪街道悦府家园", 120.0980, 30.2830, 2460, 5400),
    ("云栖苑", "SQ3301060004", "综合型社区", "330106002", "西溪街道云栖苑", 120.0920, 30.2860, 3200, 7100),
    ("湖畔名庭", "SQ3301020001", "商品房社区", "330102001", "湖滨街道湖畔名庭", 120.1210, 30.2750, 1980, 4300),
    ("春和社区", "SQ3301060005", "老旧小区", "330106003", "翠苑街道春和社区", 120.1200, 30.2900, 1860, 4820),
    ("小河佳苑社区", "SQ3301050001", "村改居社区", "330105001", "小河街道小河佳苑", 120.1310, 30.2960, 1500, 3900),
]

# ---------------------------------------------------------------- 物品类目（SRS M02-01）

ITEM_CATEGORIES = [
    ("家具家电", ["桌椅柜架", "床品床垫", "厨房电器", "生活电器", "其他家具"]),
    ("母婴用品", ["婴儿床车", "安全座椅", "玩具绘本", "喂养用品", "童装童鞋"]),
    ("数码", ["手机平板", "电脑外设", "影音耳机", "智能设备", "相机摄影"]),
    ("图书", ["童书绘本", "小说文学", "教材教辅", "社科人文", "其他图书"]),
    ("服饰", ["女装", "男装", "童装", "鞋靴箱包", "配饰"]),
    ("运动户外", ["健身器材", "骑行装备", "露营装备", "球类用品", "其他运动"]),
    ("其他", ["绿植宠物", "乐器", "收藏", "手工材料", "其他闲置"]),
]

# ---------------------------------------------------------------- 字典

DICTIONARIES: dict[str, list[tuple[str, str, str]]] = {
    "trade_type": [("货币交易（担保支付）", "MONETARY", "violet"), ("免费赠与", "FREE_GIFT", "green"), ("物品互换", "BARTER", "blue")],
    "item_condition": [
        ("全新", "NEW", "green"), ("九九新", "LIKE_NEW", "green"),
        ("轻微使用痕迹", "LIGHT_USED", "blue"), ("明显使用痕迹", "USED", "orange"),
        ("有功能缺陷", "DEFECTIVE", "red"),
    ],
    "identity_type": [("业主", "OWNER", "violet"), ("租户", "TENANT", "blue"), ("家属", "FAMILY", "green"), ("商务人员", "BUSINESS", "orange")],
    "penalty_type": [("警告", "WARNING", "orange"), ("禁言", "MUTE", "orange"), ("限制发布", "PUBLISH_LIMIT", "red"), ("限制交易", "TRADE_LIMIT", "red"), ("封禁", "BAN", "red")],
    "notification_channel": [("站内信", "IN_APP", "violet"), ("短信", "SMS", "blue"), ("App 推送", "PUSH", "green"), ("服务通知", "SERVICE", "orange")],
    "report_target_type": [("物品", "ITEM", "orange"), ("用户", "USER", "red"), ("会话", "CONVERSATION", "blue"), ("留言", "COMMENT", "orange"), ("私信", "MESSAGE", "blue"), ("生活内容", "LIFE_POST", "green")],
}

# ---------------------------------------------------------------- 权限（在 web/backend 基线上补齐 P0 缺口）

PERMISSIONS: list[tuple[str, str, str, str | None]] = [
    ("dashboard:view", "查看工作台", "页面", "/dashboard"),
    ("dashboard:export", "生成运营简报", "按钮", None),
    ("community:broadcast:view", "查看社区喇叭", "页面", "/community-operations/broadcast"),
    ("community:broadcast:create", "发布喇叭", "按钮", None),
    ("community:broadcast:update", "编辑喇叭", "按钮", None),
    ("community:broadcast:delete", "删除喇叭", "按钮", None),
    ("community:broadcast:review", "审核喇叭", "按钮", None),
    ("community:broadcast:offline", "下架喇叭", "按钮", None),
    ("community:item:view", "查看社区物品", "页面", "/community-operations/items"),
    ("community:item:create", "新增物品", "按钮", None),
    ("community:item:update", "编辑物品", "按钮", None),
    ("community:item:delete", "删除物品", "按钮", None),
    ("community:item:review", "审核物品", "按钮", None),
    ("community:item:recommend", "设置热门推荐", "按钮", None),
    ("community:item:offline", "下架物品", "按钮", None),
    ("community:item:category", "类目管理", "按钮", None),
    ("community:help:view", "查看邻里互助", "页面", "/community-operations/help"),
    ("community:help:create", "代发互助", "按钮", None),
    ("community:help:update", "编辑互助", "按钮", None),
    ("community:help:delete", "删除互助", "按钮", None),
    ("community:help:review", "审核邻里服务", "按钮", None),
    ("community:help:match", "人工撮合", "按钮", None),
    ("community:help:close", "关闭互助", "按钮", None),
    ("community:life:view", "查看社区生活", "页面", "/community-operations/life"),
    ("community:life:create", "新建生活内容", "按钮", None),
    ("community:life:update", "编辑生活内容", "按钮", None),
    ("community:life:delete", "删除生活内容", "按钮", None),
    ("community:life:review", "审核生活内容", "按钮", None),
    ("community:life:offline", "下线生活内容", "按钮", None),
    ("communication:notice:view", "查看公告", "页面", "/communication/notices"),
    ("communication:notice:create", "发布公告", "按钮", None),
    ("communication:notice:publish", "发布/撤回公告", "按钮", None),
    ("communication:task:view", "查看通知任务", "页面", "/communication/notification-tasks"),
    ("communication:task:create", "新建通知", "按钮", None),
    ("communication:task:send", "发送通知", "按钮", None),
    ("communication:template:view", "通知模板", "页面", None),
    ("community:maintenance:view", "查看社区运维", "页面", "/community-management/maintenance"),
    ("community:maintenance:create", "新增社区", "按钮", None),
    ("community:maintenance:update", "编辑社区", "按钮", None),
    ("community:resident:view", "查看社区业主", "页面", "/community-management/residents"),
    ("community:resident:create", "新增人员", "按钮", None),
    ("community:resident:update", "编辑人员", "按钮", None),
    ("community:resident:audit", "认证审核", "按钮", None),
    ("community:resident:freeze", "冻结/解冻", "按钮", None),
    ("community:resident:revoke", "撤销认证", "按钮", None),
    ("community:resident:admin-grant", "授予住户后台角色", "按钮", None),
    ("community:resident:admin-revoke", "解除住户后台授权", "按钮", None),
    ("governance:repair:view", "查看工单", "页面", "/governance/repair-orders"),
    ("governance:repair:assign", "派发工单", "按钮", None),
    ("governance:repair:process", "处理工单", "按钮", None),
    ("governance:repair:accept", "验收工单", "按钮", None),
    ("governance:repair:close", "关闭工单", "按钮", None),
    ("governance:feedback:view", "查看反馈", "页面", "/governance/feedback"),
    ("governance:feedback:reply", "回复反馈", "按钮", None),
    ("governance:feedback:assign", "指派反馈", "按钮", None),
    ("governance:feedback:close", "关闭反馈", "按钮", None),
    ("governance:dispute:view", "查看纠纷", "页面", "/governance/disputes"),
    ("governance:dispute:mediate", "调解纠纷", "按钮", None),
    ("governance:dispute:freeze", "冻结资金", "按钮", None),
    ("governance:dispute:resolve", "出具结论", "按钮", None),
    ("governance:report:view", "查看举报", "页面", "/governance/reports"),
    ("governance:report:handle", "处理举报", "按钮", None),
    ("finance:overview:view", "查看资金看板", "页面", "/finance/overview"),
    ("finance:transaction:view", "查看资金流水", "页面", "/finance/transactions"),
    ("finance:withdrawal:view", "查看提现", "页面", "/finance/withdrawals"),
    ("finance:withdrawal:review", "审核提现", "按钮", None),
    ("finance:reconcile:view", "查看对账", "页面", "/finance/reconciliations"),
    ("finance:reconcile:run", "重新对账", "按钮", None),
    ("finance:order:view", "查看订单", "页面", "/finance/orders"),
    ("finance:adjustment:create", "申请资金处置", "按钮", None),
    ("finance:adjustment:review", "复核资金处置", "按钮", None),
    ("system:user:view", "查看用户", "页面", "/system/users"),
    ("system:user:create", "新增用户", "按钮", None),
    ("system:user:update", "编辑用户", "按钮", None),
    ("system:user:penalty", "用户处置", "按钮", None),
    ("system:admin-user:view", "查看管理员", "页面", None),
    ("system:admin-user:create", "新增管理员", "按钮", None),
    ("system:admin-user:update", "编辑管理员", "按钮", None),
    ("system:role:view", "查看角色", "页面", "/system/roles"),
    ("system:role:create", "新建角色", "按钮", None),
    ("system:role:update", "编辑角色", "按钮", None),
    ("system:role:delete", "删除角色", "按钮", None),
    ("system:role:grant", "配置权限", "按钮", None),
    ("system:resource:view", "查看资源", "页面", "/system/resources"),
    ("system:resource:create", "新增资源", "按钮", None),
    ("system:resource:update", "编辑资源", "按钮", None),
    ("system:resource:delete", "删除资源", "按钮", None),
    ("system:parameter:view", "查看参数", "页面", "/system/parameters"),
    ("system:parameter:create", "新增参数", "按钮", None),
    ("system:parameter:update", "编辑参数", "按钮", None),
    ("system:parameter:publish", "发布参数", "按钮", None),
    ("system:audit:view", "查看审计日志", "页面", "/system/audit-logs"),
    ("reporting:export:view", "查看导出任务", "页面", "/analytics/exports"),
    ("reporting:export:create", "创建导出任务", "按钮", None),
]

ROLE_BLUEPRINTS: dict[str, dict] = {
    "super_admin": {"name": "超级管理员", "description": "拥有系统全部权限", "data_scope": "ALL", "builtin": True},
    "community_operator": {"name": "社区运营", "description": "负责社区内容、活动和用户运营", "data_scope": "OWN_COMMUNITY"},
    "community_admin": {
        "name": "社区管理员",
        "description": "负责本社区内容运营、住户服务与认证审核",
        "data_scope": "OWN_COMMUNITY",
        "builtin": True,
        "assignable_to_resident": True,
    },
    "property_service": {"name": "物业客服", "description": "处理报修、投诉及住户认证", "data_scope": "COMMUNITY_SET"},
    "content_reviewer": {"name": "内容审核员", "description": "负责动态、评论及商品内容审核", "data_scope": "OWN_COMMUNITY"},
    "finance_admin": {"name": "资金管理员", "description": "负责托管资金、提现复核、对账与资金处置", "data_scope": "ALL"},
    "data_analyst": {"name": "数据分析员", "description": "只读数据看板与报表", "data_scope": "ALL"},
}

ROLE_PERMISSION_PREFIXES: dict[str, tuple[str, ...]] = {
    "community_operator": (
        "dashboard:", "community:broadcast", "community:item", "community:help",
        "community:life", "communication:", "community:maintenance", "community:resident:view",
        "community:resident:admin-", "governance:report:", "reporting:",
    ),
    "community_admin": (
        "dashboard:view",
        "community:broadcast:view", "community:broadcast:create",
        "community:broadcast:update", "community:broadcast:delete",
        "community:broadcast:review", "community:broadcast:offline",
        "community:item:view", "community:item:create", "community:item:update",
        "community:item:delete", "community:item:review", "community:item:recommend",
        "community:item:offline",
        "community:help:", "community:life:",
        "community:maintenance:view",
        "community:resident:view", "community:resident:audit",
        "communication:notice:view", "communication:notice:create",
        "communication:notice:publish",
        "communication:task:view", "communication:task:create", "communication:task:send",
        "governance:report:view", "governance:report:handle",
        "reporting:export:view",
    ),
    "property_service": (
        "dashboard:", "governance:repair", "governance:feedback", "community:resident:",
        "communication:",
    ),
    "content_reviewer": (
        "dashboard:", "community:broadcast", "community:item", "community:life",
        "governance:report",
    ),
    "finance_admin": (
        "dashboard:", "finance:", "governance:dispute", "system:audit:view",
    ),
    "data_analyst": (
        "dashboard:view", "dashboard:export", "finance:overview:view", "finance:order:view",
        "finance:transaction:view", "reporting:export:",
    ),
}

# ---------------------------------------------------------------- 参数（W04-05，与 domain/enums.RULE_DEFAULTS 对齐）

PARAMETER_TREE: dict[str, list[tuple[str, str, str]]] = {
    "发布与质检": [
        ("item.photos.min", "3", "物品照片最少张数（BR-05）"),
        ("item.photos.max", "12", "物品照片最多张数（BR-05）"),
        ("item.expire.days", "30", "上架有效期天数（BR-07）"),
        ("ai.review.fast_track_confidence", "0.95", "AI 高置信免复核阈值（W03-01）"),
        ("ai.review.timeout_seconds", "60", "AI 质检超时转人工（NF-04）"),
    ],
    "交易与履约": [
        ("order.pay.timeout_minutes", "30", "下单未支付自动取消（M06-03）"),
        ("order.confirm.timeout_hours", "48", "申请未响应自动取消（M06-02）"),
        ("order.auto_release.hours", "72", "买家超时未确认自动放款（BR-11）"),
    ],
    "社区与邻近": [
        ("community.nearby.radius_km", "3", "邻近小区判定半径（W04-02/BR-03）"),
        ("community.nearby.max_count", "10", "邻近小区最大展示数（W04-02）"),
        ("community.cross_trade_enabled", "false", "跨小区交易开关（默认关闭，11.1）"),
    ],
    "资金与风控": [
        ("finance.withdrawal.review_threshold_cents", "500000", "提现双人复核阈值（分，W06-04）"),
        ("finance.reconcile.diff_alert_threshold", "100", "对账差异告警阈值（分）"),
        ("finance.refund.sla_hours", "24", "退款处理时限（小时）"),
        ("finance.withdrawal.fee_rate", "0.001", "提现手续费率（M06-05）"),
    ],
    "社交与内容": [
        ("friend.max_count", "500", "好友数量上限（BR-14）"),
        ("content.review.required", "true", "UGC 全量内容安全审核（A-09）"),
    ],
    "账号与合规": [
        ("agreement.user.version", "2026-11-01", "用户协议版本（管理员维护）"),
        ("agreement.privacy.version", "2026-11-01", "隐私政策版本（管理员维护）"),
    ],
}

HOT_KEYWORDS = ["儿童椅", "婴儿床", "绘本", "露营", "戴森", "免费领取"]


def _parent_code_for(level: str, code: str) -> str | None:
    """按国标区划编码规则推导上级编码（省 2 位 / 市 4 位 / 区县 6 位）。"""
    if len(code) < 6:
        return None
    if level == "CITY":
        return f"{code[:2]}0000"
    if level == "DISTRICT":
        return f"{code[:4]}00"
    if level == "STREET":
        return code[:6]
    return None


async def _regions_need_sync(session: AsyncSession) -> bool:
    """用轻量计数判断是否需同步：避免每次启动拉取 1800+ 行区划。"""
    total = await session.scalar(select(func.count()).select_from(Region)) or 0
    if total < len(REGIONS):
        return True
    sentinel = ("110101001", "610102001", "330106001")
    found = await session.scalar(
        select(func.count()).select_from(Region).where(Region.code.in_(sentinel))) or 0
    if found != len(sentinel):
        return True
    broken_parents = await session.scalar(
        select(func.count()).select_from(Region)
        .where(Region.level != "PROVINCE", Region.parent_id.is_(None))) or 0
    if broken_parents:
        return True
    missing_binding = await session.scalar(
        select(func.count()).select_from(Community)
        .where(Community.street_id.is_not(None), Community.region_id.is_(None))) or 0
    return bool(missing_binding)


async def _sync_regions(session: AsyncSession) -> dict[str, Region]:
    """按 REGIONS 幂等同步区划：补齐缺失节点并校正父级/排序，不删除管理员新增区划。"""
    rows = list((await session.execute(select(Region))).scalars().all())
    by_code = {row.code: row for row in rows}
    # 按层级批量写入：每层 flush 一次，父节点先取得主键，避免 1800+ 次逐条往返。
    for level in ("PROVINCE", "CITY", "DISTRICT", "STREET"):
        for name, item_level, code, parent_code, sort in REGIONS:
            if item_level != level:
                continue
            parent = by_code.get(parent_code) if parent_code else None
            desired_parent_id = parent.id if parent else None
            existing = by_code.get(code)
            if existing is None:
                region = Region(name=name, level=level, code=code,
                                parent_id=desired_parent_id, sort=sort)
                session.add(region)
                by_code[code] = region
                continue
            if (existing.name != name or existing.level != level
                    or existing.parent_id != desired_parent_id or existing.sort != sort):
                existing.name = name
                existing.level = level
                existing.parent_id = desired_parent_id
                existing.sort = sort
        await session.flush()
    return by_code


async def _repair_region_links(session: AsyncSession) -> None:
    """修复历史种子数据的区划父子关系（早期版本在 flush 前取 parent.id，导致全为 NULL）。"""
    rows = list((await session.execute(select(Region))).scalars().all())
    by_code = {row.code: row for row in rows}
    changed = False
    for row in rows:
        if row.level == "PROVINCE" or row.parent_id:
            continue
        parent_code = _parent_code_for(row.level, row.code)
        parent = by_code.get(parent_code) if parent_code else None
        if parent is not None and parent.id != row.id:
            row.parent_id = parent.id
            changed = True
    if changed:
        await session.flush()
    street_by_id = {row.id: row for row in rows if row.level == "STREET"}
    communities = list((await session.execute(
        select(Community).where(Community.street_id.is_not(None))
    )).scalars().all())
    for community in communities:
        street = street_by_id.get(community.street_id)
        if street is not None and street.parent_id and community.region_id != street.parent_id:
            community.region_id = street.parent_id
            changed = True
    if changed:
        await session.commit()


async def seed_if_empty(session: AsyncSession) -> dict[str, int] | None:
    """初始化种子；已初始化返回 None，本次写入返回各领域数量摘要。"""
    if await session.scalar(select(AdminUser.id).limit(1)):
        # 已初始化：仅当区划缺失/父子关系或小区绑定未修复时才同步，避免拖慢每次启动。
        if await _regions_need_sync(session):
            await _sync_regions(session)
            await _repair_region_links(session)
            await session.commit()
        return None

    # 区划
    region_by_code = await _sync_regions(session)

    # 社区
    for i, (name, code, ctype, street_code, address, lng, lat, households, population) in enumerate(COMMUNITIES):
        street = region_by_code.get(street_code)
        session.add(Community(
            region_id=street.parent_id if street else None,
            street_id=street.id if street else None,
            name=name, code=code, type=ctype, address=address,
            longitude=lng, latitude=lat, households=households, population=population,
            manager_name="", status="OPERATING", opened_at=date(2024, 1, 1),
        ))

    # 类目
    for sort, (parent_name, children) in enumerate(ITEM_CATEGORIES):
        parent = ItemCategory(name=parent_name, sort=sort)
        session.add(parent)
        await session.flush()
        for child_sort, child_name in enumerate(children):
            session.add(ItemCategory(name=child_name, parent_id=parent.id, sort=child_sort))

    # 字典
    for code, items in DICTIONARIES.items():
        dictionary = Dictionary(code=code, name=code, description=f"{code} 字典")
        session.add(dictionary)
        await session.flush()
        for sort, (label, value, tone) in enumerate(items):
            session.add(DictionaryItem(dictionary_id=dictionary.id, label=label,
                                       value=value, tone=tone, sort=sort))

    # 权限与角色
    permission_rows: dict[str, Permission] = {}
    for sort, (code, name, ptype, route) in enumerate(PERMISSIONS):
        permission = Permission(name=name, code=code, type=ptype, route=route or "", sort=sort)
        session.add(permission)
        permission_rows[code] = permission
    await session.flush()

    roles: dict[str, Role] = {}
    for code, blueprint in ROLE_BLUEPRINTS.items():
        role = Role(name=blueprint["name"], code=code, description=blueprint["description"],
                    data_scope=blueprint["data_scope"], is_builtin=blueprint.get("builtin", False),
                    assignable_to_resident=blueprint.get("assignable_to_resident", False))
        session.add(role)
        roles[code] = role
    await session.flush()

    for role_code, prefixes in ROLE_PERMISSION_PREFIXES.items():
        for perm_code, permission in permission_rows.items():
            if perm_code.startswith(prefixes):
                await session.execute(insert(role_permissions).values(
                    role_id=roles[role_code].id, permission_id=permission.id))

    # 超管权限由 is_super_admin 在运行时放行（permissions.py），无需落库全量授权

    # 超管（开发账号，生产必须替换）
    admin = AdminUser(
        username="admin", password_hash=hash_password("Admin@2025"),
        real_name="平台管理员", avatar_text="管", status="ACTIVE", is_super_admin=True,
    )
    session.add(admin)
    await session.flush()
    await session.execute(insert(admin_user_roles).values(
        admin_user_id=admin.id, role_id=roles["super_admin"].id))

    # 参数树（按 code 幂等：迁移可能已补入协议版本等参数）
    for sort, (group_label, items) in enumerate(PARAMETER_TREE.items()):
        group_code = f"group.{sort}"
        group = await session.scalar(
            select(ParameterKey).where(ParameterKey.code == group_code))
        if not group:
            group = ParameterKey(label=group_label, code=group_code, kind="GROUP", sort=sort)
            session.add(group)
            await session.flush()
        for item_sort, (code, value, description) in enumerate(items):
            key = await session.scalar(
                select(ParameterKey).where(ParameterKey.code == code))
            if not key:
                key = ParameterKey(label=description[:12], code=code, kind="KEY",
                                   sort=item_sort, parent_id=group.id)
                session.add(key)
                await session.flush()
            existing_item = await session.scalar(
                select(ParameterItem).where(ParameterItem.parameter_key_id == key.id,
                                            ParameterItem.name == code))
            if not existing_item:
                session.add(ParameterItem(parameter_key_id=key.id, name=code, value=value,
                                          description=description))

    # 搜索热词（与移动端 Mock 对齐）
    for sort, keyword in enumerate(HOT_KEYWORDS):
        session.add(HotKeyword(keyword=keyword, sort=sort, score=100 - sort))

    await session.commit()
    return {
        "regions": len(REGIONS),
        "communities": len(COMMUNITIES),
        "categories": sum(1 + len(children) for _, children in ITEM_CATEGORIES),
        "dictionaries": len(DICTIONARIES),
        "dictionaryItems": sum(len(items) for items in DICTIONARIES.values()),
        "permissions": len(PERMISSIONS),
        "roles": len(ROLE_BLUEPRINTS),
        "parameterItems": sum(len(items) for items in PARAMETER_TREE.values()),
        "hotKeywords": len(HOT_KEYWORDS),
    }
