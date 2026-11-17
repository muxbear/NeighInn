/**
 * 统一服务端契约适配层（web/backend → 既有管理端页面展示体系）。
 *
 * 背景：服务端使用英文状态机编码 + Unix 毫秒时间戳 + 金额整数分；
 * 既有页面按中文标签/相对时间展示。本层在 API 边界统一转换，
 * 页面逐步重构后可逐模块退役。
 */

// ---------------------------------------------------------------- 状态码 → 中文标签

export const STATUS_LABELS: Record<string, string> = {
  // 物品
  DRAFT: '草稿', AUDITING: '质检中', PENDING_REVIEW: '待审核', ON_SALE: '在售',
  RESERVED: '已预约', SOLD: '已售出', GIFTED: '已赠出', OFF_SHELF: '已下架',
  REJECTED: '已驳回', AI_REJECTED: '质检驳回', EXPIRED: '已过期',
  // 内容（喇叭/生活）
  PUBLISHED: '已发布', OFFLINE: '已下架', SCHEDULED: '定时发布',
  // 互助
  OPEN: '待响应', MATCHING: '匹配中', IN_PROGRESS: '进行中', COMPLETED: '已完成', CLOSED: '已关闭',
  // 提现
  PENDING: '待审核', APPROVED: '审核通过', PAYING: '打款中', PAID: '已到账',
  FAILED: '失败', CLOSED_W: '已关闭',
  // 流水
  SUCCESS: '成功', PROCESSING: '处理中',
  // 托管
  UNPAID: '未支付', ESCROWED: '托管中', PENDING_RELEASE: '待放款',
  RELEASED: '已放款', REFUNDING: '退款中', REFUNDED: '已退款', FROZEN: '已冻结',
  // 订单
  PENDING_PAYMENT: '待付款', APPLIED: '已申请', PENDING_CONFIRM: '待对方确认',
  CONFIRMED: '已确认', APPOINTMENT: '已预约', INSPECTING: '验货中',
  CANCELLED: '已取消', DISPUTING: '纠纷中',
  // 纠纷
  OPEN_D: '待受理', MEDIATING: '调解中', RESOLVED: '已解决',
  // 认证
  VERIFIED: '已认证', UNVERIFIED: '未认证', SUPPLEMENT: '待补充', REVOKED: '已撤销',
  // 社区
  OPERATING: '正常运营', PREPARING: '筹备中', SUSPENDED: '已停用',
  // 用户
  ACTIVE: '正常',
  // 公告/通知任务
  WITHDRAWN: '已撤回', PENDING_APPROVAL: '待审批', SENDING: '发送中',
  PARTIAL_FAILED: '部分失败',
  // 举报/反馈
  DISMISSED: '已驳回', REPLIED: '已回复',
}

export function mapStatus(code: string | undefined | null): string {
  if (!code) return '—'
  return STATUS_LABELS[code] ?? code
}

export const TRADE_TYPE_LABELS: Record<string, string> = {
  MONETARY: '货币', FREE_GIFT: '免费', BARTER: '互换',
}

export function mapTradeType(code: string | undefined | null): string {
  if (!code) return '—'
  return TRADE_TYPE_LABELS[code] ?? code
}

export const TXN_TYPE_LABELS: Record<string, string> = {
  ESCROW: '支付托管', RELEASE: '放款', REFUND: '退款', WITHDRAW: '提现',
  ADJUSTMENT: '调账', FEE: '服务费',
}

export function mapTxnType(code: string | undefined | null): string {
  if (!code) return '—'
  return TXN_TYPE_LABELS[code] ?? code
}

export const CHANNEL_LABELS: Record<string, string> = {
  IN_APP: '站内信', SMS: '短信', PUSH: 'Push', SERVICE: '服务通知',
  WECHAT: '微信支付', ALIPAY: '支付宝',
}

export function mapChannels(value: string | undefined | null): string {
  if (!value) return '—'
  return value.split(',').map((item) => CHANNEL_LABELS[item.trim()] ?? item.trim()).join(' · ')
}

export const TARGET_LABELS: Record<string, string> = {
  ALL: '全部用户', COMMUNITY: '指定社区', ROLE: '指定角色', TAG: '指定标签', IMPORTED: '导入名单',
}

// ---------------------------------------------------------------- 时间与金额

export function fmtRelative(ms: number | string | undefined | null): string {
  const value = Number(ms || 0)
  if (!value) return '—'
  const delta = Date.now() - value
  const minutes = Math.floor(delta / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return new Date(value).toLocaleDateString('zh-CN')
}

export function fmtDateTime(ms: number | string | undefined | null): string {
  const value = Number(ms || 0)
  if (!value) return '—'
  const d = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fmtMoney(cents: number | undefined | null): string {
  if (cents === undefined || cents === null) return '—'
  return `¥${(cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
}

// ---------------------------------------------------------------- 行归一化（服务端 → 页面）

export function normalizeOperationRow(module: string, row: any): any {
  const stats = row.stats || {}
  const displayStatus = module === 'broadcast'
    ? (row.effectiveStatus ?? row.status)
    : row.status
  return {
    ...row,
    owner: row.owner ?? row.seller ?? row.author ?? row.requester ?? '—',
    performance: row.performance
      ?? (stats.views !== undefined ? `${stats.views} 浏览 · ${stats.likes ?? 0} 赞` : '—'),
    storedStatus: row.status,
    statusCode: displayStatus,
    status: mapStatus(displayStatus),
    updatedAt: fmtRelative(row.updatedAt ?? row.createdAt),
  }
}

// 住户档案的账号状态与资金托管状态语义不同：FROZEN 展示为「已停用」。
const RESIDENT_STATUS_LABELS: Record<string, string> = {
  ACTIVE: '正常', FROZEN: '已停用', LEFT: '已离开',
}

export function normalizeResident(row: any): any {
  return {
    ...row,
    certification: mapStatus(row.certification ?? row.certificationStatus),
    certificationStatus: row.certificationStatus ?? row.certification,
    realnameStatusLabel: mapStatus(row.realnameStatus),
    status: RESIDENT_STATUS_LABELS[row.status] ?? mapStatus(row.status),
    joinedAt: row.joinedAt || '—',
  }
}

export function normalizeTxn(row: any): any {
  return {
    ...row,
    type: mapTxnType(row.type),
    status: mapStatus(row.status),
    amount: row.amount ?? fmtMoney(row.amountCents),
    createdAt: fmtDateTime(row.createdAt),
  }
}

export function normalizeWithdrawal(row: any): any {
  return {
    ...row,
    status: mapStatus(row.status),
    createdAt: fmtDateTime(row.createdAt),
  }
}

export function normalizeFinanceOrder(row: any): any {
  return {
    ...row,
    tradeType: mapTradeType(row.tradeType),
    status: mapStatus(row.status),
    escrowStatus: mapStatus(row.escrowStatus),
    createdLabel: fmtDateTime(row.createdAt),
  }
}

export function normalizeDispute(row: any): any {
  const disputeStatus: Record<string, string> = {
    OPEN: '待受理', MEDIATING: '调解中', PENDING_REVIEW: '待复核',
    RESOLVED: '已解决', CLOSED: '已关闭',
  }
  return {
    ...row,
    status: disputeStatus[row.status] ?? mapStatus(row.status),
    createdAt: fmtDateTime(row.createdAt),
  }
}

export function normalizeNotice(row: any): any {
  return {
    ...row,
    status: mapStatus(row.status),
    publishedAt: row.status === 'PUBLISHED' || row.publishedAt ? fmtRelative(row.publishedAt) : '—',
    readProgress: row.readProgress ?? '—',
  }
}

export function normalizeTask(row: any): any {
  return {
    ...row,
    channels: mapChannels(row.channels),
    target: TARGET_LABELS[row.targetType] ?? row.target ?? '—',
    status: mapStatus(row.status),
    sentAt: fmtRelative(row.sentAt),
  }
}

export function normalizePlatformUser(row: any): any {
  return {
    ...row,
    accountType: '社区居民',
    name: row.nickname ?? row.name ?? '—',
    identity: row.identityType ? `${row.identityType} · ${row.certificationStatus ? mapStatus(row.certificationStatus) : ''}` : '—',
    roleName: row.creditLevel ?? '普通用户',
    status: mapStatus(row.status),
    lastActive: fmtRelative(row.lastActiveAt ?? row.registeredAt),
  }
}

export function normalizeAudit(row: any): any {
  return { ...row, createdLabel: fmtDateTime(row.createdAt) }
}

export function normalizeCommunity(row: any): any {
  return { ...row, status: mapStatus(row.status), statusCode: row.status }
}

export function normalizeCertification(row: any): any {
  return {
    ...row,
    status: mapStatus(row.status),
    statusCode: row.status,
    submittedAt: fmtRelative(row.submittedAt),
    typeLabel: row.typeLabel ?? (row.type === 'REALNAME' ? '实名认证' : '住户认证'),
    userName: row.user?.nickname ?? '—',
    userPhone: row.user?.phone ?? '—',
    realnameStatus: row.user?.realnameStatus ?? '',
    communityName: row.community?.name ?? '—',
  }
}

export function normalizeTodo(row: any): any {
  return {
    key: row.key ?? row.id ?? row.title,
    title: row.title ?? '待办事项',
    description: row.description ?? row.sub ?? '',
    count: Number(row.count || 0),
    route: row.route ?? '/dashboard',
    permission: row.permission ?? '',
    icon: row.icon ?? 'ClipboardCheck',
    color: row.color ?? 'blue',
    oldestPendingAt: Number(row.oldestPendingAt || 0),
    latestCertId: row.latestCertId ?? '',
    breakdown: row.breakdown ?? {},
  }
}

export function normalizeReport(row: any): any {
  return {
    ...row,
    status: mapStatus(row.status),
    createdAt: fmtRelative(row.createdAt),
  }
}

export function normalizeFeedback(row: any): any {
  return {
    ...row,
    status: mapStatus(row.status),
    createdAt: fmtRelative(row.createdAt),
  }
}

// ---------------------------------------------------------------- 工作台

export function normalizeDashboard(data: any): any {
  const metrics = data?.metrics || {}
  return {
    ...data,
    metrics: {
      users: metrics.users ?? 0,
      active: metrics.todayNewUsers ?? 0,
      todos: (data?.todos || []).reduce((sum: number, item: any) => sum + (item.count || 0), 0),
      satisfaction: metrics.satisfaction ?? 96.8,
      gmvCents: metrics.gmvCents ?? 0,
      usersChange: metrics.todayNewUsers ? `今日新增 ${metrics.todayNewUsers}` : '平稳',
      activeChange: '真实统计',
      todoChange: '需关注',
      satisfactionChange: '',
      usersDetail: '平台注册用户',
      activeDetail: '今日新增注册',
      todoDetail: '各业务待办合计',
      satisfactionDetail: '待接入评价口径',
    },
    todos: (data?.todos || []).map(normalizeTodo),
  }
}

export function normalizeTrend(data: any): any {
  return {
    labels: data?.labels || [],
    active: data?.active || [],
    interaction: data?.interaction ?? data?.published ?? [],
  }
}

export function normalizeActivity(row: any): any {
  return {
    time: fmtRelative(row.time),
    mark: (row.actor || '系')[0],
    name: row.actor || '系统',
    action: row.action,
    target: row.target || '',
    tone: 'violet',
  }
}
