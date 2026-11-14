from __future__ import annotations

from datetime import date

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import hash_password, verify_password
from src.db.models import (
    AdminUser,
    AuditLog,
    Broadcast,
    Community,
    DashboardSnapshot,
    Dispute,
    Feedback,
    HelpRequest,
    Item,
    LifePost,
    Notice,
    NotificationTask,
    OrderRecord,
    PageResource,
    ParameterItem,
    ParameterKey,
    PaymentTransaction,
    Permission,
    PlatformUser,
    Reconciliation,
    Region,
    RepairOrder,
    Resident,
    Role,
    SysPage,
    Withdrawal,
    admin_user_roles,
    role_permissions,
)

PERMISSIONS: list[tuple[str, str, str, str | None]] = [
    ("dashboard:view", "查看工作台", "页面", "/dashboard"),
    ("dashboard:export", "生成运营简报", "按钮", None),
    ("community:broadcast:view", "查看社区喇叭", "页面", "/community-operations/broadcast"),
    ("community:broadcast:create", "发布喇叭", "按钮", None),
    ("community:broadcast:review", "审核喇叭", "按钮", None),
    ("community:broadcast:offline", "下架喇叭", "按钮", None),
    ("community:item:view", "查看社区物品", "页面", "/community-operations/items"),
    ("community:item:create", "新增物品", "按钮", None),
    ("community:item:review", "审核物品", "按钮", None),
    ("community:item:recommend", "设置热门推荐", "按钮", None),
    ("community:item:offline", "下架物品", "按钮", None),
    ("community:help:view", "查看邻里互助", "页面", "/community-operations/help"),
    ("community:help:create", "代发互助", "按钮", None),
    ("community:help:match", "人工撮合", "按钮", None),
    ("community:help:close", "关闭互助", "按钮", None),
    ("community:life:view", "查看社区生活", "页面", "/community-operations/life"),
    ("community:life:create", "新建生活内容", "按钮", None),
    ("community:life:review", "审核生活内容", "按钮", None),
    ("community:life:offline", "下线生活内容", "按钮", None),
    ("communication:notice:view", "查看公告", "页面", "/communication/notices"),
    ("communication:notice:create", "发布公告", "按钮", None),
    ("communication:notice:publish", "发布/撤回公告", "按钮", None),
    ("communication:task:view", "查看通知任务", "页面", "/communication/notification-tasks"),
    ("communication:task:create", "新建通知", "按钮", None),
    ("communication:task:send", "发送通知", "按钮", None),
    ("community:maintenance:view", "查看社区运维", "页面", "/community-management/maintenance"),
    ("community:maintenance:create", "新增社区", "按钮", None),
    ("community:maintenance:update", "编辑社区", "按钮", None),
    ("community:resident:view", "查看社区业主", "页面", "/community-management/residents"),
    ("community:resident:create", "新增人员", "按钮", None),
    ("community:resident:update", "编辑人员", "按钮", None),
    ("community:resident:delete", "删除人员", "按钮", None),
    ("community:resident:audit", "认证审核", "按钮", None),
    ("community:resident:freeze", "冻结/解冻", "按钮", None),
    ("system:user:view", "查看用户", "页面", "/system/users"),
    ("system:user:create", "新增用户", "按钮", None),
    ("system:user:update", "编辑用户", "按钮", None),
    ("system:user:reset-password", "重置密码", "按钮", None),
    ("system:user:penalty", "用户处置", "按钮", None),
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
    ("finance:overview:view", "查看资金看板", "页面", "/finance/overview"),
    ("finance:transaction:view", "查看资金流水", "页面", "/finance/transactions"),
    ("finance:withdrawal:view", "查看提现", "页面", "/finance/withdrawals"),
    ("finance:withdrawal:review", "审核提现", "按钮", None),
    ("finance:reconcile:view", "查看对账", "页面", "/finance/reconciliations"),
    ("finance:reconcile:run", "重新对账", "按钮", None),
    ("finance:order:view", "查看订单", "页面", "/finance/orders"),
    ("finance:adjustment:create", "资金处置", "按钮", None),
    ("reporting:export:view", "查看导出任务", "页面", "/analytics/exports"),
    ("reporting:export:create", "创建导出任务", "按钮", None),
]

ROLE_BLUEPRINTS: dict[str, dict] = {
    "super_admin": {
        "name": "超级管理员",
        "description": "拥有系统全部菜单、数据及操作权限",
        "data_scope": "ALL",
        "is_builtin": True,
        "members": 3,
    },
    "community_operator": {
        "name": "社区运营",
        "description": "负责社区内容、活动和用户运营",
        "data_scope": "OWN_COMMUNITY",
        "members": 12,
    },
    "property_service": {
        "name": "物业客服",
        "description": "处理报修、投诉及住户认证",
        "data_scope": "COMMUNITY_SET",
        "members": 28,
    },
    "content_reviewer": {
        "name": "内容审核员",
        "description": "负责动态、评论及商品内容审核",
        "data_scope": "OWN_COMMUNITY",
        "members": 6,
    },
    "finance_admin": {
        "name": "资金管理员",
        "description": "负责托管资金、提现复核、对账与资金处置",
        "data_scope": "ALL",
        "members": 2,
    },
}


def _permissions_for(role_code: str) -> list[str]:
    if role_code == "super_admin":
        return [p[0] for p in PERMISSIONS]
    if role_code == "community_operator":
        prefixes = ("dashboard:", "community:broadcast", "community:item", "community:help",
                    "community:life", "communication:", "community:maintenance", "community:resident:view",
                    "reporting:")
    elif role_code == "property_service":
        prefixes = ("dashboard:", "governance:repair", "governance:feedback", "community:resident:",
                    "communication:")
    elif role_code == "content_reviewer":
        prefixes = ("dashboard:", "community:broadcast", "community:item", "community:life")
    elif role_code == "finance_admin":
        prefixes = ("dashboard:", "finance:", "governance:dispute", "system:audit:view")
    else:
        prefixes = ()
    return [p[0] for p in PERMISSIONS if p[0].startswith(prefixes)]


async def repair_seed_data(session: AsyncSession) -> None:
    """Idempotent repair for development databases seeded before the region
    parent flush fix. Safe to run on every startup; it only fills missing links."""
    rows = list((await session.execute(select(Region))).scalars().all())
    by_code = {row.code: row for row in rows}
    parent_map = {
        "330100": "330000",
        "330106": "330100",
        "330102": "330100",
        "330105": "330100",
        "330106001": "330106",
        "330106002": "330106",
        "330106003": "330106",
        "330102001": "330102",
        "330105001": "330105",
    }
    changed = False
    for child_code, parent_code in parent_map.items():
        child = by_code.get(child_code)
        parent = by_code.get(parent_code)
        if child and parent and child.parent_id != parent.id:
            child.parent_id = parent.id
            changed = True
    admin = await session.scalar(select(AdminUser).where(AdminUser.username == "admin"))
    if admin and verify_password("admin123", admin.password_hash):
        # Align the development demo credential with the Figma login screen.
        admin.password_hash = hash_password("Admin@2025")
        changed = True
    if changed:
        await session.commit()


async def seed_if_empty(session: AsyncSession) -> None:
    existing = await session.scalar(select(AdminUser.id).limit(1))
    if existing:
        return

    roles: dict[str, Role] = {}
    for code, blueprint in ROLE_BLUEPRINTS.items():
        role = Role(
            name=blueprint["name"],
            code=code,
            description=blueprint["description"],
            data_scope=blueprint["data_scope"],
            is_builtin=blueprint.get("is_builtin", False),
            members=blueprint.get("members", 0),
        )
        session.add(role)
        roles[code] = role
    await session.flush()

    permission_rows: dict[str, Permission] = {}
    for sort, (code, name, type_, route) in enumerate(PERMISSIONS):
        permission = Permission(name=name, code=code, type=type_, route=route, sort=sort)
        session.add(permission)
        permission_rows[code] = permission
    await session.flush()

    for role_code, role in roles.items():
        for code in _permissions_for(role_code):
            permission = permission_rows.get(code)
            if permission:
                await session.execute(
                    insert(role_permissions).values(role_id=role.id, permission_id=permission.id)
                )

    admin = AdminUser(
        username="admin",
        password_hash=hash_password("Admin@2025"),
        real_name="夏木",
        phone="138****0921",
        email="admin@neighinn.local",
        avatar_text="夏",
        status="ACTIVE",
        is_super_admin=True,
    )
    session.add(admin)
    await session.flush()
    await session.execute(
        insert(admin_user_roles).values(admin_user_id=admin.id, role_id=roles["super_admin"].id)
    )

    # Administrative divisions
    def add_region(name: str, level: str, code: str, parent: Region | None = None, sort: int = 0) -> Region:
        region = Region(name=name, level=level, code=code, parent_id=parent.id if parent else None, sort=sort)
        session.add(region)
        return region

    zhejiang = add_region("浙江省", "PROVINCE", "330000")
    await session.flush()
    hangzhou = add_region("杭州市", "CITY", "330100", zhejiang, 1)
    await session.flush()
    xihu = add_region("西湖区", "DISTRICT", "330106", hangzhou, 1)
    shangcheng = add_region("上城区", "DISTRICT", "330102", hangzhou, 2)
    gongshu = add_region("拱墅区", "DISTRICT", "330105", hangzhou, 3)
    await session.flush()
    wenxin = add_region("文新街道", "STREET", "330106001", xihu, 1)
    xixi = add_region("西溪街道", "STREET", "330106002", xihu, 2)
    cuiyuan = add_region("翠苑街道", "STREET", "330106003", xihu, 3)
    hubin = add_region("湖滨街道", "STREET", "330102001", shangcheng, 1)
    xiaohe = add_region("小河街道", "STREET", "330105001", gongshu, 1)
    await session.flush()

    communities = [
        Community(region_id=xihu.id, street_id=wenxin.id, name="云栖里社区", code="SQ3301060012",
                  type="商品房社区", address="文新街道云栖里", longitude="120.102", latitude="30.287",
                  households=2106, population=4582, manager_name="林嘉禾", status="正常运营",
                  opened_at=date(2024, 6, 18)),
        Community(region_id=xihu.id, street_id=xixi.id, name="滨河家园社区", code="SQ3301060018",
                  type="综合型社区", address="西溪街道滨河家园", longitude="120.090", latitude="30.280",
                  households=3680, population=9200, manager_name="陈知夏", status="正常运营",
                  opened_at=date(2024, 2, 18)),
        Community(region_id=xihu.id, street_id=cuiyuan.id, name="春和社区", code="SQ3301060024",
                  type="老旧小区", address="翠苑街道春和社区", longitude="120.120", latitude="30.290",
                  households=1860, population=4820, manager_name="周砚", status="正常运营",
                  opened_at=date(2023, 9, 12)),
        Community(region_id=xihu.id, street_id=wenxin.id, name="拾光公寓", code="SQ3301060031",
                  type="商品房社区", address="文新街道拾光公寓", households=980, population=2100,
                  manager_name="王宁", status="正常运营", opened_at=date(2024, 10, 8)),
        Community(region_id=shangcheng.id, street_id=hubin.id, name="东坡路社区", code="SQ3301020006",
                  type="综合型社区", address="湖滨街道东坡路", households=2400, population=6100,
                  manager_name="李清", status="正常运营", opened_at=date(2023, 5, 20)),
        Community(region_id=gongshu.id, street_id=xiaohe.id, name="小河佳苑社区", code="SQ3301050015",
                  type="村改居社区", address="小河街道小河佳苑", households=1500, population=3900,
                  manager_name="林嘉禾", status="筹备中", opened_at=date(2025, 1, 8)),
    ]
    session.add_all(communities)
    await session.flush()
    c = {item.name: item for item in communities}

    residents = [
        ("林小满", "女", "138****0921", "业主", "8 栋 1 单元 902", "房屋产权人", "已认证",
         "YZ330106000821", "社区达人", "正常", "2024-06-18", c["云栖里社区"].id),
        ("陈屿舟", "男", "186****4420", "家属", "8 栋 1 单元 902", "业主配偶", "已认证",
         "JS330106001139", "活跃用户", "正常", "2024-06-20", c["云栖里社区"].id),
        ("沈嘉禾", "男", "139****7728", "业主", "3 栋 2 单元 1401", "房屋产权人", "待审核",
         "YZ330106002364", "普通用户", "正常", "2025-03-20", c["云栖里社区"].id),
        ("裴溪", "女", "177****3012", "租户", "2 栋 2 单元 1401", "整租租户", "待审核",
         "ZH330106001827", "普通用户", "正常", "2025-03-19", c["云栖里社区"].id),
        ("周言", "男", "135****6672", "商务人员", "邻里中心 A-18", "商户负责人", "已认证",
         "SW330106000436", "活跃用户", "正常", "2024-11-08", c["云栖里社区"].id),
        ("刘玉兰", "女", "136****1185", "业主", "6 栋 1 单元 302", "房屋产权人", "已认证",
         "YZ330106000178", "重点关怀", "正常", "2023-09-12", c["云栖里社区"].id),
        ("徐安", "男", "159****3088", "租户", "11 栋 2 单元 603", "合租租户", "认证驳回",
         "ZH330106002018", "普通用户", "正常", "2025-03-16", c["云栖里社区"].id),
        ("许清", "女", "188****2066", "家属", "5 栋 1 单元 1102", "业主子女", "已认证",
         "JS330106001520", "活跃用户", "正常", "2024-08-22", c["云栖里社区"].id),
        ("高敏", "女", "131****4205", "商务人员", "邻里中心 B-06", "门店店员", "未认证",
         "—", "普通用户", "已停用", "2025-02-10", c["云栖里社区"].id),
        ("顾言", "男", "138****5028", "业主", "2 栋 1 单元 1801", "房屋产权人", "已认证",
         "YZ330106003120", "社区达人", "正常", "2024-02-18", c["滨河家园社区"].id),
        ("宋知夏", "女", "137****2910", "租户", "7 栋 2 单元 501", "整租租户", "已认证",
         "ZH330106003528", "活跃用户", "正常", "2024-10-08", c["滨河家园社区"].id),
        ("莫白", "男", "152****6639", "业主", "1 栋 2 单元 702", "房屋产权人", "已认证",
         "YZ330106004101", "普通用户", "正常", "2024-07-15", c["春和社区"].id),
    ]
    for name, gender, phone, identity, building, relationship, certification, cert_no, level, status, joined, cid in residents:
        session.add(Resident(
            community_id=cid, name=name, gender=gender, phone=phone, identity_type=identity,
            building=building, relationship=relationship, certification_status=certification,
            certification_no=cert_no, level=level, status=status, joined_at=joined,
        ))

    broadcasts = [
        ("LB20250320028", "今晚 7 点中心广场有露天电影", "含图片 · 覆盖云栖里全体住户", "社区运营 · 李知夏",
         "邻里播报", "2,106 触达 · 186 互动", "已发布", "今天 16:28"),
        ("LB20250320027", "3 栋电梯临时检修提醒", "重要提醒 · 仅 3 栋住户", "物业服务中心",
         "物业提醒", "486 触达 · 92% 已读", "已发布", "今天 15:42"),
        ("LB20250320026", "你最期待社区增加什么设施？", "投票话题 · 4 个选项", "社区营造组",
         "话题互动", "328 参与 · 76 评论", "待审核", "今天 14:16"),
        ("LB20250320025", "周末旧物交换摊主招募", "图文内容 · 关联社区物品", "林小满",
         "居民投稿", "—", "待审核", "今天 11:08"),
        ("LB20250320024", "春分节气社区问候", "定时内容 · 全社区", "运营中心",
         "节日节气", "预计触达 4,582 人", "定时发布", "明天 08:00"),
        ("LB20250319019", "宠物友好公约意见征集", "图文内容 · 评论已关闭", "社区居委会",
         "社区议事", "1,835 触达 · 63 互动", "已下架", "昨天 18:30"),
    ]
    for code, title, subtitle, owner, category, performance, status, updated in broadcasts:
        session.add(Broadcast(community_id=c["云栖里社区"].id, code=code, title=title, subtitle=subtitle,
                              owner=owner, category=category, performance=performance, status=status,
                              updated_label=updated))

    items = [
        ("SP20250320118", "九成新儿童平衡车", "¥128 · 2 张图片 · 自提", "小树爸爸 · 8 栋", "母婴玩具",
         12800, "326 浏览 · 18 想要", "在售", "今天 15:36"),
        ("SP20250320117", "实木书桌 120cm", "¥260 · 5 张图片 · 可议价", "7-2-1103", "家居日用",
         26000, "—", "待审核", "今天 14:52"),
        ("SP20250320116", "露营折叠椅两把", "¥90 · 成色 8.5 新", "April · 3 栋", "运动户外",
         9000, "486 浏览 · 32 想要", "已售出", "今天 13:10"),
        ("SP20250320115", "小米电饭煲 3L", "¥75 · 支持送货到楼下", "宋女士 · 11 栋", "数码家电",
         7500, "218 浏览 · 9 想要", "在售", "今天 10:22"),
        ("SP20250319106", "儿童绘本 30 册打包", "¥60 · 适合 3—6 岁", "辰辰妈妈 · 5 栋", "图书教育",
         6000, "156 浏览 · 12 想要", "在售", "昨天 20:18"),
        ("SP20250319098", "品牌空气炸锅", "¥110 · 信息不完整", "张言 · 2 栋", "数码家电",
         11000, "83 浏览", "已下架", "昨天 16:40"),
    ]
    for code, title, subtitle, seller, category, price, performance, status, updated in items:
        session.add(Item(community_id=c["云栖里社区"].id, code=code, title=title, subtitle=subtitle,
                         seller=seller, category=category, price_cents=price, performance=performance,
                         status=status, updated_label=updated))

    helps = [
        ("HZ20250320042", "周六帮忙照看两小时宠物", "期望时间：周六 14:00—16:00", "莫白 · 7 栋",
         "临时照看", "3 人响应 · 距离 120m", "匹配中", "12 分钟前"),
        ("HZ20250320041", "需要借用家用梯子", "预计使用 1 小时 · 已实名认证", "刘阿姨 · 6 栋",
         "物品借用", "已匹配 陈师傅", "进行中", "35 分钟前"),
        ("HZ20250320040", "帮独居老人代取药品", "紧急 · 社区服务站已介入", "网格员 03",
         "志愿服务", "1 人响应", "进行中", "48 分钟前"),
        ("HZ20250320039", "求推荐靠谱的开锁师傅", "希望今天上门", "张言 · 2 栋",
         "信息咨询", "5 条建议", "已完成", "今天 10:20"),
        ("HZ20250320038", "下午有空帮忙搬两箱书", "电梯房 · 预计 20 分钟", "裴溪 · 2 栋",
         "邻里帮忙", "暂无响应", "待响应", "今天 09:48"),
        ("HZ20250319031", "寻找一起晨跑的邻居", "每日 06:30 · 约 3 公里", "陈屿舟 · 8 栋",
         "兴趣搭伴", "4 人加入", "已完成", "昨天 21:08"),
    ]
    for code, title, subtitle, owner, category, performance, status, updated in helps:
        session.add(HelpRequest(community_id=c["云栖里社区"].id, code=code, title=title, subtitle=subtitle,
                                owner=owner, category=category, performance=performance, status=status,
                                updated_label=updated))

    life_posts = [
        ("SH20250320066", "家门口的春日赏花地图", "图文专题 · 6 个推荐地点", "社区生活编辑部",
         "周末去哪", "2,186 阅读 · 328 收藏", "已发布", "今天 15:20"),
        ("SH20250320065", "云栖里周边早餐店红榜", "探店合集 · 8 家门店", "生活达人 · 林小满",
         "邻里探店", "1,835 阅读 · 92 评论", "已发布", "今天 12:10"),
        ("SH20250320064", "本周生鲜团购清单", "关联 12 个商品 · 周五截单", "禾田生鲜",
         "社区团购", "—", "待审核", "今天 10:36"),
        ("SH20250320063", "带孩子看牙前要准备什么", "健康科普 · 合作机构投稿", "社区卫生服务站",
         "健康生活", "预计触达 2,800 人", "草稿", "今天 09:18"),
        ("SH20250319058", "旧衣物回收点位指南", "便民指南 · 4 个点位", "社区运营 · 李知夏",
         "便民指南", "968 阅读 · 218 收藏", "已发布", "昨天 17:42"),
        ("SH20250318042", "冬季水管防冻小贴士", "季节内容 · 已过时效", "物业服务中心",
         "居家技巧", "3,286 阅读", "已下线", "03-18 14:20"),
    ]
    for code, title, subtitle, owner, category, performance, status, updated in life_posts:
        session.add(LifePost(community_id=c["云栖里社区"].id, code=code, title=title, subtitle=subtitle,
                             owner=owner, category=category, performance=performance, status=status,
                             updated_label=updated))

    notices = [
        ("关于本周四停水维护的通知", "云栖里全体住户", "物业服务中心", "1,283 / 2,106", "已发布", "今天 08:00"),
        ("清明节社区服务安排", "全部社区", "运营中心", "—", "定时发布", "03-22 09:00"),
        ("电梯年度检修计划", "3、5、7 栋", "工程服务部", "652 / 886", "已发布", "昨天 14:30"),
        ("文明养犬温馨提示", "全部社区", "社区居委会", "3,021 / 4,582", "已发布", "03-15 10:00"),
    ]
    for title, scope, publisher, progress, status, published in notices:
        session.add(Notice(community_id=c["云栖里社区"].id, title=title, scope=scope, publisher=publisher,
                           read_progress=progress, status=status, published_label=published))

    tasks = [
        ("停水公告触达提醒", "Push · 站内信", "云栖里住户", "2,086 / 1,283", "已完成", "今天 08:00"),
        ("活动报名成功通知", "站内信 · 短信", "活动报名用户", "112 / 109", "发送中", "自动触发"),
        ("住户认证材料补充提醒", "Push", "认证待补充用户", "28 / 19", "已完成", "昨天 16:00"),
        ("月度社区简报", "Push · 站内信", "全部用户", "—", "草稿", "未发送"),
    ]
    for name, channels, target, delivery, status, sent in tasks:
        session.add(NotificationTask(name=name, channels=channels, target=target, delivery=delivery,
                                     status=status, sent_label=sent))

    repairs = [
        ("BX20250320018", "单元门禁失灵", "赵女士", "3 栋 2 单元", "工程部 · 徐工", "处理中", "剩余 1h 28m"),
        ("BX20250320017", "地库照明损坏", "巡检员 02", "B2 C区", "待指派", "待派单", "已等待 36m"),
        ("BX20250319042", "楼道墙面渗水", "孙先生", "7 栋 18F", "物业 · 吴工", "待验收", "用时 5h 20m"),
        ("BX20250318031", "公区树枝遮挡", "网格员 07", "东门步道", "绿化组", "已完成", "用时 3h 12m"),
    ]
    for no, title, reporter, location, assignee, status, sla in repairs:
        session.add(RepairOrder(community_id=c["云栖里社区"].id, order_no=no, title=title, reporter=reporter,
                                location=location, assignee=assignee, status=status, sla_label=sla))

    feedbacks = [
        ("建议增加晚间广场照明", "匿名用户", "社区建议", "网格员 05", "待回复", "今天 09:18"),
        ("周末装修噪音扰民", "郑先生", "投诉举报", "物业客服", "处理中", "今天 08:42"),
        ("希望增设儿童友好座椅", "徐女士", "设施建议", "社区营造组", "已采纳", "昨天"),
        ("快递柜高峰期容量不足", "顾言", "便民服务", "运营经理", "已回复", "03-17"),
    ]
    for content, submitter, category, assignee, status, created in feedbacks:
        session.add(Feedback(community_id=c["云栖里社区"].id, content=content, submitter=submitter,
                             category=category, assignee=assignee, status=status, created_label=created))

    users = [
        ("业主", "林小满", "138****0921", "业主 · 云栖里", "云栖里社区", "社区居民", "正常", "2 分钟前"),
        ("运营", "李知夏", "186****4420", "运营 · 云栖里", "云栖里社区", "社区运营", "正常", "18 分钟前"),
        ("物业", "徐正", "139****7728", "物业 · 云栖里", "云栖里社区", "工单处理员", "正常", "今天 08:21"),
        ("商户", "陈安", "177****3012", "商户 · 邻里中心", "邻里中心", "认证商户", "已停用", "03-12 19:20"),
    ]
    for account_type, name, phone, identity, community, role_name, status, active in users:
        session.add(PlatformUser(account_type=account_type, name=name, phone=phone, identity=identity,
                                 community_name=community, role_name=role_name, status=status,
                                 last_active_label=active))

    txns = [
        ("TX20250320001", "OR20250319001", "林小满", "支付托管", 12800, "微信支付", "成功", "WX20250320001", "今天 10:08"),
        ("TX20250320002", "OR20250319002", "顾言", "放款", 26000, "平台余额", "成功", "PL20250320002", "今天 09:36"),
        ("TX20250320003", "OR20250319003", "宋知夏", "退款", 9000, "支付宝", "退款中", "AL20250320003", "今天 09:12"),
        ("TX20250320004", "OR20250318004", "莫白", "支付托管", 7500, "微信支付", "成功", "WX20250320004", "昨天 21:10"),
        ("TX20250320005", "OR20250318005", "裴溪", "提现", 36000, "银行卡", "成功", "BK20250320005", "昨天 18:20"),
        ("TX20250320006", "OR20250317006", "刘玉兰", "放款", 6000, "平台余额", "成功", "PL20250320006", "03-17 14:22"),
    ]
    for txn_no, order_no, user, type_, amount, channel, status, channel_no, created in txns:
        session.add(PaymentTransaction(txn_no=txn_no, order_no=order_no, user_name=user, type=type_,
                                       amount_cents=amount, channel=channel, status=status,
                                       channel_txn_no=channel_no, created_label=created))

    withdrawals = [
        ("WD20250320001", "裴溪", 36000, 360, "招商银行 **** 8821", "通过", "待审核", "今天 09:20"),
        ("WD20250320002", "林小满", 12800, 128, "微信零钱 **** 0921", "通过", "打款中", "今天 08:50"),
        ("WD20250320003", "顾言", 52000, 520, "工商银行 **** 3012", "人工复核", "待审核", "昨天 18:40"),
    ]
    for no, user, amount, fee, account, risk, status, created in withdrawals:
        session.add(Withdrawal(withdrawal_no=no, user_name=user, amount_cents=amount, fee_cents=fee,
                               account_masked=account, risk_result=risk, status=status, created_label=created))

    reconciliations = [
        ("微信支付", "2026-11-13", 128600, 128600, 0, 0, "一致", "今天 06:00"),
        ("支付宝", "2026-11-13", 86400, 86250, 150, 1, "有差异", "今天 06:00"),
        ("银行卡", "2026-11-13", 52000, 52000, 0, 0, "一致", "今天 06:00"),
    ]
    for channel, bill_date, channel_amount, platform_amount, diff, count, status, created in reconciliations:
        session.add(Reconciliation(channel=channel, bill_date=bill_date, channel_amount_cents=channel_amount,
                                   platform_amount_cents=platform_amount, diff_cents=diff, diff_count=count,
                                   status=status, created_label=created))

    orders = [
        ("OR20250319001", "九成新儿童平衡车", "顾言", "小树爸爸", "货币", 12800, "已完成", "已放款", "今天 10:08"),
        ("OR20250319002", "实木书桌 120cm", "宋知夏", "7-2-1103", "货币", 26000, "已完成", "已放款", "今天 09:36"),
        ("OR20250319003", "露营折叠椅两把", "莫白", "April", "货币", 9000, "退款中", "退款中", "今天 09:12"),
        ("OR20250318004", "儿童绘本 30 册打包", "裴溪", "辰辰妈妈", "互换", 0, "已完成", "已交割", "昨天 21:10"),
    ]
    for no, title, buyer, seller, trade_type, amount, status, escrow, created in orders:
        session.add(OrderRecord(order_no=no, item_title=title, buyer=buyer, seller=seller,
                                trade_type=trade_type, amount_cents=amount, status=status,
                                escrow_status=escrow, created_label=created))

    disputes = [
        ("DP20250320001", "OR20250319003", "莫白", "April", 9000, "调解中", "商品存在明显使用痕迹，与描述不符", "今天 09:08"),
        ("DP20250319002", "OR20250318004", "裴溪", "辰辰妈妈", 0, "待受理", "互换物品数量不一致", "昨天 20:16"),
        ("DP20250318003", "OR20250317006", "刘玉兰", "宋女士", 6000, "已解决", "验货后达成部分补偿", "03-17 16:40"),
    ]
    for no, order_no, initiator, respondent, amount, status, statement, created in disputes:
        session.add(Dispute(dispute_no=no, order_no=order_no, community_id=c["云栖里社区"].id,
                            initiator=initiator, respondent=respondent, amount_cents=amount,
                            status=status, statement=statement, created_label=created))

    pages = [
        ("工作台", "dashboard", "/dashboard", "总览", "LayoutDashboard", "展示社区核心指标、趋势、待办事项和最新运营动态。"),
        ("社区喇叭", "community-broadcast", "/community-operations/broadcast", "社区运营", "Megaphone", "运营移动版小区喇叭站的播报、话题、提醒及互动内容。"),
        ("社区物品", "community-items", "/community-operations/items", "社区运营", "ShoppingBag", "管理移动版最近热门商品、闲置物品审核及推荐展位。"),
        ("邻里互助", "neighbor-help", "/community-operations/help", "社区运营", "HandHeart", "管理居民求助、邻里响应、撮合履约及互助信用。"),
        ("社区生活", "community-life", "/community-operations/life", "社区运营", "Coffee", "运营移动版生活频道、便民指南、探店与专题推荐内容。"),
        ("公告管理", "notices", "/communication/notices", "触达中心", "Bell", "编辑、定时发布并置顶社区公告。"),
        ("通知任务", "messages", "/communication/notification-tasks", "触达中心", "Activity", "统一管理站内信、短信、Push 和服务通知。"),
        ("社区运维", "community-maintenance", "/community-management/maintenance", "社区管理", "Map", "按行政区划管理全国地市、街道及社区基础信息。"),
        ("社区业主", "community-residents", "/community-management/residents", "社区管理", "UserRound", "维护社区业主、家属、租户及商务人员的身份认证和用户档案。"),
        ("用户管理", "users", "/system/users", "系统管理", "Users", "统一管理居民、物业、商户与运营人员账户。"),
        ("角色权限", "roles", "/system/roles", "系统管理", "ShieldCheck", "管理角色成员，并按菜单页面和页面资源精细配置访问权限。"),
        ("资源管理", "resources", "/system/resources", "系统管理", "Box", "维护系统菜单页面以及页面内可授权、可操作的资源。"),
        ("参数配置", "parameters", "/system/parameters", "系统管理", "SlidersHorizontal", "集中配置业务规则、字典、开关和系统参数。"),
        ("资金看板", "finance-overview", "/finance/overview", "资金与治理", "Wallet", "监控平台托管资金、放款、退款与提现风险。"),
        ("资金流水", "finance-transactions", "/finance/transactions", "资金与治理", "ReceiptText", "按订单、用户、时间与类型检索全部资金流水。"),
        ("提现管理", "finance-withdrawals", "/finance/withdrawals", "资金与治理", "Banknote", "审核提现申请、跟踪打款状态并处理失败。"),
        ("对账管理", "finance-reconciliations", "/finance/reconciliations", "资金与治理", "Scale", "按渠道与账单日核对平台流水与渠道账单。"),
        ("订单查询", "finance-orders", "/finance/orders", "资金与治理", "ClipboardList", "查询全量订单、托管状态与双方确认记录。"),
        ("纠纷调解", "disputes", "/governance/disputes", "资金与治理", "Gavel", "查看双方陈述与证据，出具处理结论。"),
        ("审计日志", "audit-logs", "/system/audit-logs", "系统管理", "FileClock", "查询关键操作的操作人、时间、IP、前后快照与追踪号。"),
        ("报表导出中心", "exports", "/analytics/exports", "系统管理", "Download", "创建、跟踪和下载异步导出任务。"),
    ]
    page_rows: dict[str, SysPage] = {}
    for sort, (name, code, route, region, icon, desc) in enumerate(pages):
        page = SysPage(name=name, code=code, route=route, region=region, icon=icon, description=desc, sort=sort)
        session.add(page)
        page_rows[code] = page
    await session.flush()

    for page_code, page in page_rows.items():
        resources = [
            (f"{page.name}搜索框", "输入框", f"{page_code}.search", "system:resource:view"),
            (f"新增{page.name}按钮", "按钮", f"{page_code}.create", f"{page_code}:create"),
            ("状态筛选", "下拉列表", f"{page_code}.status.filter", f"{page_code}:view"),
            ("行操作菜单", "弹出菜单", f"{page_code}.row.actions", f"{page_code}:update"),
        ]
        for name, type_, code, permission in resources:
            session.add(PageResource(page_id=page.id, name=name, type=type_, code=code,
                                     permission_code=permission))

    def add_key(label: str, code: str, parent: ParameterKey | None, kind: str = "KEY") -> ParameterKey:
        key = ParameterKey(label=label, code=code, kind=kind, parent=parent)
        session.add(key)
        return key

    content = add_key("内容与安全", "content", None, "GROUP")
    review = add_key("内容审核规则", "content.review", content, "GROUP")
    mode = add_key("审核模式", "content.review.mode", review)
    sensitive = add_key("敏感词等级", "content.sensitive.level", review)
    add_key("发布频率限制", "content.publish.limit", content)
    activity = add_key("活动与报名", "activity", None, "GROUP")
    signup = add_key("报名规则", "activity.signup", activity, "GROUP")
    add_key("报名截止时间", "activity.signup.close_hours", signup)
    add_key("报名人数限制", "activity.signup.capacity", signup)
    add_key("签到方式", "activity.checkin.method", activity)
    neighborhood = add_key("邻里服务", "neighborhood", None, "GROUP")
    add_key("互助响应有效期", "help.response.expire_hours", neighborhood)
    add_key("报修超时时长", "repair.order.timeout", neighborhood)
    add_key("市集服务费率", "market.service.fee", neighborhood)
    system = add_key("系统基础配置", "system", None, "GROUP")
    add_key("新用户默认角色", "user.default_role", system)
    add_key("附件上传限制", "upload.file.max_size", system)
    add_key("消息保留周期", "message.retention.days", system)
    finance = add_key("资金规则", "finance", None, "GROUP")
    add_key("提现复核阈值", "finance.withdrawal.review_threshold", finance)
    add_key("自动放款时长", "finance.auto_release.hours", finance)
    add_key("对账差异阈值", "finance.reconcile.diff_alert_threshold", finance)
    await session.flush()
    for key, items in {
        mode: [("社区动态", "先审后发", "普通居民发布动态时进入人工审核队列", "启用"),
               ("动态评论", "发布后审", "评论实时发布，命中风险规则后转人工复核", "启用"),
               ("认证机构内容", "免审核", "物业、居委会及认证服务机构内容直接发布", "启用")],
        sensitive: [("政治敏感词", "严格", "命中后立即拦截并生成高风险工单", "启用"),
                    ("广告营销词", "标准", "结合发布频率与账号信用综合判定", "启用")],
        signup: [("普通社区活动", "2 小时", "活动开始前停止用户报名与取消", "启用"),
                 ("志愿服务活动", "12 小时", "预留志愿者排班及通知时间", "启用")],
        neighborhood: [("普通邻里求助", "24 小时", "超时未响应的求助自动关闭", "启用"),
                       ("紧急求助", "2 小时", "超时自动提醒社区网格员介入", "启用")],
        system: [("未认证用户", "访客", "仅可浏览公开内容和提交认证申请", "启用"),
                 ("住户认证通过", "社区居民", "自动授予当前社区居民基础权限", "启用")],
        finance: [("提现双人复核", "500000", "单笔提现超过该金额需双人复核（分）", "启用"),
                  ("自动放款", "72", "买家确认后超时自动放款（小时）", "启用")],
    }.items():
        for name, value, desc, status in items:
            session.add(ParameterItem(parameter_key_id=key.id, name=name, value=value,
                                      description=desc, status=status))

    session.add_all([
        AuditLog(actor_id=admin.id, actor_name="夏木", action="resident.certification.approve",
                 resource_type="resident", resource_id="3", ip="10.0.0.8", trace_id="b7c2f1a9e8d74563",
                 created_label="今天 09:12", result="SUCCESS"),
        AuditLog(actor_id=admin.id, actor_name="夏木", action="broadcast.review",
                 resource_type="broadcast", resource_id="LB20250320027", ip="10.0.0.8",
                 trace_id="b7c2f1a9e8d74564", created_label="今天 10:04", result="SUCCESS"),
        AuditLog(actor_id=admin.id, actor_name="夏木", action="finance.withdrawal.review",
                 resource_type="withdrawal", resource_id="WD20250320001", ip="10.0.0.8",
                 trace_id="b7c2f1a9e8d74565", created_label="今天 09:36", result="SUCCESS"),
    ])

    session.add(DashboardSnapshot(
        community_id=c["云栖里社区"].id,
        metrics={"users": 12680, "active": 3428, "todos": 43, "satisfaction": 96.8,
                 "usersChange": "+8.2%", "usersDetail": "本月新增 326",
                 "activeChange": "+12.4%", "activeDetail": "活跃率 27.0%",
                 "todoChange": "需关注", "todoDetail": "6 项即将超时",
                 "satisfactionChange": "+1.6%", "satisfactionDetail": "基于 1,284 份评价"},
        trend={"labels": ["03/14", "03/15", "03/16", "03/17", "03/18", "03/19", "今天"],
               "active": [68, 52, 73, 61, 84, 78, 92],
               "interaction": [43, 33, 47, 39, 54, 50, 59]},
        distribution={"total": 4582, "owner": 2864, "tenant": 1214, "other": 504,
                      "ownerPct": "62.5%", "tenantPct": "26.5%", "otherPct": "11.0%"},
        activities=[
            {"mark": "李", "tone": "lavender", "name": "李知夏", "action": "发布了社区活动", "target": "春分邻里市集", "time": "8 分钟前"},
            {"mark": "沈", "tone": "mint", "name": "沈嘉禾", "action": "提交了住户认证", "target": "云栖里 8-1-902", "time": "12 分钟前"},
            {"mark": "徐", "tone": "peach", "name": "徐正", "action": "完成了报修工单", "target": "东门路灯检修", "time": "26 分钟前"},
            {"mark": "物", "tone": "blue", "name": "物业服务中心", "action": "发布了公告", "target": "本周四停水维护通知", "time": "1 小时前"},
        ],
    ))

    await session.commit()
