/**
 * 本地 Mock 服务：与真实接口保持同一路径、同一响应形状。
 * 关闭方式：config/env.ts -> env.mock = false。
 */
import type {
  AppNotification,
  AppSettings,
  AuditProgress,
  Broadcast,
  ChatMessage,
  CommunityBinding,
  Conversation,
  CreateOrderResult,
  FriendRequest,
  HomeBundle,
  Item,
  ItemComment,
  LifeComment,
  LifePost,
  LoginResult,
  Order,
  PageResult,
  RegionNode,
  ReviewPayload,
  ServicePost,
  UserProfile,
  WalletTransaction,
} from '../models'
import {
  APP_CONFIG,
  AUDIT_REPORT,
  BROADCASTS,
  CHAT_MESSAGES,
  COMMUNITIES,
  CONVERSATIONS,
  CURRENT_COMMUNITY,
  DEFAULT_SETTINGS,
  FRIEND_REQUESTS,
  FRIENDS,
  HOT_KEYWORDS,
  ITEM_COMMENTS,
  ITEMS,
  LIFE_COMMENTS,
  LIFE_POSTS,
  MY_ITEMS,
  MY_SELLER,
  NEARBY_COMMUNITIES,
  NOTIFICATIONS,
  ORDERS,
  REGION_TREE,
  SEARCH_HISTORY,
  SELLERS,
  SERVICE_POSTS,
  USER,
  WALLET,
  WALLET_TRANSACTIONS,
  createAuditProgress,
} from '../config/mock/data'
import type { RegionTreeNode } from '../config/mock/data'
import { env } from '../config/env'
import { ApiError } from './errors'
import { formatDateTime } from '../utils/formatter'

export interface MockRequestOptions {
  url: string
  method: string
  data?: Record<string, any>
  headers?: Record<string, string>
}

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

const state = {
  items: clone<Item[]>([...ITEMS, ...MY_ITEMS]),
  lifePosts: clone<LifePost[]>(LIFE_POSTS),
  servicePosts: clone<ServicePost[]>(SERVICE_POSTS),
  broadcasts: clone<Broadcast[]>(BROADCASTS),
  notifications: clone<AppNotification[]>(NOTIFICATIONS),
  orders: clone<Order[]>(ORDERS),
  conversations: clone<Conversation[]>(CONVERSATIONS),
  messages: clone<Record<string, ChatMessage[]>>(CHAT_MESSAGES),
  friends: clone(FRIENDS),
  friendRequests: clone<FriendRequest[]>(FRIEND_REQUESTS),
  communities: clone<CommunityBinding[]>(COMMUNITIES),
  nearbyCommunities: clone<CommunityBinding[]>(NEARBY_COMMUNITIES),
  user: clone<UserProfile>(USER),
  wallet: clone(WALLET),
  transactions: clone<WalletTransaction[]>(WALLET_TRANSACTIONS),
  settings: clone<AppSettings>(DEFAULT_SETTINGS),
  itemComments: clone<Record<string, ItemComment[]>>(ITEM_COMMENTS),
  lifeComments: clone<Record<string, LifeComment[]>>(LIFE_COMMENTS),
  auditTicks: {} as Record<string, number>,
  searchHistory: [...SEARCH_HISTORY],
  viewHistory: [] as string[],
  favoriteIds: new Set<string>(ITEMS.filter((item) => item.favorite).map((item) => item.id)),
}

const DEFAULT_USER = clone<UserProfile>(USER)
// Mock 中视为已注册的手机号；其余手机号走注册入口创建新账号。
const registeredPhones = new Set<string>(['13812345628', '13800005628'])

function createMockNewUser(phone: string): UserProfile {
  return {
    id: `mock-user-${phone.slice(-4)}`,
    nickname: `邻居${phone.slice(-4)}`,
    phone: `${phone.slice(0, 3)}****${phone.slice(-4)}`,
    email: '',
    address: '',
    bio: '',
    avatarPreset: 'avatar-person-1',
    avatarDataUrl: '',
    showBio: true,
    shareAddressAfterOrder: false,
    verified: false,
    realnameVerified: false,
    ownerVerified: false,
    realnameStatus: 'UNVERIFIED',
    ownerStatus: 'UNVERIFIED',
    creditScore: 100,
    creditLevel: '良好',
    dealCount: 0,
    communityName: '',
    joinedDays: 0,
    authStatus: 'LOGGED_IN_UNVERIFIED',
    onboardingStatus: 'NEW',
    intentCommunityId: '',
    intentCommunityName: '',
  }
}

function fail(code: number, message: string): never {
  throw new ApiError(code, message)
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function parseQuery(url: string): Record<string, string> {
  const result: Record<string, string> = {}
  const index = url.indexOf('?')
  if (index < 0) return result
  const query = url.slice(index + 1)
  for (const pair of query.split('&')) {
    if (!pair) continue
    const [rawKey, rawValue = ''] = pair.split('=')
    try {
      result[decodeURIComponent(rawKey)] = decodeURIComponent(rawValue)
    } catch {
      result[rawKey] = rawValue
    }
  }
  return result
}

function pageResult<T>(list: T[], query: Record<string, string>): PageResult<T> {
  const page = Math.max(1, Number.parseInt(query.page ?? '1', 10) || 1)
  const pageSize = Math.min(50, Math.max(1, Number.parseInt(query.pageSize ?? '20', 10) || 20))
  const start = (page - 1) * pageSize
  const slice = list.slice(start, start + pageSize)
  return {
    list: slice,
    page,
    pageSize,
    total: list.length,
    hasMore: start + slice.length < list.length,
  }
}

function toRegionNode(node: RegionTreeNode): RegionNode {
  return { id: node.id, name: node.name, level: node.level, code: node.code }
}

function regionChildren(parentId: string): RegionNode[] {
  if (!parentId) return REGION_TREE.map(toRegionNode)
  const stack: RegionTreeNode[] = [...REGION_TREE]
  while (stack.length) {
    const node = stack.pop() as RegionTreeNode
    if (node.id === parentId) return (node.children ?? []).map(toRegionNode)
    if (node.children) stack.push(...node.children)
  }
  return []
}

function findItem(id: string): Item {
  const item = state.items.find((entry) => entry.id === id)
  if (!item) fail(40001, '物品不存在或已下架')
  return item
}

function findOrder(id: string): Order {
  const order = state.orders.find((entry) => entry.id === id)
  if (!order) fail(40001, '订单不存在')
  return order
}

function mySeller() {
  return {
    ...MY_SELLER,
    name: state.user.nickname,
    avatar: state.user.avatarPreset ? `/static/avatars/${state.user.avatarPreset}.svg` : state.user.avatarDataUrl,
  }
}

function unreadNotificationCount(): number {
  return state.notifications.filter((item) => !item.read).length
}

function unreadConversationCount(): number {
  return state.conversations.reduce((sum, item) => sum + item.unread, 0)
}

function stamp(): string {
  const date = new Date()
  const pad = (value: number) => (value < 10 ? `0${value}` : `${value}`)
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function parseDistanceMeters(text: string): number {
  const value = Number.parseFloat(String(text).replace(/[^\d.]/g, '')) || 0
  return String(text).includes('km') ? value * 1000 : value
}

function travelByMeters(meters: number): string {
  return `${Math.max(1, Math.round(meters / 72))}分钟`
}

function filterItems(query: Record<string, string>, all = false): Item[] {
  const keyword = (query.keyword ?? '').trim()
  const category = (query.category ?? '').trim()
  const type = (query.type ?? '').trim()
  const zone = (query.zone ?? '').trim()
  let list = state.items.filter((item) => all || item.status === 'ON_SALE')
  if (!all) list = list.filter((item) => !item.id.startsWith('mi'))

  if (zone === 'gift') list = list.filter((item) => item.type === '免费')
  if (zone === 'swap') list = list.filter((item) => item.type === '互换')
  if (zone === 'sale') list = list.filter((item) => item.type === '出售')
  if (type) list = list.filter((item) => item.type === type)
  if (category && category !== '全部') list = list.filter((item) => item.category === category)
  if (keyword) {
    const lower = keyword.toLowerCase()
    const chars = Array.from(lower)
    list = list.filter((item) => {
      const text = `${item.title} ${item.description ?? ''} ${item.category ?? ''}`.toLowerCase()
      return text.includes(lower) || chars.every((char) => text.includes(char))
    })
  }

  const sort = query.sort ?? '最新发布'
  if (sort === '价格从低到高') {
    list = [...list].sort((a, b) => Number(a.price) - Number(b.price))
  } else if (sort === '离我最近') {
    list = [...list].sort((a, b) => parseDistanceMeters(a.distance) - parseDistanceMeters(b.distance))
  } else {
    list = [...list].sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
  }
  return list
}

function buildHome(): HomeBundle {
  const onSale = state.items.filter((item) => item.status === 'ON_SALE' && !item.id.startsWith('mi'))
  const help = state.servicePosts.filter((item) => item.kind === '求助').slice(0, 5)
  const offer = state.servicePosts.filter((item) => item.kind === '提供').slice(0, 5)
  return {
    community: { ...CURRENT_COMMUNITY, itemCount: onSale.length, serviceCount: state.servicePosts.length },
    zones: [
      { key: 'gift', name: '物品赠与', count: onSale.filter((item) => item.type === '免费').length },
      { key: 'swap', name: '物品交换', count: onSale.filter((item) => item.type === '互换').length },
      { key: 'sale', name: '闲置赚米', count: onSale.filter((item) => item.type === '出售').length },
      { key: 'service', name: '邻里互助', count: state.servicePosts.length },
    ],
    broadcasts: clone(state.broadcasts),
    hotItems: clone(onSale.slice(0, 10)),
    serviceHelp: clone(help),
    serviceOffer: clone(offer),
    lifePosts: clone(state.lifePosts
      .filter((post) => !post.status || post.status === 'PUBLISHED')
      .slice(0, 10)),
    notificationUnread: unreadNotificationCount(),
  }
}

function createOrder(body: Record<string, any>): CreateOrderResult {
  const item = findItem(String(body.itemId ?? ''))
  if (body.tradeType && body.tradeType !== item.type) fail(40001, '交易方式与物品不一致')
  if (item.status === 'RESERVED') fail(40901, '物品已被预约，看看其他好物吧')

  const isMonetary = item.type === '出售'
  const now = Date.now()
  const orderNo = `NI${now}`
  const amount = isMonetary ? Number(item.price) : 0
  const status: Order['status'] = isMonetary ? 'PENDING_PAYMENT' : 'PENDING_CONFIRM'
  const statusText = isMonetary ? '待支付' : '等待对方确认'
  const offeredItems = Array.isArray(body.offeredItemIds)
    ? body.offeredItemIds
        .map((id: string) => state.items.find((entry) => entry.id === id))
        .filter(Boolean)
    : undefined

  const order: Order = {
    id: `o-${now}`,
    orderNo,
    tradeType: item.type,
    tradeTypeCode: isMonetary ? 'MONETARY' : item.type === '免费' ? 'FREE_GIFT' : 'BARTER',
    status,
    statusText,
    item: clone(item),
    offeredItems: offeredItems ? clone(offeredItems as Item[]) : undefined,
    amount,
    buyer: mySeller(),
    seller: item.seller ?? mySeller(),
    role: 'buyer',
    createdAt: now,
    createdAtText: formatDateTime(now),
    timeline: [
      { key: 'created', title: '订单已创建', time: stamp(), done: true },
      isMonetary
        ? { key: 'paid', title: '等待付款至平台托管', done: false, active: true }
        : { key: 'confirm', title: '等待对方确认', done: false, active: true },
      { key: 'meet', title: '见面交割', done: false },
      { key: 'done', title: '完成', done: false },
    ],
    canPay: isMonetary,
    canCancel: true,
  }
  state.orders.unshift(order)
  return {
    orderId: order.id,
    orderNo,
    amount,
    expireAt: now + APP_CONFIG.payTimeoutMinutes * 60 * 1000,
  }
}

function prepay(body: Record<string, any>): Record<string, any> {
  const order = findOrder(String(body.orderId ?? ''))
  if (order.status === 'PENDING_PAYMENT' || order.status === 'ESCROWED') {
    if (order.status === 'PENDING_PAYMENT') {
      order.status = 'ESCROWED'
      order.statusText = '待见面验货'
      order.canPay = false
      order.canAppointment = true
      order.canInspect = true
      order.canDispute = true
      order.timeline = order.timeline.map((step) =>
        step.key === 'paid'
          ? { ...step, title: '付款至平台托管', time: stamp(), done: true, active: false }
          : step,
      )
      order.item.status = 'RESERVED'
      const item = state.items.find((entry) => entry.id === order.item.id)
      if (item) item.status = 'RESERVED'
      state.wallet.escrow += order.amount
      state.wallet.balance -= order.amount
    }
    return {
      orderNo: order.orderNo,
      orderId: order.id,
      payParams: { provider: body.method ?? 'wechat', package: 'mock-prepay-package' },
      expireAt: Date.now() + APP_CONFIG.payTimeoutMinutes * 60 * 1000,
    }
  }
  fail(40001, '当前订单状态不可支付')
}

function completeOrder(order: Order): void {
  order.status = 'COMPLETED'
  order.statusText = '已完成'
  order.canAppointment = false
  order.canInspect = false
  order.canCancel = false
  order.canDispute = false
  order.canReview = true
  order.reviewable = true
  order.timeline = order.timeline.map((step) => ({ ...step, done: true, active: false }))
  if (order.tradeType === '出售') {
    state.wallet.escrow = Math.max(0, state.wallet.escrow - order.amount)
    state.wallet.balance += order.amount
    state.transactions.unshift({
      id: `w-${Date.now()}`,
      title: `担保交易放款 · ${order.item.title}`,
      amount: order.amount,
      direction: 'in',
      time: stamp(),
      icon: 'wallet',
    })
  }
  const item = state.items.find((entry) => entry.id === order.item.id)
  if (item) item.status = 'SOLD'
}

async function route(
  path: string,
  method: string,
  query: Record<string, string>,
  body: Record<string, any>,
): Promise<any> {
  const segments = path.split('/').filter(Boolean)

  // ---------------- 认证 ----------------
  if (path === '/auth/sms-code' && method === 'POST') {
    if (!/^1[3-9]\d{9}$/.test(String(body.phone ?? ''))) fail(40001, '请输入正确的手机号')
    return { cooldown: 60, mockCode: '123456' }
  }
  if (path === '/auth/login/sms' && method === 'POST') {
    const phone = String(body.phone ?? '')
    if (!/^1[3-9]\d{9}$/.test(phone)) fail(40001, '请输入正确的手机号')
    if (!/^\d{6}$/.test(String(body.code ?? ''))) fail(40001, '请输入 6 位验证码')
    const intent = body.intent === 'register' ? 'register' : 'login'
    const registered = registeredPhones.has(phone)
    if (intent === 'register') {
      if (registered) fail(40901, '该手机号已注册，请直接登录')
      if (!body.agreed) fail(40001, '请先阅读并同意用户协议与隐私政策')
      registeredPhones.add(phone)
      state.user = createMockNewUser(phone)
    } else if (!registered) {
      fail(40401, '该手机号尚未注册，请先注册')
    } else if (phone === '13812345628' || phone === '13800005628') {
      state.user = clone(DEFAULT_USER)
    }
    const result: LoginResult = {
      accessToken: `mock-access-${Date.now()}`,
      refreshToken: `mock-refresh-${Date.now()}`,
      profile: clone(state.user),
      isNewUser: intent === 'register',
      onboardingStatus: state.user.onboardingStatus ?? 'COMPLETED',
    }
    return result
  }
  if ((path === '/auth/login/one-click' || path === '/auth/login/wechat') && method === 'POST') {
    const result: LoginResult = {
      accessToken: `mock-access-${Date.now()}`,
      refreshToken: `mock-refresh-${Date.now()}`,
      profile: clone(state.user),
      isNewUser: false,
      onboardingStatus: state.user.onboardingStatus ?? 'COMPLETED',
    }
    return result
  }
  if (path === '/auth/register/complete' && method === 'POST') {
    if (body.finish) {
      state.user.onboardingStatus = 'COMPLETED'
    } else if (body.skip) {
      state.user.onboardingStatus = 'PROFILE_COMPLETED'
    } else {
      const nickname = String(body.nickname ?? '').trim()
      if (!nickname) fail(40001, '请填写昵称')
      if (nickname.length > 16) fail(40001, '昵称最多 16 字')
      if (body.intentCommunityId === undefined || body.intentCommunityId === null || body.intentCommunityId === '') {
        fail(40001, '请选择入住小区')
      }
      state.user.nickname = nickname
      if (body.avatarKey) state.user.avatarPreset = String(body.avatarKey)
      const communityId = String(body.intentCommunityId)
      const community = [...state.communities, ...state.nearbyCommunities]
        .find((item) => item.id === communityId)
      state.user.intentCommunityId = communityId
      state.user.intentCommunityName = community?.name ?? ''
      state.user.onboardingStatus = 'PROFILE_COMPLETED'
    }
    return clone(state.user)
  }
  if (path === '/auth/token/refresh' && method === 'POST') {
    return { accessToken: `mock-access-${Date.now()}`, refreshToken: `mock-refresh-${Date.now()}` }
  }
  if (path === '/auth/status' && method === 'GET') {
    const realnameStatus = state.user.realnameStatus ?? 'UNVERIFIED'
    const ownerStatus = state.user.ownerStatus ?? 'UNVERIFIED'
    const realnameVerified = realnameStatus === 'VERIFIED'
    const ownerVerified = ownerStatus === 'VERIFIED'
    return {
      status: ownerVerified
        ? 'VERIFIED_OWNER'
        : ownerStatus === 'PENDING' || ownerStatus === 'SUPPLEMENT'
          ? 'PENDING_AUDIT'
          : ownerStatus === 'REJECTED'
            ? 'REJECTED'
            : realnameStatus === 'PENDING' || realnameStatus === 'SUPPLEMENT'
              ? 'VERIFYING'
              : realnameStatus === 'REJECTED'
                ? 'REJECTED'
                : realnameVerified
                  ? 'VERIFIED_UNOWNER'
                  : 'LOGGED_IN_UNVERIFIED',
      realname: {
        status: realnameStatus,
        rejectReason: '',
        canResubmit: true,
        submittedAt: 0,
        certId: '',
      },
      owner: {
        status: ownerStatus,
        rejectReason: '',
        canResubmit: true,
        submittedAt: 0,
        certId: '',
        communityId: state.user.intentCommunityId ?? '',
        communityName: state.user.intentCommunityName ?? '',
      },
      realnameVerified,
      ownerVerified,
      canResubmit: true,
      rejectType: '',
    }
  }
  if (path === '/auth/realname' && method === 'POST') {
    state.user.realnameStatus = 'PENDING'
    state.user.authStatus = state.user.ownerStatus === 'VERIFIED' ? 'VERIFIED_OWNER' : 'VERIFYING'
    return { status: 'PENDING', certId: `mock-cert-${Date.now()}`, message: '实名认证已提交' }
  }
  if (path === '/auth/owner-proof' && method === 'POST') {
    state.user.ownerStatus = 'PENDING'
    state.user.authStatus = 'PENDING_AUDIT'
    return { status: 'PENDING', certId: `mock-cert-${Date.now()}`, auditHours: 24 }
  }
  if (path === '/auth/logout' && method === 'POST') {
    return { success: true }
  }

  // ---------------- 首页 ----------------
  if (path === '/home' && method === 'GET') {
    return buildHome()
  }

  // ---------------- 物品 ----------------
  if (path === '/items/mine' && method === 'GET') {
    const mine = state.items.filter((item) => item.id.startsWith('mi') || item.seller?.id === 'me')
    return pageResult(mine, query)
  }
  if (path === '/items' && method === 'GET') {
    return pageResult(filterItems(query), query)
  }
  if (path === '/items' && method === 'POST') {
    const now = Date.now()
    const item: Item = {
      id: `i-${now}`,
      title: String(body.title ?? '未命名物品'),
      price: body.price ?? 0,
      type: body.tradeType ?? '出售',
      condition: body.condition ?? '轻微使用痕迹',
      distance: '约 120m',
      walk: '步行2分',
      time: state.user.communityName,
      image: (Array.isArray(body.images) && body.images[0]) || '',
      images: Array.isArray(body.images) ? body.images : [],
      category: body.category,
      description: body.qualityDesc,
      barterExpect: body.barterExpect,
      seller: mySeller(),
      aiVerified: false,
      status: 'DRAFT',
      favorite: false,
      tradeTypeCode: body.tradeType === '出售' ? 'MONETARY' : body.tradeType === '免费' ? 'FREE_GIFT' : 'BARTER',
      createdAt: now,
      viewCount: 0,
      commentCount: 0,
    }
    state.items.unshift(item)
    return { id: item.id, status: item.status }
  }
  if (segments[0] === 'items' && segments[2] === 'submit' && method === 'POST') {
    const item = findItem(segments[1])
    item.status = 'AUDITING'
    state.auditTicks[item.id] = 0
    return { auditId: `audit-${item.id}`, status: 'PROCESSING' }
  }
  if (segments[0] === 'items' && segments[2] === 'audit-progress' && method === 'GET') {
    const item = findItem(segments[1])
    const tick = (state.auditTicks[item.id] ?? 0) + 1
    state.auditTicks[item.id] = tick
    const progress: AuditProgress = createAuditProgress(item.id, tick)
    if (progress.status === 'PASSED') {
      item.status = 'ON_SALE'
      item.aiVerified = true
    }
    return progress
  }
  if (segments[0] === 'items' && segments[2] === 'favorite' && method === 'POST') {
    const item = findItem(segments[1])
    item.favorite = !item.favorite
    if (item.favorite) state.favoriteIds.add(item.id)
    else state.favoriteIds.delete(item.id)
    return { favorite: item.favorite }
  }
  if (segments[0] === 'items' && segments[2] === 'comments') {
    if (method === 'GET') return state.itemComments[segments[1]] ?? []
    if (method === 'POST') {
      const comment: ItemComment = {
        id: `cm-${Date.now()}`,
        author: state.user.nickname,
        avatar: state.user.avatarPreset ? `/static/avatars/${state.user.avatarPreset}.svg` : '',
        time: '刚刚',
        content: String(body.content ?? ''),
      }
      const list = state.itemComments[segments[1]] ?? []
      state.itemComments[segments[1]] = [comment, ...list]
      const item = findItem(segments[1])
      item.commentCount = (item.commentCount ?? 0) + 1
      return comment
    }
  }
  if (segments[0] === 'items' && segments[2] === 'distance' && method === 'GET') {
    const item = findItem(segments[1])
    const meters = parseDistanceMeters(item.distance)
    return {
      distance: item.distance,
      walk: item.walk,
      bike: `骑行${travelByMeters(meters / 3.2)}`,
      car: `驾车${travelByMeters(meters / 8)}`,
      meters,
    }
  }
  if (segments[0] === 'items' && method === 'GET' && segments.length === 2) {
    return clone(findItem(segments[1]))
  }
  if (segments[0] === 'items' && method === 'PUT' && segments.length === 2) {
    const item = findItem(segments[1])
    if (body.title !== undefined) item.title = String(body.title)
    if (body.price !== undefined) item.price = body.price
    if (body.tradeType !== undefined) {
      item.type = body.tradeType
      item.tradeTypeCode = body.tradeType === '出售' ? 'MONETARY' : body.tradeType === '免费' ? 'FREE_GIFT' : 'BARTER'
    }
    if (body.condition !== undefined) item.condition = body.condition
    if (body.category !== undefined) item.category = body.category
    if (body.qualityDesc !== undefined) item.description = body.qualityDesc
    if (body.barterExpect !== undefined) item.barterExpect = body.barterExpect
    if (Array.isArray(body.images) && body.images.length) {
      item.images = body.images
      item.image = body.images[0]
    }
    item.status = 'AUDITING'
    state.auditTicks[item.id] = 0
    return clone(item)
  }
  if (segments[0] === 'items' && segments[2] === 'renew' && method === 'POST') {
    const item = findItem(segments[1])
    item.createdAt = Date.now()
    return { success: true }
  }
  if (segments[0] === 'items' && segments[2] === 'off-shelf' && method === 'POST') {
    const item = findItem(segments[1])
    item.status = 'OFF_SHELF'
    return { success: true }
  }
  if (segments[0] === 'items' && method === 'DELETE' && segments.length === 2) {
    state.items = state.items.filter((item) => item.id !== segments[1])
    return { success: true }
  }

  // ---------------- 小区生活 ----------------
  if (path === '/life/posts' && method === 'GET') {
    const category = query.category ?? ''
    // 仅已发布内容出现在小区生活；无 status 的历史 Mock 数据视为已发布。
    let list = state.lifePosts.filter((item) => !item.status || item.status === 'PUBLISHED')
    if (category && category !== '全部') list = list.filter((item) => item.category === category)
    list.sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
    return pageResult(list, query)
  }
  if (path === '/life/posts' && method === 'POST') {
    const post: LifePost = {
      id: `l-${Date.now()}`,
      type: body.mediaType === 'video' ? 'video' : 'gallery',
      category: body.category ?? '邻里日常',
      title: String(body.title ?? ''),
      description: String(body.description ?? ''),
      images: Array.isArray(body.media) ? body.media : [],
      cover: (Array.isArray(body.media) && body.media[0]) || '',
      duration: body.duration,
      author: state.user.nickname,
      avatar: state.user.avatarPreset ? `/static/avatars/${state.user.avatarPreset}.svg` : '',
      avatarClass: 'orange',
      area: `阳光花园 · ${state.user.address.split(' ')[1] ?? '3号楼'}`,
      time: '刚刚',
      status: 'PENDING_REVIEW',
      statusLabel: '待审核',
      views: 0,
      likes: 0,
      comments: 0,
      createdAt: Date.now(),
    }
    state.lifePosts.unshift(post)
    return post
  }
  if (segments[0] === 'life' && segments[1] === 'posts' && segments[2] === 'mine' && method === 'GET') {
    const list = state.lifePosts.map((item) => ({
      ...item,
      status: item.status ?? 'PUBLISHED',
      statusLabel: item.statusLabel ?? '已发布',
    }))
    list.sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
    return pageResult(list, query)
  }
  if (segments[0] === 'life' && segments[1] === 'posts' && segments[3] === 'like' && method === 'POST') {
    const post = state.lifePosts.find((item) => item.id === segments[2])
    if (!post) fail(40001, '动态不存在')
    post.liked = !post.liked
    post.likes += post.liked ? 1 : -1
    return { liked: post.liked, likes: post.likes }
  }
  if (segments[0] === 'life' && segments[1] === 'posts' && segments[3] === 'comments') {
    if (method === 'GET') return state.lifeComments[segments[2]] ?? []
    if (method === 'POST') {
      const comment: LifeComment = {
        id: `lc-${Date.now()}`,
        author: state.user.nickname,
        avatar: state.user.avatarPreset ? `/static/avatars/${state.user.avatarPreset}.svg` : '',
        content: String(body.content ?? ''),
        time: '刚刚',
      }
      const list = state.lifeComments[segments[2]] ?? []
      state.lifeComments[segments[2]] = [comment, ...list]
      const post = state.lifePosts.find((item) => item.id === segments[2])
      if (post) post.comments += 1
      return comment
    }
  }
  if (segments[0] === 'life' && segments[1] === 'posts' && method === 'GET' && segments.length === 3) {
    const post = state.lifePosts.find((item) => item.id === segments[2])
    if (!post) fail(40001, '动态不存在')
    return clone(post)
  }

  // ---------------- 邻里互助 ----------------
  if (path === '/services' && method === 'GET') {
    const kind = query.kind ?? ''
    const category = query.category ?? ''
    let list = [...state.servicePosts]
    if (kind) list = list.filter((item) => item.kind === kind)
    if (category && category !== '全部') list = list.filter((item) => item.category === category)
    return pageResult(list, query)
  }
  if (path === '/services' && method === 'POST') {
    const kind = body.kind === 'OFFER' || body.kind === '提供' ? '提供' : '求助'
    const post: ServicePost = {
      id: `s-${Date.now()}`,
      kind,
      icon: body.icon || (kind === '提供' ? 'friend' : 'child'),
      category: body.category ?? '其他',
      title: String(body.title ?? ''),
      description: String(body.description ?? ''),
      time: '刚刚',
      place: body.location ?? body.place ?? state.user.communityName,
      distance: '约 100m',
      reward: body.reward ?? '邻里互助',
      author: state.user.nickname,
      avatar: state.user.avatarPreset ? `/static/avatars/${state.user.avatarPreset}.svg` : '',
      avatarClass: 'orange',
      responses: 0,
      price: body.reward || undefined,
      credit: '信用良好',
    }
    state.servicePosts.unshift(post)
    return post
  }
  if (segments[0] === 'services' && segments[2] === 'respond' && method === 'POST') {
    const post = state.servicePosts.find((item) => String(item.id) === segments[1])
    if (!post) fail(40001, '服务不存在')
    post.responses += 1
    return { success: true, responses: post.responses }
  }

  // ---------------- 喇叭站 ----------------
  if (path === '/broadcasts' && method === 'GET') {
    return clone(state.broadcasts)
  }
  if (segments[0] === 'broadcasts' && segments[2] === 'favorite' && method === 'POST') {
    const broadcast = state.broadcasts.find((item) => item.id === segments[1])
    if (!broadcast) fail(40001, '播报不存在')
    broadcast.favorited = !broadcast.favorited
    return { favorited: broadcast.favorited }
  }
  if (segments[0] === 'broadcasts' && segments[2] === 'respond' && method === 'POST') {
    const broadcast = state.broadcasts.find((item) => item.id === segments[1])
    if (!broadcast) fail(40001, '播报不存在')
    broadcast.responseCount = (broadcast.responseCount ?? 0) + 1
    return { success: true, responseCount: broadcast.responseCount }
  }
  if (segments[0] === 'broadcasts' && method === 'GET' && segments.length === 2) {
    const broadcast = state.broadcasts.find((item) => item.id === segments[1])
    if (!broadcast) fail(40001, '播报不存在')
    return clone(broadcast)
  }

  // ---------------- 行政区划与小区 ----------------
  if (path === '/regions/children' && method === 'GET') {
    return clone(regionChildren(query.parentId ?? ''))
  }
  if (path === '/communities/mine' && method === 'GET') {
    return clone(state.communities)
  }
  if (path === '/communities/nearby' && method === 'GET') {
    return clone(state.nearbyCommunities)
  }
  if (path === '/communities/search' && method === 'GET') {
    const keyword = (query.keyword ?? '').trim()
    const cityId = (query.cityId ?? '').trim()
    const streetId = (query.streetId ?? '').trim()
    const regionId = (query.regionId ?? '').trim()
    const seen = new Set<string>()
    let source = [...state.nearbyCommunities, ...state.communities].filter((item) => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })
    if (cityId) {
      const districtIds = new Set(regionChildren(cityId).map((node) => node.id))
      source = source.filter((item) => Boolean(item.regionId && districtIds.has(item.regionId)))
    }
    if (streetId) source = source.filter((item) => item.streetId === streetId)
    if (regionId) source = source.filter((item) => item.regionId === regionId)
    if (!keyword) return clone(source)
    return clone(source.filter((item) => item.name.includes(keyword) || String(item.address ?? '').includes(keyword)))
  }
  if (segments[0] === 'communities' && segments[2] === 'verify' && method === 'POST') {
    const target = [...state.nearbyCommunities, ...state.communities].find((item) => item.id === segments[1])
    if (!target) fail(40001, '小区不存在')
    if (state.communities.length >= APP_CONFIG.maxCommunities) fail(40001, '最多认证 3 个小区')
    if (!state.communities.some((item) => item.id === target.id)) {
      state.communities.push({
        ...target,
        role: body.identity === 'owner' ? '业主' : body.identity === 'tenant' ? '租户' : body.identity === 'family' ? '家属' : body.identity === 'staff' ? '教职工' : body.identity === 'student' ? '学生' : '家属',
        status: '审核中',
      })
    }
    return { status: '审核中', success: true }
  }

  // ---------------- 通知 ----------------
  if (path === '/notifications' && method === 'GET') {
    const category = query.category ?? ''
    let list = [...state.notifications]
    if (category && category !== '全部') list = list.filter((item) => item.category === category)
    list.sort((a, b) => b.createdAt - a.createdAt)
    return pageResult(list, query)
  }
  if (path === '/notifications/unread' && method === 'GET') {
    return { count: unreadNotificationCount(), conversationCount: unreadConversationCount() }
  }
  if (path === '/notifications/read-all' && method === 'POST') {
    state.notifications.forEach((item) => {
      item.read = true
    })
    return { success: true }
  }
  if (path === '/notifications/settings' && method === 'GET') {
    return clone(state.settings)
  }
  if (path === '/notifications/settings' && method === 'PUT') {
    state.settings = { ...state.settings, ...body }
    return clone(state.settings)
  }
  if (segments[0] === 'notifications' && segments[2] === 'read' && method === 'POST') {
    const notification = state.notifications.find((item) => item.id === Number(segments[1]))
    if (notification) notification.read = true
    return { success: true, unread: unreadNotificationCount() }
  }

  // ---------------- 用户资料 ----------------
  if (path === '/users/me' && method === 'GET') {
    return clone(state.user)
  }
  if (path === '/users/me' && method === 'PUT') {
    state.user = { ...state.user, ...body }
    return clone(state.user)
  }
  if (path === '/users/me/avatar' && method === 'POST') {
    state.user.avatarPreset = body.avatarPreset ?? state.user.avatarPreset
    state.user.avatarDataUrl = body.avatarDataUrl ?? state.user.avatarDataUrl
    return clone(state.user)
  }
  if (path === '/avatars/presets' && method === 'GET') {
    return [
      { key: 'person', label: '卡通人物', items: ['avatar-person-1', 'avatar-person-2', 'avatar-person-3'] },
      { key: 'animal', label: '卡通动物', items: ['avatar-animal-1', 'avatar-animal-2', 'avatar-animal-3'] },
      { key: 'landmark', label: '名胜古迹', items: ['avatar-landmark-1', 'avatar-landmark-2', 'avatar-landmark-3'] },
      { key: 'nature', label: '自然风景', items: ['avatar-nature-1', 'avatar-nature-2', 'avatar-nature-3'] },
    ]
  }
  if (path === '/favorites' && method === 'GET') {
    const type = query.type ?? 'item'
    if (type === 'service') return { items: [], services: clone(state.servicePosts.slice(0, 2)), life: [] }
    if (type === 'life') return { items: [], services: [], life: clone(state.lifePosts.filter((post) => post.liked)) }
    return {
      items: clone(state.items.filter((item) => state.favoriteIds.has(item.id))),
      services: [],
      life: [],
    }
  }
  if (path === '/favorites' && method === 'POST') {
    const id = String(body.id ?? '')
    state.favoriteIds.add(id)
    const item = state.items.find((entry) => entry.id === id)
    if (item) item.favorite = true
    return { success: true }
  }
  if (path === '/favorites' && method === 'DELETE') {
    const id = String(body.id ?? '')
    state.favoriteIds.delete(id)
    const item = state.items.find((entry) => entry.id === id)
    if (item) item.favorite = false
    return { success: true }
  }
  if (path === '/history' && method === 'GET') {
    return clone(state.viewHistory.map((id) => state.items.find((item) => item.id === id)).filter(Boolean))
  }
  if (path === '/history' && method === 'POST') {
    const id = String(body.id ?? '')
    state.viewHistory = [id, ...state.viewHistory.filter((entry) => entry !== id)].slice(0, 100)
    return { success: true }
  }
  if (path === '/search' && method === 'GET') {
    const keyword = (query.keyword ?? '').trim()
    const lower = keyword.toLowerCase()
    const chars = Array.from(lower)
    const matchesKeyword = (text: string): boolean => {
      if (!keyword) return true
      const target = text.toLowerCase()
      return target.includes(lower) || chars.every((char) => target.includes(char))
    }
    return {
      keyword,
      items: clone(
        state.items.filter(
          (item) =>
            item.status === 'ON_SALE' &&
            matchesKeyword(`${item.title} ${item.description ?? ''} ${item.category ?? ''}`),
        ).slice(0, 20),
      ),
      lifePosts: clone(state.lifePosts.filter((post) => !keyword || post.title.includes(keyword)).slice(0, 5)),
      services: clone(state.servicePosts.filter((post) => !keyword || post.title.includes(keyword)).slice(0, 5)),
    }
  }
  if (path === '/search/hot' && method === 'GET') {
    return [...HOT_KEYWORDS]
  }
  if (path === '/search/history' && method === 'GET') {
    return [...state.searchHistory]
  }
  if (path === '/search/history' && method === 'POST') {
    const keyword = String(body.keyword ?? '').trim()
    if (keyword) state.searchHistory = [keyword, ...state.searchHistory.filter((item) => item !== keyword)].slice(0, 10)
    return [...state.searchHistory]
  }
  if (path === '/search/history' && method === 'DELETE') {
    state.searchHistory = []
    return []
  }
  if (path === '/mine/stats' && method === 'GET') {
    const onSale = state.items.filter((item) => item.id.startsWith('mi') && item.status === 'ON_SALE').length
    return {
      publishCount: onSale,
      favoriteCount: state.favoriteIds.size,
      historyCount: state.viewHistory.length,
      lifeCount: 8,
      serviceCount: 5,
      creditScore: state.user.creditScore,
    }
  }
  if (path === '/mine/credit' && method === 'GET') {
    return {
      score: state.user.creditScore,
      level: state.user.creditLevel,
      nextLevel: '信用极好 · 距离下一等级还差 8 分',
      records: [
        { id: 'cr1', title: '完成担保交易', delta: 5, time: '11-09' },
        { id: 'cr2', title: '按时赴约', delta: 3, time: '11-06' },
        { id: 'cr3', title: '收到好评', delta: 2, time: '11-06' },
        { id: 'cr4', title: '参与邻里互助', delta: 4, time: '10-28' },
      ],
    }
  }

  // ---------------- 订单 ----------------
  if (path === '/orders' && method === 'POST') {
    return createOrder(body)
  }
  if (path === '/orders' && method === 'GET') {
    const type = query.type ?? ''
    const code = type === 'free' ? 'FREE_GIFT' : type === 'swap' ? 'BARTER' : type === 'monetary' ? 'MONETARY' : ''
    let list = [...state.orders]
    if (code) list = list.filter((order) => order.tradeTypeCode === code)
    list.sort((a, b) => b.createdAt - a.createdAt)
    return pageResult(list, query)
  }
  if (segments[0] === 'orders' && segments[2] === 'appointment' && method === 'POST') {
    const order = findOrder(segments[1])
    order.appointment = {
      time: body.time ?? '明天 14:00',
      place: body.place ?? '物业中心',
      note: body.note,
      status: 'CONFIRMED',
    }
    order.status = 'APPOINTMENT'
    order.statusText = '已预约验货'
    order.canAppointment = false
    order.timeline = order.timeline.map((step) =>
      step.key === 'appointment'
        ? { ...step, title: `预约见面：${order.appointment?.time}`, time: stamp(), done: true, active: true }
        : step,
    )
    return clone(order)
  }
  if (segments[0] === 'orders' && segments[2] === 'confirm-application' && method === 'POST') {
    const order = findOrder(segments[1])
    if (order.tradeType === '出售') fail(40001, '担保交易无需确认申请')
    if (order.status !== 'PENDING_CONFIRM') fail(40001, '当前订单状态不可确认')
    order.status = 'CONFIRMED'
    order.statusText = '已确认，等待见面交割'
    order.canConfirmApplication = false
    order.canCompleteTrade = true
    order.canCancel = true
    order.timeline = order.timeline.map((step) =>
      step.key === 'confirm' || step.key === 'applied'
        ? { ...step, done: true, active: false, time: step.time || stamp() }
        : step.key === 'meet'
          ? { ...step, active: true }
          : step,
    )
    return clone(order)
  }
  if (segments[0] === 'orders' && segments[2] === 'confirm' && method === 'POST') {
    const order = findOrder(segments[1])
    completeOrder(order)
    return clone(order)
  }
  if (segments[0] === 'orders' && segments[2] === 'cancel' && method === 'POST') {
    const order = findOrder(segments[1])
    order.status = 'CANCELLED'
    order.statusText = '已取消'
    order.canPay = false
    order.canAppointment = false
    order.canInspect = false
    order.canCancel = false
    const item = state.items.find((entry) => entry.id === order.item.id)
    if (item && item.status === 'RESERVED') item.status = 'ON_SALE'
    return clone(order)
  }
  if (segments[0] === 'orders' && segments[2] === 'dispute' && method === 'POST') {
    const order = findOrder(segments[1])
    order.status = 'DISPUTING'
    order.statusText = '纠纷处理中'
    return { success: true, order: clone(order) }
  }
  if (segments[0] === 'orders' && segments[2] === 'reviews' && method === 'POST') {
    const order = findOrder(segments[1])
    order.reviewable = false
    order.canReview = false
    state.user.creditScore = Math.min(100, state.user.creditScore + 1)
    return { success: true, rating: (body as ReviewPayload).rating ?? 5 }
  }
  if (segments[0] === 'orders' && method === 'GET' && segments.length === 2) {
    return clone(findOrder(segments[1]))
  }

  // ---------------- 支付 ----------------
  if (path === '/payments/prepay' && method === 'POST') {
    return prepay(body)
  }
  if (segments[0] === 'payments' && segments[2] === 'status' && method === 'GET') {
    const order = state.orders.find((entry) => entry.orderNo === segments[1])
    return {
      status: order ? 'SUCCESS' : 'NOT_FOUND',
      orderId: order?.id,
      orderStatus: order?.status,
    }
  }

  // ---------------- 钱包 ----------------
  if (path === '/wallet' && method === 'GET') {
    return clone(state.wallet)
  }
  if (path === '/wallet/transactions' && method === 'GET') {
    return pageResult(state.transactions, query)
  }
  if (path === '/wallet/withdrawals' && method === 'POST') {
    const amount = Number(body.amount ?? 0)
    if (!Number.isFinite(amount) || amount <= 0) fail(40001, '请输入有效提现金额')
    if (amount > state.wallet.withdrawable) fail(40001, '可提现余额不足')
    state.wallet.balance -= amount
    state.wallet.withdrawable -= amount
    state.transactions.unshift({
      id: `w-${Date.now()}`,
      title: '提现至银行卡',
      amount,
      direction: 'out',
      time: stamp(),
      icon: 'order',
    })
    return { success: true, status: 'PROCESSING' }
  }

  // ---------------- 社交 ----------------
  if (path === '/conversations' && method === 'GET') {
    const list = [...state.conversations].sort((a, b) => b.unread - a.unread)
    return list.map((item) => ({
      ...item,
      type: item.type ?? (item.itemId ? 'ITEM' : 'FRIEND'),
      canSend: true,
      readOnlyReason: null,
    }))
  }
  if (path === '/conversations' && method === 'POST') {
    const peerId = String(body.peerId ?? '')
    const existing = state.conversations.find((item) => item.peerId === peerId)
    if (existing) return clone(existing)
    const peer =
      Object.values(SELLERS).find((item) => item.id === peerId) ??
      state.friends.find((item) => item.id === peerId)
    const conversation: Conversation = {
      id: `c-${Date.now()}`,
      type: body.itemId ? 'ITEM' : 'FRIEND',
      peerId,
      peerName: peer?.name ?? '新邻居',
      peerAvatar: peer?.avatar ?? '/static/avatars/avatar-person-1.svg',
      peerVerified: true,
      lastMessage: '你好，想咨询一下',
      lastTime: '刚刚',
      unread: 0,
      itemId: body.itemId,
      canSend: true,
      readOnlyReason: null,
    }
    state.conversations.unshift(conversation)
    state.messages[conversation.id] = []
    return clone(conversation)
  }
  if (path === '/conversations/read-all' && method === 'POST') {
    state.conversations.forEach((item) => {
      item.unread = 0
    })
    return { success: true }
  }
  if (segments[0] === 'conversations' && segments[2] === 'messages') {
    const conversationId = segments[1]
    if (method === 'GET') {
      return {
        items: clone(state.messages[conversationId] ?? []),
        hasMoreBefore: false,
        hasMoreAfter: false,
      }
    }
    if (method === 'POST') {
      const list = state.messages[conversationId] ?? []
      const seq = list.reduce((max, item) => Math.max(max, item.seq ?? 0), 0) + 1
      const messageType = String(body.type ?? 'TEXT')
      const message: ChatMessage = {
        id: `m-${Date.now()}`,
        clientMsgId: body.clientMsgId,
        conversationId,
        seq,
        senderId: 'me',
        senderName: '我',
        type: messageType as ChatMessage['type'],
        content: String(body.content ?? ''),
        image: body.image,
        imageKey: body.image,
        extra: body.extra ?? {},
        createdAt: Date.now(),
        timeText: '刚刚',
        status: 'SENT',
        mine: true,
      }
      state.messages[conversationId] = [...list, message]
      const conversation = state.conversations.find((item) => item.id === conversationId)
      if (conversation) {
        conversation.lastMessage = messageType === 'IMAGE'
          ? '[图片]'
          : messageType === 'VIDEO'
            ? '[视频]'
            : message.content
        conversation.lastMessageType = messageType
        conversation.lastTime = '刚刚'
      }
      return clone(message)
    }
  }
  if (segments[0] === 'conversations' && segments[2] === 'read' && method === 'POST') {
    const conversation = state.conversations.find((item) => item.id === segments[1])
    if (conversation) conversation.unread = 0
    return { success: true }
  }
  const mockEligibility = {
    eligible: true,
    realnameVerified: true,
    ownerVerified: true,
    communityId: '1',
    communityName: '阳光花园小区',
    reasonCode: 'OK',
    reasonText: '',
  }
  if (path === '/friends/eligibility' && method === 'GET') {
    return clone(mockEligibility)
  }
  if (path === '/friends/blocks' && method === 'GET') {
    return { items: [], page: 1, pageSize: 20, total: 0, hasMore: false }
  }
  if (path === '/friends' && method === 'GET') {
    const items = state.friends.map((friend) => ({
      ...friend,
      userId: friend.userId ?? friend.id,
      building: friend.building ?? friend.community,
      identityType: friend.identityType ?? '业主',
    }))
    return {
      items,
      page: 1,
      pageSize: 50,
      total: items.length,
      hasMore: false,
      eligibility: mockEligibility,
    }
  }
  if (
    segments[0] === 'friends' &&
    segments[1] &&
    segments[1] !== 'requests' &&
    segments.length === 2 &&
    method === 'GET'
  ) {
    const friend = state.friends.find((item) => (item.userId ?? item.id) === segments[1])
    if (!friend) fail(40401, '邻居不存在')
    return {
      ...friend,
      userId: friend.userId ?? friend.id,
      relation: 'FRIEND',
      blockedByMe: false,
      blockedMe: false,
      canMessage: true,
      reasonCode: 'OK',
    }
  }
  if (
    segments[0] === 'friends' &&
    segments[2] === 'remark' &&
    method === 'PUT'
  ) {
    const friend = state.friends.find((item) => (item.userId ?? item.id) === segments[1])
    if (friend) {
      friend.remark = String(body.remark ?? '')
      friend.name = friend.remark || friend.name
    }
    return { peerId: segments[1], remark: String(body.remark ?? '') }
  }
  if (segments[0] === 'friends' && segments[2] === 'block') {
    if (method === 'POST') {
      state.friends = state.friends.filter((item) => (item.userId ?? item.id) !== segments[1])
      return { blocked: true }
    }
    if (method === 'DELETE') return { blocked: false }
  }
  if (
    segments[0] === 'friends' &&
    segments[1] === 'requests' &&
    segments.length === 4 &&
    (segments[3] === 'accept' || segments[3] === 'reject') &&
    method === 'POST'
  ) {
    const request = state.friendRequests.find((item) => item.id === segments[2])
    if (!request) fail(40001, '好友申请不存在')
    request.status = segments[3] === 'accept' ? 'ACCEPTED' : 'REJECTED'
    if (request.status === 'ACCEPTED') {
      state.friends.unshift({
        id: `u-${Date.now()}`,
        name: request.name,
        avatar: request.avatar,
        verified: true,
        community: '阳光花园',
        letter: request.name.slice(0, 1),
      })
    }
    return { success: true }
  }
  if (segments[0] === 'friends' && segments[1] === 'requests' && segments.length === 2) {
    if (method === 'GET') return clone(state.friendRequests)
    if (method === 'POST') {
      const request: FriendRequest = {
        id: `fr-${Date.now()}`,
        name: String(body.name ?? '新邻居'),
        avatar: '/static/avatars/avatar-person-1.svg',
        message: String(body.message ?? ''),
        time: '刚刚',
        status: 'PENDING',
      }
      state.friendRequests.unshift(request)
      return request
    }
  }
  if (segments[0] === 'friends' && method === 'DELETE' && segments.length === 2) {
    state.friends = state.friends.filter((item) => item.id !== segments[1])
    return { success: true }
  }

  // ---------------- 配置 / 上传 / 埋点 ----------------
  if (path === '/config/app' && method === 'GET') {
    return clone(APP_CONFIG)
  }
  if (path === '/categories' && method === 'GET') {
    return {
      itemCategories: ['家具家电', '母婴用品', '数码', '图书', '服饰', '运动户外', '其他'],
      conditions: ['全新', '九九新', '轻微使用痕迹', '明显使用痕迹', '有功能缺陷'],
      lifeCategories: ['小区风景', '邻里日常', '个人风采', '萌宠生活'],
      serviceCategories: ['接送照看', '宠物照看', '学习陪伴', '邻里活动', '维修安装', '其他'],
    }
  }
  if (path === '/uploads/presign' && method === 'POST') {
    const fileName = String(body.fileName ?? `ni-${Date.now()}.jpg`)
    return {
      uploadUrl: `https://upload-dev.neighinn.example.com/mock/${fileName}`,
      fileUrl: `https://cdn-dev.neighinn.example.com/mock/${fileName}`,
      headers: {},
    }
  }
  if (path === '/track/batch' && method === 'POST') {
    return { accepted: Array.isArray(body.events) ? body.events.length : 0 }
  }

  fail(404, `Mock 接口不存在：${method} ${path}`)
}

export async function mockRequest<T>(options: MockRequestOptions): Promise<T> {
  const method = (options.method || 'GET').toUpperCase()
  const [path] = options.url.split('?')
  const query = parseQuery(options.url)
  const body = options.data ?? {}

  await delay(env.mockLatency + Math.random() * 80)
  const result = await route(path, method, query, body)
  return clone(result) as T
}

export function resetMockState(): void {
  state.notifications = clone(NOTIFICATIONS)
  state.orders = clone(ORDERS)
}
