import {
  Activity,
  Banknote,
  Bell,
  Box,
  ClipboardList,
  Coffee,
  Download,
  FileClock,
  Flag,
  Gavel,
  HandHeart,
  LayoutDashboard,
  Map,
  Megaphone,
  ReceiptText,
  Scale,
  ShieldCheck,
  ShoppingBag,
  SlidersHorizontal,
  UserRound,
  Users,
  Wallet,
} from 'lucide-vue-next'

export type NavItem = {
  id: string
  label: string
  route: string
  icon: any
  permission?: string
  /** 静态徽标（仅用于有稳定业务口径的模块，保留兼容）。 */
  badge?: number
  /** 动态徽标：对应 /dashboard/todos 的待办 key，数字随真实待办刷新。 */
  badgeKey?: string
}

export type NavGroup = {
  label: string
  items: NavItem[]
}

export const figmaNavGroups: NavGroup[] = [
  {
    label: '总览',
    items: [{ id: 'dashboard', label: '工作台', route: '/dashboard', icon: LayoutDashboard, permission: 'dashboard:view' }],
  },
  {
    label: '社区运营',
    items: [
      { id: 'community-broadcast', label: '社区喇叭', route: '/community-operations/broadcast', icon: Megaphone, permission: 'community:broadcast:view' },
      { id: 'community-items', label: '社区物品', route: '/community-operations/items', icon: ShoppingBag, permission: 'community:item:view', badgeKey: 'item' },
      { id: 'neighbor-help', label: '邻里互助', route: '/community-operations/help', icon: HandHeart, permission: 'community:help:view', badgeKey: 'help' },
      { id: 'community-life', label: '社区生活', route: '/community-operations/life', icon: Coffee, permission: 'community:life:view' },
    ],
  },
  {
    label: '触达中心',
    items: [
      { id: 'notices', label: '公告管理', route: '/communication/notices', icon: Bell, permission: 'communication:notice:view' },
      { id: 'messages', label: '通知任务', route: '/communication/notification-tasks', icon: Activity, permission: 'communication:task:view' },
    ],
  },
  {
    label: '社区管理',
    items: [
      { id: 'community-maintenance', label: '社区运维', route: '/community-management/maintenance', icon: Map, permission: 'community:maintenance:view' },
      { id: 'community-residents', label: '社区业主', route: '/community-management/residents', icon: UserRound, permission: 'community:resident:view' },
      { id: 'community-verification', label: '住户认证', route: '/governance/verification', icon: ShieldCheck, permission: 'community:resident:audit' },
    ],
  },
  {
    label: '资金与治理',
    items: [
      { id: 'finance-overview', label: '资金看板', route: '/finance/overview', icon: Wallet, permission: 'finance:overview:view' },
      { id: 'finance-transactions', label: '资金流水', route: '/finance/transactions', icon: ReceiptText, permission: 'finance:transaction:view' },
      { id: 'finance-withdrawals', label: '提现管理', route: '/finance/withdrawals', icon: Banknote, permission: 'finance:withdrawal:view' },
      { id: 'finance-reconciliations', label: '对账管理', route: '/finance/reconciliations', icon: Scale, permission: 'finance:reconcile:view' },
      { id: 'finance-orders', label: '订单查询', route: '/finance/orders', icon: ClipboardList, permission: 'finance:order:view' },
      { id: 'disputes', label: '纠纷调解', route: '/governance/disputes', icon: Gavel, permission: 'governance:dispute:view' },
      { id: 'reports', label: '举报处理', route: '/governance/reports', icon: Flag, permission: 'governance:report:view' },
    ],
  },
  {
    label: '系统管理',
    items: [
      { id: 'users', label: '用户管理', route: '/system/users', icon: Users, permission: 'system:user:view' },
      { id: 'roles', label: '角色权限', route: '/system/roles', icon: ShieldCheck, permission: 'system:role:view' },
      { id: 'resources', label: '资源管理', route: '/system/resources', icon: Box, permission: 'system:resource:view' },
      { id: 'parameters', label: '参数配置', route: '/system/parameters', icon: SlidersHorizontal, permission: 'system:parameter:view' },
      { id: 'audit-logs', label: '审计日志', route: '/system/audit-logs', icon: FileClock, permission: 'system:audit:view' },
      { id: 'exports', label: '报表导出', route: '/analytics/exports', icon: Download, permission: 'reporting:export:view' },
    ],
  },
]
