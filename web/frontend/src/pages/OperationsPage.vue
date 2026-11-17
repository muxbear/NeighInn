<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArchiveX, CircleX, Coffee, HandHeart, Megaphone, Pencil, Plus, Search, ShieldCheck, ShoppingBag, SlidersHorizontal, Trash2, Upload, X } from 'lucide-vue-next'
import { filesApi, operationsApi } from '@/api'
import { mapTradeType } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useNavBadgeStore } from '@/stores/navBadges'
import { useConfirm } from '@/composables/useConfirm'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import CommunityFilterBar from '@/components/CommunityFilterBar.vue'

const route = useRoute()
const app = useAppStore()
const auth = useAuthStore()
const navBadges = useNavBadgeStore()
const { confirm } = useConfirm()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const query = ref('')
const activeTab = ref('全部')
const helpKind = ref('全部')
const selectedRows = ref<string[]>([])
const loading = ref(false)
const drawerOpen = ref(false)
const broadcastEditTarget = ref<any>(null)
const form = ref({
  title: '',
  subtitle: '',
  type: 'NEW_ITEM',
  content: '',
  important: false,
  effectiveMode: 'IMMEDIATE',
  startAt: '',
  endAt: '',
})
const overview = ref<any>(null)
const itemCategories = ref<any[]>([])

const ITEM_CONDITIONS = ['全新', '九九新', '轻微使用痕迹', '明显使用痕迹', '有功能缺陷']
const BROADCAST_TYPES = [
  { value: 'URGENT_HELP', label: '紧急求助' },
  { value: 'FREE_NEW', label: '免费上新' },
  { value: 'REWARD', label: '悬赏服务' },
  { value: 'NEW_ITEM', label: '新上架' },
]
/** 移动端生活分类 + 详设 4.7.3.5 运营频道分类，覆盖存量数据。 */
const LIFE_CATEGORIES = [
  '小区风景', '邻里日常', '个人风采', '萌宠生活',
  '周末去哪', '邻里探店', '社区团购', '健康生活', '便民指南', '居家技巧',
]
const TRADE_TYPES = [
  { value: 'MONETARY', label: '货币交易' },
  { value: 'FREE_GIFT', label: '免费赠与' },
  { value: 'BARTER', label: '物品互换' },
]

type LifeMediaItem = { key: string; url: string; type: 'image' | 'video' }

const configs: Record<string, any> = {
  broadcast: {
    api: 'broadcasts', title: '社区喇叭', tone: 'broadcast', icon: Megaphone,
    ownerLabel: '喇叭归属小区', scopeNote: '喇叭列表仅展示所选小区',
    description: '运营社区即时播报、邻里话题、重要提醒和互动内容', create: '发布喇叭',
    tabs: ['全部', '已发布', '定时发布', '已下架'],
    metrics: [
      { label: '今日播报', value: '28', note: '较昨日 +6' },
      { label: '待审核', value: '6', note: '2 条高优先级', attention: true },
      { label: '今日互动', value: '1,286', note: '评论与点赞' },
      { label: '内容触达率', value: '82.4%', note: '近 7 日 +3.2%' },
    ],
  },
  items: {
    api: 'items', title: '社区物品', tone: 'items', icon: ShoppingBag,
    ownerLabel: '物品归属小区', scopeNote: '物品列表仅展示所选小区',
    description: '管理邻里闲置物品、热门推荐、商品审核及交易状态', create: '新增物品',
    tabs: ['全部', '在售', '待审核', '已售出', '已下架'],
  },
  help: {
    api: 'help-requests', title: '邻里互助', tone: 'help', icon: HandHeart,
    ownerLabel: '互助归属小区', scopeNote: '互助列表仅展示所选小区',
    description: '管理居民求助、邻里响应、撮合履约及互助信用评价', create: '代发互助',
    tabs: ['全部', '待审核', '待响应', '匹配中', '进行中', '已完成', '已关闭', '已驳回'],
  },
  life: {
    api: 'life-posts', title: '社区生活', tone: 'life', icon: Coffee,
    ownerLabel: '内容归属小区', scopeNote: '生活内容仅展示所选小区',
    description: '运营小区生活、便民指南、探店内容和专题推荐', create: '新建内容',
    tabs: ['全部', '已发布', '草稿', '待审核', '已下线'],
    metrics: [
      { label: '频道内容', value: '248', note: '覆盖 8 个分类' },
      { label: '今日阅读', value: '6,328', note: '较昨日 +14.8%', attention: true },
      { label: '待审核', value: '9', note: '含 3 条商户投稿' },
      { label: '内容收藏率', value: '12.6%', note: '近 7 日 +1.9%' },
    ],
  },
}

/**
 * 页面 Tab 是中文标签，服务端状态机使用英文编码。
 * 过滤条件必须下发编码，否则「待审核」等 Tab 永远查不到数据。
 */
const TAB_STATUS: Record<string, Record<string, string>> = {
  broadcast: { 已发布: 'PUBLISHED', 待审核: 'PENDING_REVIEW', 定时发布: 'SCHEDULED', 已下架: 'OFFLINE' },
  life: { 已发布: 'PUBLISHED', 草稿: 'DRAFT', 待审核: 'PENDING_REVIEW', 已下线: 'OFFLINE' },
  help: {
    待审核: 'PENDING_REVIEW', 待响应: 'OPEN', 匹配中: 'MATCHING',
    进行中: 'IN_PROGRESS', 已完成: 'COMPLETED', 已关闭: 'CLOSED', 已驳回: 'REJECTED',
  },
  items: { 在售: 'ON_SALE', 待审核: 'PENDING_REVIEW', 已售出: 'SOLD', 已下架: 'OFF_SHELF' },
}

const ITEM_OFFLINE_BLOCKED = ['SOLD', 'GIFTED', 'OFF_SHELF']
const HELP_KIND_TABS = [
  { label: '全部', code: '' },
  { label: '邻里求助', code: 'HELP' },
  { label: '邻里服务', code: 'OFFER' },
]

const module = computed(() => String(route.params.module || 'broadcast'))
const config = computed(() => configs[module.value] || configs.broadcast)
const tabs = computed(() => config.value.tabs)
const filteredRows = computed(() => rows.value)
const canCreate = computed(() => module.value === 'broadcast' && auth.hasPermission('community:broadcast:create'))
const canEditBroadcast = computed(() => module.value === 'broadcast'
  && (auth.hasPermission('community:broadcast:update') || auth.hasPermission('community:broadcast:create')))
const canDeleteBroadcast = computed(() => module.value === 'broadcast'
  && (auth.hasPermission('community:broadcast:delete') || auth.hasPermission('community:broadcast:offline')))
const canEditHelp = computed(() => module.value === 'help' && auth.hasPermission('community:help:update'))
const canDeleteHelp = computed(() => module.value === 'help' && auth.hasPermission('community:help:delete'))
const canReviewHelp = computed(() => module.value === 'help' && auth.hasPermission('community:help:review'))
const canEditItem = computed(() => module.value === 'items' && auth.hasPermission('community:item:update'))
const canDeleteItem = computed(() => module.value === 'items' && auth.hasPermission('community:item:delete'))
const canEditLife = computed(() => module.value === 'life' && auth.hasPermission('community:life:update'))
const canDeleteLife = computed(() => module.value === 'life' && auth.hasPermission('community:life:delete'))

/** 运营指标卡：物品与社区生活均来自 /operations/overview 实时聚合（禁止硬编码）。 */
const metrics = computed(() => {
  if (module.value === 'broadcast') {
    const data = overview.value?.metrics || {}
    return [
      {
        label: '生效中',
        value: String(Number(data.active || 0)),
        note: `累计 ${Number(data.total || 0)} 条喇叭`,
      },
      {
        label: '定时待发',
        value: String(Number(data.scheduled || 0)),
        note: Number(data.scheduled || 0) ? '到点自动生效' : '暂无定时喇叭',
      },
      {
        label: '今日发布',
        value: String(Number(data.todayPublished || 0)),
        note: '即时与定时发布合计',
        attention: true,
      },
      {
        label: '累计互动',
        value: String(Number(data.totalResponses || 0)),
        note: '移动端邻居响应次数',
      },
    ]
  }
  if (module.value === 'life') {
    const data = overview.value?.metrics || {}
    const delta = Number(data.todayViewsDelta || 0)
    return [
      {
        label: '频道内容',
        value: String(data.total || 0),
        note: `覆盖 ${data.categoryCount || 0} 个分类`,
      },
      {
        label: '今日阅读',
        value: Number(data.todayViews || 0).toLocaleString('zh-CN'),
        note: data.yesterdayViews
          ? `较昨日 ${delta >= 0 ? '+' : ''}${delta}%`
          : '暂无昨日基线',
        attention: true,
      },
      {
        label: '待审核',
        value: String(data.pendingReview || 0),
        note: data.pendingReview ? '含移动端业主投稿' : '暂无待审核',
        attention: true,
      },
      {
        label: '内容收藏率',
        value: `${Number(data.favoriteRate || 0).toFixed(1)}%`,
        note: `累计 ${data.totalLikes || 0} 收藏 / ${data.totalViews || 0} 阅读`,
      },
    ]
  }
  if (module.value === 'help') {
    const data = overview.value?.metrics || {}
    const pending = Number(data.pendingResponse || 0)
    const credit = Number(data.creditScore || 0)
    return [
      {
        label: '今日求助',
        value: String(Number(data.todayHelp || 0)),
        note: Number(data.urgentHelp || 0) > 0
          ? `紧急求助 ${Number(data.urgentHelp || 0)} 条`
          : '暂无紧急求助',
      },
      {
        label: '待响应',
        value: String(pending),
        note: pending ? `平均等待 ${Number(data.pendingAvgMinutes || 0)} 分钟` : '暂无待响应',
        attention: true,
      },
      {
        label: '本周完成',
        value: String(Number(data.weekCompleted || 0)),
        note: `完成率 ${Number(data.completionRate || 0).toFixed(1)}%`,
      },
      {
        label: '互助信用分',
        value: credit.toFixed(1),
        note: credit ? '社区平均分' : '暂无社区评分',
      },
    ]
  }
  if (module.value !== 'items') return config.value.metrics
  const data = overview.value?.metrics || {}
  const recommended = Number(data.recommended || 0)
  const slots = Number(data.recommendSlots || 12)
  const gmv = Number(data.weekGmvCents || 0) / 100
  return [
    { label: '在售物品', value: String(data.onSale || 0), note: `本周新增 ${data.weekNew || 0}` },
    {
      label: '待审核',
      value: String(data.pendingReview || 0),
      note: data.pendingReview ? `平均等待 ${data.pendingAvgMinutes || 0} 分钟` : '暂无待审核',
      attention: true,
    },
    {
      label: '本周成交',
      value: String(data.weekDeals || 0),
      note: `成交额 ¥${gmv.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`,
    },
    {
      label: '热门推荐位',
      value: `${recommended} / ${slots}`,
      note: `剩余 ${Math.max(0, slots - recommended)} 个展位`,
    },
  ]
})

const reviewOpen = ref(false)
const reviewTarget = ref<any>(null)
const reviewDetail = ref<any>(null)
const reviewAudit = ref<any>(null)
const reviewLoading = ref(false)
const reviewSubmitting = ref(false)
const reviewForm = ref({ decision: 'APPROVE', reason: '', recommend: false })
const reviewDecisions = [
  { value: 'APPROVE', label: '通过并上架' },
  { value: 'REJECT', label: '驳回修改' },
  { value: 'DOWNGRADE', label: '降级上架' },
]

function tabStatusCode(tab: string): string {
  if (tab === '全部') return ''
  return TAB_STATUS[module.value]?.[tab] ?? tab
}

function statusCount(tab: string): number | string {
  if (['items', 'life', 'help', 'broadcast'].includes(module.value) && overview.value) {
    if (tab === '全部') return overview.value.total ?? 0
    const code = tabStatusCode(tab)
    return overview.value.statusCounts?.[code] ?? 0
  }
  if (tab === '全部') return activeTab.value === '全部' ? total.value : ''
  if (activeTab.value === '全部') {
    const code = tabStatusCode(tab)
    return rows.value.filter((row) => row.statusCode === code).length
  }
  // 服务端已按当前 Tab 过滤，其他 Tab 的计数需要额外查询，不在本页猜测。
  return tab === activeTab.value ? total.value : ''
}

async function load() {
  loading.value = true
  try {
    const params: any = { communityId: app.currentCommunityId, page: page.value, pageSize }
    const status = tabStatusCode(activeTab.value)
    if (status) params.status = status
    if (module.value === 'help') {
      const kindCode = HELP_KIND_TABS.find((item) => item.label === helpKind.value)?.code
      if (kindCode) params.kind = kindCode
    }
    if (query.value) params.keyword = query.value
    const overviewModule = ['items', 'life', 'help', 'broadcast'].includes(module.value) ? module.value : ''
    const [data, summary] = await Promise.all([
      operationsApi.list(config.value.api, params),
      overviewModule
        ? operationsApi.overview(overviewModule, { communityId: app.currentCommunityId }).catch(() => null)
        : Promise.resolve(null),
    ])
    rows.value = data.items || []
    total.value = data.total || 0
    overview.value = overviewModule ? summary : null
    if (module.value === 'items' && summary) {
      navBadges.setItemPending(Number(summary.metrics?.pendingReview || 0))
    }
    selectedRows.value = []
  } catch (exc: any) {
    app.showToast(exc?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

function selectTab(tab: string) {
  activeTab.value = tab
  page.value = 1
  load()
}

function selectHelpKind(kind: string) {
  if (helpKind.value === kind) return
  helpKind.value = kind
  page.value = 1
  load()
}

const HOUR_MS = 60 * 60 * 1000

function toLocalInput(ms: number): string {
  const date = new Date(ms)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fromLocalInput(value: string): number | null {
  if (!value) return null
  const timestamp = new Date(value).getTime()
  return Number.isFinite(timestamp) ? timestamp : null
}

function resetBroadcastForm(): void {
  const now = Date.now()
  form.value = {
    title: '',
    subtitle: '',
    type: 'NEW_ITEM',
    content: '',
    important: false,
    effectiveMode: 'IMMEDIATE',
    startAt: toLocalInput(now),
    endAt: toLocalInput(now + 24 * HOUR_MS),
  }
}

function create() {
  broadcastEditTarget.value = null
  resetBroadcastForm()
  drawerOpen.value = true
}

function onBroadcastModeChange(): void {
  const now = Date.now()
  if (form.value.effectiveMode === 'IMMEDIATE') {
    form.value.startAt = toLocalInput(now)
    form.value.endAt = toLocalInput(now + 24 * HOUR_MS)
    return
  }
  const start = fromLocalInput(form.value.startAt)
  const nextStart = start && start > now ? start : now + HOUR_MS
  form.value.startAt = toLocalInput(nextStart)
  form.value.endAt = toLocalInput(nextStart + 24 * HOUR_MS)
}

function openBroadcastEdit(row: any): void {
  broadcastEditTarget.value = row
  const now = Date.now()
  const storedExpiresAt = Number(row.expiresAt || 0)
  const expired = storedExpiresAt > 0 && storedExpiresAt <= now
  const scheduledAt = expired ? now : Number(row.scheduledAt || row.publishedAt || now)
  const expiresAt = expired || !storedExpiresAt ? now + 24 * HOUR_MS : storedExpiresAt
  const storedStatus = String(row.storedStatus || row.status || '')
  form.value = {
    title: row.title || '',
    subtitle: row.subtitle || '',
    type: row.type || 'NEW_ITEM',
    content: row.content || '',
    important: Boolean(row.important),
    effectiveMode: storedStatus === 'SCHEDULED' && scheduledAt > now ? 'SCHEDULED' : 'IMMEDIATE',
    startAt: toLocalInput(scheduledAt),
    endAt: toLocalInput(expiresAt),
  }
  drawerOpen.value = true
}

async function save() {
  const title = form.value.title.trim()
  if (title.length < 2) {
    app.showToast('标题至少 2 个字')
    return
  }
  const endAt = fromLocalInput(form.value.endAt)
  const startAt = fromLocalInput(form.value.startAt)
  if (!endAt) {
    app.showToast('请选择结束时间')
    return
  }
  if (form.value.effectiveMode === 'SCHEDULED' && !startAt) {
    app.showToast('请选择开始时间')
    return
  }
  const effectiveStart = form.value.effectiveMode === 'SCHEDULED' ? startAt : Date.now()
  if (effectiveStart && endAt <= effectiveStart) {
    app.showToast('结束时间必须晚于开始时间')
    return
  }
  const payload = {
    communityId: app.currentCommunityId,
    title,
    subtitle: form.value.subtitle,
    type: form.value.type,
    content: form.value.content,
    important: form.value.important,
    effectiveMode: form.value.effectiveMode,
    startAt: form.value.effectiveMode === 'SCHEDULED' ? startAt : Date.now(),
    endAt,
  }
  try {
    if (broadcastEditTarget.value) {
      await operationsApi.updateBroadcast(broadcastEditTarget.value.id, payload)
      app.showToast('喇叭已更新')
    } else {
      await operationsApi.create(config.value.api, payload)
      app.showToast(form.value.effectiveMode === 'SCHEDULED'
        ? '喇叭已发布，将按时生效'
        : '喇叭已发布并生效')
    }
    drawerOpen.value = false
    broadcastEditTarget.value = null
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function review(row: any) {
  if (module.value === 'items') {
    await openReview(row)
    return
  }
  if (module.value === 'life') {
    await openLifeReview(row)
    return
  }
  if (module.value === 'help') {
    if (row.kindCode === 'OFFER' || row.statusCode === 'PENDING_REVIEW') {
      openHelpReview(row)
      return
    }
    await matchHelpRow(row)
    return
  }
  try {
    await operationsApi.review(config.value.api, row.id, { decision: 'APPROVE' })
    app.showToast('操作已完成')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

/** 邻里服务审核：通过后进入待响应，驳回原因不少于 5 个字。 */
const helpReviewOpen = ref(false)
const helpReviewTarget = ref<any>(null)
const helpReviewDetail = ref<any>(null)
const helpReviewLoading = ref(false)
const helpReviewSubmitting = ref(false)
const helpReviewForm = ref({ decision: 'APPROVE', reason: '' })

async function openHelpReview(row: any) {
  if (!canReviewHelp.value) return
  helpReviewTarget.value = row
  helpReviewDetail.value = null
  helpReviewForm.value = { decision: 'APPROVE', reason: '' }
  helpReviewOpen.value = true
  helpReviewLoading.value = true
  try {
    helpReviewDetail.value = await operationsApi.helpDetail(row.id)
  } catch (exc: any) {
    app.showToast(exc?.message || '互助详情加载失败')
  } finally {
    helpReviewLoading.value = false
  }
}

async function submitHelpReview() {
  const target = helpReviewTarget.value
  if (!target || helpReviewSubmitting.value) return
  const { decision, reason } = helpReviewForm.value
  if (decision === 'REJECT' && reason.trim().length < 5) {
    app.showToast('驳回原因至少 5 个字（将通知发布人）')
    return
  }
  helpReviewSubmitting.value = true
  try {
    await operationsApi.reviewHelp(target.id, decision as 'APPROVE' | 'REJECT', reason.trim())
    helpReviewOpen.value = false
    app.showToast(decision === 'REJECT' ? '已驳回并通知发布人' : '审核通过，已展示在邻里服务')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '审核失败')
  } finally {
    helpReviewSubmitting.value = false
  }
}

async function matchHelpRow(row: any) {
  if (!row.responses) {
    app.showToast('暂无邻居响应，暂时无法撮合')
    return
  }
  try {
    const responses = await operationsApi.helpResponses(row.id)
    const pending = (responses || []).find((item: any) => item.status === 'PENDING')
    if (!pending) {
      app.showToast('没有待处理的响应')
      return
    }
    await operationsApi.matchHelp(row.id, pending.responderId)
    app.showToast('互助撮合成功')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

/** 社区生活审核：移动端投稿必须人工确认，支持通过/驳回并填写原因。 */
const lifeReviewOpen = ref(false)
const lifeReviewTarget = ref<any>(null)
const lifeReviewDetail = ref<any>(null)
const lifeReviewLoading = ref(false)
const lifeReviewSubmitting = ref(false)
const lifeReviewForm = ref({ decision: 'APPROVE', reason: '' })

async function openLifeReview(row: any) {
  lifeReviewTarget.value = row
  lifeReviewDetail.value = null
  lifeReviewForm.value = { decision: 'APPROVE', reason: '' }
  lifeReviewOpen.value = true
  lifeReviewLoading.value = true
  try {
    lifeReviewDetail.value = await operationsApi.lifeDetail(row.id)
  } catch (exc: any) {
    app.showToast(exc?.message || '内容详情加载失败')
  } finally {
    lifeReviewLoading.value = false
  }
}

async function submitLifeReview() {
  const target = lifeReviewTarget.value
  if (!target || lifeReviewSubmitting.value) return
  const { decision, reason } = lifeReviewForm.value
  if (decision === 'REJECT' && reason.trim().length < 5) {
    app.showToast('驳回原因至少 5 个字（将通知发布人）')
    return
  }
  lifeReviewSubmitting.value = true
  try {
    await operationsApi.review('life-posts', target.id, {
      decision,
      reason: reason.trim(),
    })
    lifeReviewOpen.value = false
    app.showToast(decision === 'REJECT' ? '已驳回并通知发布人' : '审核通过，已发布到移动端')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '审核失败')
  } finally {
    lifeReviewSubmitting.value = false
  }
}

/** 物品复核：打开详情抽屉，带 AI 质检报告与通过/驳回/降级结论。 */
async function openReview(row: any) {
  reviewTarget.value = row
  reviewDetail.value = null
  reviewAudit.value = null
  reviewForm.value = { decision: 'APPROVE', reason: '', recommend: false }
  reviewOpen.value = true
  reviewLoading.value = true
  try {
    const [detail, audit] = await Promise.all([
      operationsApi.itemDetail(row.id),
      operationsApi.itemAudit(row.id).catch(() => null),
    ])
    reviewDetail.value = detail
    reviewAudit.value = audit
  } catch (exc: any) {
    app.showToast(exc?.message || '物品详情加载失败')
  } finally {
    reviewLoading.value = false
  }
}

async function submitReview() {
  const target = reviewTarget.value
  if (!target || reviewSubmitting.value) return
  const { decision, reason, recommend } = reviewForm.value
  if (decision === 'REJECT' && reason.trim().length < 5) {
    app.showToast('驳回原因至少 5 个字（将通知卖家）')
    return
  }
  reviewSubmitting.value = true
  try {
    await operationsApi.review('items', target.id, {
      decision,
      reason: reason.trim(),
      recommend: decision === 'APPROVE' ? recommend : false,
    })
    reviewOpen.value = false
    app.showToast(decision === 'REJECT' ? '已驳回并通知卖家' : '复核完成，物品已上架')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '复核失败')
  } finally {
    reviewSubmitting.value = false
  }
}

const offlineOpen = ref(false)
const offlineTarget = ref<any>(null)
const offlineReason = ref('')
const offlineSubmitting = ref(false)

function offline(row: any) {
  offlineTarget.value = row
  offlineReason.value = ''
  offlineOpen.value = true
}

async function submitOffline() {
  const target = offlineTarget.value
  if (!target || offlineSubmitting.value) return
  const reason = offlineReason.value.trim()
  if (module.value === 'items' && reason.length < 2) {
    app.showToast('请填写下架原因（至少 2 个字，将通知卖家）')
    return
  }
  offlineSubmitting.value = true
  try {
    if (module.value === 'help') {
      await operationsApi.closeHelp(target.id, reason)
      app.showToast('互助已关闭')
    } else {
      // 下架接口要求 JSON 请求体，缺失会被服务端判定为参数校验失败
      await operationsApi.offline(config.value.api, target.id, reason)
      app.showToast(module.value === 'items' ? '物品已下架' : '内容已下架')
    }
    offlineOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  } finally {
    offlineSubmitting.value = false
  }
}

const editOpen = ref(false)
const editTarget = ref<any>(null)
const editSubmitting = ref(false)
const editForm = ref({
  title: '',
  qualityDesc: '',
  categoryId: null as number | null,
  tradeType: 'MONETARY',
  priceYuan: '',
  condition: '',
  barterExpect: '',
})

const flatCategories = computed(() => {
  const result: { id: number; name: string }[] = []
  const walk = (nodes: any[]) => {
    for (const node of nodes || []) {
      result.push({ id: Number(node.id), name: node.name })
      walk(node.children || [])
    }
  }
  walk(itemCategories.value)
  return result
})

async function loadCategories() {
  if (itemCategories.value.length) return
  try {
    itemCategories.value = (await operationsApi.itemCategories()) || []
  } catch {
    itemCategories.value = []
  }
}

async function openEdit(row: any) {
  if (!canEditItem.value) return
  editTarget.value = row
  editForm.value = {
    title: row.title || '',
    qualityDesc: row.qualityDesc || row.subtitle || '',
    categoryId: row.categoryId ? Number(row.categoryId) : null,
    tradeType: row.tradeType || 'MONETARY',
    priceYuan: row.tradeType === 'MONETARY' ? String((Number(row.priceCents || 0)) / 100) : '',
    condition: row.condition || '',
    barterExpect: row.barterExpect || '',
  }
  editOpen.value = true
  await loadCategories()
  try {
    const detail = await operationsApi.itemDetail(row.id)
    if (detail && editTarget.value?.id === row.id) {
      editForm.value.qualityDesc = detail.qualityDesc || editForm.value.qualityDesc
      editForm.value.categoryId = detail.categoryId ? Number(detail.categoryId) : editForm.value.categoryId
      editForm.value.barterExpect = detail.barterExpect || editForm.value.barterExpect
    }
  } catch {
    // 详情失败时仍可用列表数据编辑
  }
}

function canEditRow(row: any): boolean {
  if (module.value === 'broadcast') return canEditBroadcast.value
  if (module.value === 'help') return canEditHelp.value
  if (module.value === 'life') return canEditLife.value
  return canEditItem.value && !['RESERVED', 'SOLD', 'GIFTED'].includes(row.statusCode)
}

function canDeleteRow(row: any): boolean {
  if (module.value === 'broadcast') return canDeleteBroadcast.value
  if (module.value === 'help') return canDeleteHelp.value
  if (module.value === 'life') return canDeleteLife.value
  return canDeleteItem.value && !['RESERVED', 'SOLD', 'GIFTED'].includes(row.statusCode)
}

function rowEditLabel(): string {
  if (module.value === 'broadcast') return '编辑喇叭'
  if (module.value === 'help') return '编辑互助'
  return module.value === 'life' ? '编辑内容' : '编辑物品'
}

function rowDeleteLabel(): string {
  if (module.value === 'broadcast') return '删除喇叭'
  if (module.value === 'help') return '删除互助'
  return module.value === 'life' ? '删除内容' : '删除物品'
}

function editRow(row: any): void {
  if (module.value === 'broadcast') {
    openBroadcastEdit(row)
    return
  }
  if (module.value === 'help') {
    void openHelpEdit(row)
    return
  }
  if (module.value === 'life') {
    void openLifeEdit(row)
    return
  }
  void openEdit(row)
}

async function saveEdit() {
  const target = editTarget.value
  if (!target || editSubmitting.value) return
  const form = editForm.value
  const title = form.title.trim()
  if (title.length < 2 || title.length > 30) {
    app.showToast('标题需 2–30 个字')
    return
  }
  if (form.qualityDesc.trim().length < 20) {
    app.showToast('质量说明至少 20 个字')
    return
  }
  if (!form.condition) {
    app.showToast('请选择成色档位')
    return
  }
  if (form.tradeType === 'MONETARY' && Number(form.priceYuan) <= 0) {
    app.showToast('货币交易必须填写价格')
    return
  }
  if (form.tradeType === 'BARTER' && form.barterExpect.trim().length < 2) {
    app.showToast('互换需填写期望交换的物品描述')
    return
  }
  editSubmitting.value = true
  try {
    const payload: any = {
      title,
      qualityDesc: form.qualityDesc.trim(),
      tradeType: form.tradeType,
      condition: form.condition,
      barterExpect: form.barterExpect.trim(),
    }
    if (form.categoryId) payload.categoryId = form.categoryId
    payload.priceCents = form.tradeType === 'MONETARY'
      ? Math.round(Number(form.priceYuan) * 100)
      : 0
    await operationsApi.updateItem(target.id, payload)
    editOpen.value = false
    app.showToast('物品已更新')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  } finally {
    editSubmitting.value = false
  }
}

/** 社区生活编辑：标题、分类、正文、封面与图片/视频均可维护。 */
const lifeEditOpen = ref(false)
const lifeEditTarget = ref<any>(null)
const lifeEditSubmitting = ref(false)
const lifeEditForm = ref({ title: '', category: '', description: '', coverKey: '' })
const lifeEditMedia = ref<LifeMediaItem[]>([])
const lifeMediaUploading = ref(false)
const lifeFileInput = ref<HTMLInputElement | null>(null)

const lifeCategoryOptions = computed(() => {
  const current = lifeEditForm.value.category
  return current && !LIFE_CATEGORIES.includes(current)
    ? [current, ...LIFE_CATEGORIES]
    : LIFE_CATEGORIES
})

const lifeMediaOptions = computed(() => lifeEditMedia.value.map((media, index) => ({
  key: media.key,
  label: `${media.type === 'video' ? '视频' : '图片'} ${index + 1}`,
})))

function buildLifeMedia(row: any): LifeMediaItem[] {
  const keys: string[] = row.mediaKeys || []
  const urls: string[] = row.media || []
  return keys.map((key, index) => ({
    key,
    url: urls[index] || '',
    type: row.mediaType === 'VIDEO' && index === 0 ? 'video' : 'image',
  }))
}

async function openLifeEdit(row: any) {
  if (!canEditLife.value) return
  lifeEditTarget.value = row
  lifeEditForm.value = {
    title: row.title || '',
    category: row.category || '',
    description: row.description || '',
    coverKey: row.coverKey || '',
  }
  lifeEditMedia.value = buildLifeMedia(row)
  lifeEditOpen.value = true
  try {
    const detail = await operationsApi.lifeDetail(row.id)
    if (detail && lifeEditTarget.value?.id === row.id) {
      // 保留列表行的中文状态标签，仅用详情补充媒体与正文。
      lifeEditTarget.value = {
        ...row,
        media: detail.media?.length ? detail.media : row.media,
        mediaKeys: detail.mediaKeys?.length ? detail.mediaKeys : row.mediaKeys,
        mediaType: detail.mediaType || row.mediaType,
      }
      lifeEditMedia.value = buildLifeMedia({
        mediaKeys: detail.mediaKeys?.length ? detail.mediaKeys : row.mediaKeys,
        media: detail.media?.length ? detail.media : row.media,
        mediaType: detail.mediaType || row.mediaType,
      })
      lifeEditForm.value = {
        title: detail.title || lifeEditForm.value.title,
        category: detail.category || lifeEditForm.value.category,
        description: detail.description || lifeEditForm.value.description,
        coverKey: detail.coverKey || lifeEditForm.value.coverKey,
      }
      if (!lifeEditMedia.value.some((media) => media.key === lifeEditForm.value.coverKey)) {
        lifeEditForm.value.coverKey = lifeEditMedia.value[0]?.key || ''
      }
    }
  } catch {
    // 详情失败时仍可用列表数据编辑
  }
}

function removeLifeMedia(index: number): void {
  const [removed] = lifeEditMedia.value.splice(index, 1)
  if (removed && lifeEditForm.value.coverKey === removed.key) {
    lifeEditForm.value.coverKey = lifeEditMedia.value[0]?.key || ''
  }
}

function triggerLifeMediaUpload(): void {
  if (lifeMediaUploading.value) return
  lifeFileInput.value?.click()
}

/** 追加媒体：图片最多 12 张；短视频只能单独存在。 */
async function onLifeMediaPicked(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  for (const file of files) {
    const name = file.name.toLowerCase()
    const isVideo = file.type.startsWith('video/') || /\.(mp4|mov|webm)$/.test(name)
    const isImage = file.type.startsWith('image/') || /\.(jpe?g|png|webp)$/.test(name)
    if (!isVideo && !isImage) {
      app.showToast(`「${file.name}」仅支持 JPG / PNG / WebP 图片或 MP4 / MOV / WebM 短视频`)
      continue
    }
    if (isVideo) {
      if (lifeEditMedia.value.length > 0) {
        app.showToast('短视频动态只能包含一个视频，请先移除其他媒体')
        continue
      }
    } else {
      if (lifeEditMedia.value.some((media) => media.type === 'video')) {
        app.showToast('图文动态不能与短视频混排，请先移除视频')
        continue
      }
      if (lifeEditMedia.value.length >= 12) {
        app.showToast('图文动态最多上传 12 张图片')
        break
      }
    }
    lifeMediaUploading.value = true
    try {
      const data = await filesApi.uploadMedia(file, isVideo ? 'LIFE_VIDEO' : 'LIFE_IMAGE')
      const item: LifeMediaItem = {
        key: data.objectKey,
        url: data.url || data.objectKey,
        type: isVideo ? 'video' : 'image',
      }
      lifeEditMedia.value.push(item)
      if (!lifeEditForm.value.coverKey) lifeEditForm.value.coverKey = item.key
    } catch (exc: any) {
      app.showToast(exc?.message || `「${file.name}」上传失败`)
    } finally {
      lifeMediaUploading.value = false
    }
  }
}

async function saveLifeEdit() {
  const target = lifeEditTarget.value
  if (!target || lifeEditSubmitting.value) return
  if (lifeMediaUploading.value) {
    app.showToast('媒体上传中，请稍候')
    return
  }
  const form = lifeEditForm.value
  const title = form.title.trim()
  const category = form.category.trim()
  const description = form.description.trim()
  if (title.length < 2 || title.length > 30) {
    app.showToast('标题需 2–30 个字')
    return
  }
  if (!category) {
    app.showToast('请选择内容分类')
    return
  }
  if (description.length > 500) {
    app.showToast('正文最多 500 个字')
    return
  }
  if (!lifeEditMedia.value.length) {
    app.showToast('请至少保留一张图片或一个视频')
    return
  }
  const hasVideo = lifeEditMedia.value.some((media) => media.type === 'video')
  if (hasVideo && lifeEditMedia.value.length > 1) {
    app.showToast('短视频动态只能包含一个视频')
    return
  }
  const mediaKeys = lifeEditMedia.value.map((media) => media.key)
  const coverKey = mediaKeys.includes(form.coverKey) ? form.coverKey : mediaKeys[0]
  lifeEditSubmitting.value = true
  try {
    await operationsApi.updateLife(target.id, {
      title,
      category,
      description,
      media: mediaKeys,
      mediaType: hasVideo ? 'VIDEO' : 'GALLERY',
      coverKey,
    })
    lifeEditOpen.value = false
    app.showToast('内容已更新')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  } finally {
    lifeEditSubmitting.value = false
  }
}

/** 邻里互助/服务编辑：发布类型与全部业务字段、图片/视频均可维护。 */
const helpEditOpen = ref(false)
const helpEditTarget = ref<any>(null)
const helpEditSubmitting = ref(false)
const helpEditForm = ref({
  kind: 'HELP',
  category: '',
  title: '',
  description: '',
  expectedTime: '',
  location: '',
  reward: '',
  coverKey: '',
})
const helpEditMedia = ref<LifeMediaItem[]>([])
const helpMediaUploading = ref(false)
const helpFileInput = ref<HTMLInputElement | null>(null)
const helpMediaType = ref<'gallery' | 'video'>('gallery')
const helpCategoryCustomMode = ref(false)
const helpTimePickerOpen = ref(false)
const helpTimePickerMode = ref<'specific' | 'range'>('specific')
const helpTimePickerDate = ref('')
const helpTimePickerStart = ref('')
const helpTimePickerEnd = ref('')

const HELP_KIND_OPTIONS = [
  { value: 'HELP', label: '邻里求助' },
  { value: 'OFFER', label: '邻里服务' },
]
const HELP_CATEGORIES = ['接送照看', '宠物照看', '学习陪伴', '邻里活动', '维修安装', '其他']
const HELP_REWARD_OPTIONS: Record<string, string[]> = {
  HELP: ['邻里互助', '红包答谢', '酬谢可议'],
  OFFER: ['免费帮忙', '邻里价', '按次收费', '面议'],
}
const HELP_TIME_SLOTS = Array.from(
  { length: 16 },
  (_, index) => `${String(index + 7).padStart(2, '0')}:00`,
)
const helpCategoryOptions = computed(() => {
  const current = helpEditForm.value.category.trim()
  return current && !helpCategoryCustomMode.value && !HELP_CATEGORIES.includes(current)
    ? [current, ...HELP_CATEGORIES]
    : HELP_CATEGORIES
})
const helpRewardOptions = computed(
  () => HELP_REWARD_OPTIONS[helpEditForm.value.kind] || HELP_REWARD_OPTIONS.HELP,
)
const helpVisibleMedia = computed(() => helpEditMedia.value.filter(
  (media) => media.type === (helpMediaType.value === 'video' ? 'video' : 'image'),
))
const helpDateChoices = computed(() => buildHelpDateOptions())
const helpEndTimeChoices = computed(() => {
  const startIndex = HELP_TIME_SLOTS.indexOf(helpTimePickerStart.value)
  return startIndex >= 0 ? HELP_TIME_SLOTS.slice(startIndex + 1) : []
})
const helpTitlePlaceholder = computed(() => (
  helpEditForm.value.kind === 'HELP'
    ? '例如：今天临时加班，求帮忙接孩子'
    : '例如：退休教师，可辅导小学语文'
))
const helpDescriptionPlaceholder = computed(() => (
  helpEditForm.value.kind === 'HELP'
    ? '说明具体情况、时间、注意事项，方便邻居判断能否帮忙'
    : '介绍你的经验、可提供的服务和注意事项'
))
const helpLocationPlaceholder = computed(() => (
  helpEditForm.value.kind === 'HELP'
    ? '例如：实验小学北门 / 8号楼大堂'
    : '例如：阳光花园及周边 1 公里'
))
const helpRewardPlaceholder = computed(() => (
  helpEditForm.value.kind === 'HELP'
    ? '也可补充具体金额或酬谢说明'
    : '也可补充具体报价或计费方式'
))

function isVideoMediaKey(key: string): boolean {
  return /\.(mp4|mov|webm|m4v)(\?|$)/i.test(key)
}

function buildHelpMedia(row: any): LifeMediaItem[] {
  const keys: string[] = row.mediaKeys || []
  const urls: string[] = row.media || []
  return keys.map((key, index) => ({
    key,
    url: urls[index] || '',
    type: isVideoMediaKey(key) ? 'video' : 'image',
  }))
}

async function openHelpEdit(row: any) {
  if (!canEditHelp.value) return
  helpEditTarget.value = row
  const kind = row.kindCode === 'OFFER' ? 'OFFER' : 'HELP'
  helpEditForm.value = {
    kind,
    category: row.category || '',
    title: row.title || '',
    description: row.description || '',
    expectedTime: row.expectedTime || '',
    location: row.location || '',
    reward: row.reward || '',
    coverKey: row.coverKey || '',
  }
  helpEditMedia.value = buildHelpMedia(row)
  helpMediaType.value = row.mediaType === 'VIDEO'
    || helpEditMedia.value.some((media) => media.type === 'video') ? 'video' : 'gallery'
  helpCategoryCustomMode.value = Boolean(
    helpEditForm.value.category && !HELP_CATEGORIES.includes(helpEditForm.value.category),
  )
  helpTimePickerOpen.value = false
  helpEditOpen.value = true
  try {
    const detail = await operationsApi.helpDetail(row.id)
    if (!detail || helpEditTarget.value?.id !== row.id) return
    const detailKind = detail.kindCode || detail.kind
    helpEditForm.value = {
      kind: detailKind === 'OFFER' ? 'OFFER' : helpEditForm.value.kind,
      category: detail.category || helpEditForm.value.category,
      title: detail.title || helpEditForm.value.title,
      description: detail.description || helpEditForm.value.description,
      expectedTime: detail.expectedTime || helpEditForm.value.expectedTime,
      location: detail.location || helpEditForm.value.location,
      reward: detail.reward || helpEditForm.value.reward,
      coverKey: detail.coverKey || helpEditForm.value.coverKey,
    }
    helpEditMedia.value = buildHelpMedia(detail)
    helpMediaType.value = detail.mediaType === 'VIDEO'
      || helpEditMedia.value.some((media) => media.type === 'video') ? 'video' : 'gallery'
    helpCategoryCustomMode.value = Boolean(
      helpEditForm.value.category && !HELP_CATEGORIES.includes(helpEditForm.value.category),
    )
    if (!helpEditMedia.value.some((media) => media.key === helpEditForm.value.coverKey)) {
      helpEditForm.value.coverKey = helpEditMedia.value[0]?.key || ''
    }
  } catch {
    // 详情失败时仍可基于列表行编辑
  }
}

function buildHelpDateOptions(): Array<{ label: string; value: string }> {
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']
  const now = new Date()
  const options: Array<{ label: string; value: string }> = []
  for (let offset = 0; offset < 14; offset += 1) {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset)
    const value = `${date.getMonth() + 1}月${date.getDate()}日`
    const relative = offset === 0 ? '（今天）' : offset === 1 ? '（明天）' : ''
    options.push({ label: `${value} 周${weekdays[date.getDay()]}${relative}`, value })
  }
  return options
}

function selectHelpEditKind(kind: string): void {
  if (helpEditForm.value.kind === kind) return
  helpEditForm.value.kind = kind
  helpEditForm.value.expectedTime = ''
  helpEditForm.value.reward = ''
  helpTimePickerOpen.value = false
}

function selectHelpCategory(category: string): void {
  if (!category) {
    helpEditForm.value.category = ''
    helpCategoryCustomMode.value = false
    return
  }
  helpCategoryCustomMode.value = category === '其他'
  helpEditForm.value.category = category === '其他' ? '' : category
}

function selectHelpMediaType(type: 'gallery' | 'video'): void {
  helpMediaType.value = type
}

function openHelpTimePicker(mode: 'specific' | 'range'): void {
  helpTimePickerMode.value = mode
  helpTimePickerDate.value = helpDateChoices.value[0]?.value ?? ''
  helpTimePickerStart.value = ''
  helpTimePickerEnd.value = ''
  helpTimePickerOpen.value = true
}

function selectHelpTimeDate(date: string): void {
  if (helpTimePickerDate.value === date) return
  helpTimePickerDate.value = date
  helpTimePickerStart.value = ''
  helpTimePickerEnd.value = ''
}

function selectHelpTimeStart(time: string): void {
  helpTimePickerStart.value = time
  helpTimePickerEnd.value = ''
  if (helpTimePickerMode.value === 'specific') {
    helpEditForm.value.expectedTime = `${helpTimePickerDate.value} ${time}`
    helpTimePickerOpen.value = false
  }
}

function selectHelpTimeEnd(time: string): void {
  if (!helpTimePickerStart.value || time <= helpTimePickerStart.value) return
  helpTimePickerEnd.value = time
  helpEditForm.value.expectedTime =
    `${helpTimePickerDate.value} ${helpTimePickerStart.value}–${time}`
  helpTimePickerOpen.value = false
}

function clearHelpTime(closePicker = false): void {
  helpEditForm.value.expectedTime = ''
  helpTimePickerStart.value = ''
  helpTimePickerEnd.value = ''
  if (closePicker) helpTimePickerOpen.value = false
}

function removeHelpMedia(key: string): void {
  const index = helpEditMedia.value.findIndex((media) => media.key === key)
  if (index < 0) return
  const [removed] = helpEditMedia.value.splice(index, 1)
  if (removed && helpEditForm.value.coverKey === removed.key) {
    helpEditForm.value.coverKey = helpVisibleMedia.value[0]?.key || helpEditMedia.value[0]?.key || ''
  }
}

function triggerHelpMediaUpload(): void {
  if (helpMediaUploading.value) return
  helpFileInput.value?.click()
}

async function onHelpMediaPicked(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  for (const file of files) {
    const name = file.name.toLowerCase()
    const isVideo = file.type.startsWith('video/') || /\.(mp4|mov|webm)$/.test(name)
    const isImage = file.type.startsWith('image/') || /\.(jpe?g|png|webp)$/.test(name)
    if (!isVideo && !isImage) {
      app.showToast(`「${file.name}」仅支持 JPG / PNG / WebP 图片或 MP4 / MOV / WebM 短视频`)
      continue
    }
    if (helpMediaType.value === 'video' && !isVideo) {
      app.showToast('当前为短视频模式，请切换为照片集后上传图片')
      continue
    }
    if (helpMediaType.value === 'gallery' && !isImage) {
      app.showToast('当前为照片集模式，请切换为短视频后上传视频')
      continue
    }
    if (isVideo && helpEditMedia.value.some((media) => media.type === 'video')) {
      app.showToast('短视频互助只能包含一个视频，请先移除已有视频')
      continue
    }
    if (isImage && helpEditMedia.value.filter((media) => media.type === 'image').length >= 9) {
      app.showToast('图片最多上传 9 张')
      break
    }
    helpMediaUploading.value = true
    try {
      const data = await filesApi.uploadMedia(file, isVideo ? 'LIFE_VIDEO' : 'LIFE_IMAGE')
      const item: LifeMediaItem = {
        key: data.objectKey,
        url: data.url || data.objectKey,
        type: isVideo ? 'video' : 'image',
      }
      helpEditMedia.value.push(item)
      if (!helpEditForm.value.coverKey) helpEditForm.value.coverKey = item.key
    } catch (exc: any) {
      app.showToast(exc?.message || `「${file.name}」上传失败`)
    } finally {
      helpMediaUploading.value = false
    }
  }
}

async function saveHelpEdit() {
  const target = helpEditTarget.value
  if (!target || helpEditSubmitting.value) return
  if (helpMediaUploading.value) {
    app.showToast('媒体上传中，请稍候')
    return
  }
  const form = helpEditForm.value
  const title = form.title.trim()
  const category = form.category.trim()
  const description = form.description.trim()
  if (title.length < 2 || title.length > 30) {
    app.showToast('标题需 2–30 个字')
    return
  }
  if (description.length < 5) {
    app.showToast('请补充至少 5 个字的详细说明')
    return
  }
  if (description.length > 500) {
    app.showToast('详细说明最多 500 个字')
    return
  }
  if (form.location.trim().length > 64 || form.expectedTime.trim().length > 64) {
    app.showToast('时间与地点最多 64 个字')
    return
  }
  const mediaType = helpMediaType.value === 'video' ? 'VIDEO' : 'GALLERY'
  const mediaList = helpVisibleMedia.value
  if (mediaType === 'VIDEO' && mediaList.length > 1) {
    app.showToast('短视频互助只能包含一个视频')
    return
  }
  if (mediaType === 'GALLERY' && mediaList.length > 9) {
    app.showToast('图片最多上传 9 张')
    return
  }
  const mediaKeys = mediaList.map((media) => media.key)
  const coverKey = mediaKeys.includes(form.coverKey) ? form.coverKey : (mediaKeys[0] || '')
  helpEditSubmitting.value = true
  try {
    await operationsApi.updateHelp(target.id, {
      kind: form.kind,
      category,
      title,
      description,
      expectedTime: form.expectedTime.trim(),
      location: form.location.trim(),
      reward: form.reward.trim(),
      media: mediaKeys,
      mediaType,
      coverKey,
    })
    helpEditOpen.value = false
    app.showToast('互助信息已更新')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  } finally {
    helpEditSubmitting.value = false
  }
}

async function confirmDelete(row: any): Promise<void> {
  const isBroadcast = module.value === 'broadcast'
  const isLife = module.value === 'life'
  const isHelp = module.value === 'help'
  const confirmed = await confirm({
    title: isBroadcast ? '删除喇叭' : isHelp ? '删除互助' : isLife ? '删除内容' : '删除物品',
    message: isBroadcast
      ? `确定删除“${row.title}”吗？删除后不可恢复，移动端喇叭站将立即移除。`
      : isHelp
      ? `确定删除“${row.title}”吗？删除后不可恢复，邻居响应记录将一并清理。`
      : isLife
      ? `确定删除“${row.title}”吗？删除后不可恢复，内容评论与收藏记录将一并清理。`
      : `确定删除“${row.title}”吗？删除后不可恢复，物品照片、质检记录与留言将一并清理。`,
    details: [isBroadcast
      ? '删除会同时清理该喇叭的收藏记录，并写入审计日志。'
      : isHelp
      ? '删除操作会通知发布人，并写入审计日志。'
      : isLife
      ? '若仅需停止展示，请改用「下架内容」保留运营数据；删除记录仍会写入审计日志。'
      : '若物品已有订单记录，系统会拒绝删除，请改用「下架物品」保留交易凭证。'],
    confirmText: '确认删除',
    danger: true,
  })
  if (!confirmed) return
  try {
    if (isBroadcast) {
      await operationsApi.deleteBroadcast(row.id)
      app.showToast('喇叭已删除')
    } else if (isHelp) {
      await operationsApi.deleteHelp(row.id)
      app.showToast('互助信息已删除')
    } else if (isLife) {
      await operationsApi.deleteLife(row.id)
      app.showToast('内容已删除')
    } else {
      await operationsApi.deleteItem(row.id)
      app.showToast('物品已删除')
    }
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

function selectAll(event: Event) {
  selectedRows.value = (event.target as HTMLInputElement).checked ? rows.value.map((row) => row.id) : []
}

function toggleRow(id: string) {
  selectedRows.value = selectedRows.value.includes(id)
    ? selectedRows.value.filter((value) => value !== id)
    : [...selectedRows.value, id]
}

async function batchDeleteHelp(): Promise<void> {
  if (!selectedRows.value.length || !canDeleteHelp.value) return
  const confirmed = await confirm({
    title: '批量删除互助',
    message: `确定删除已选择的 ${selectedRows.value.length} 条互助/服务信息吗？删除后不可恢复。`,
    details: ['每条删除都会通知发布人并写入审计日志；失败项会在完成后提示。'],
    confirmText: '确认删除',
    danger: true,
  })
  if (!confirmed) return
  try {
    const result = await operationsApi.batchDeleteHelp(selectedRows.value)
    const failed = result?.failed?.length || 0
    app.showToast(failed ? `已删除 ${result.deleted.length} 条，${failed} 条失败` : `已删除 ${result.deleted.length} 条`)
    selectedRows.value = []
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '批量删除失败')
  }
}

async function batchDeleteBroadcasts(): Promise<void> {
  if (!selectedRows.value.length || !canDeleteBroadcast.value) return
  const confirmed = await confirm({
    title: '批量删除喇叭',
    message: `确定删除已选择的 ${selectedRows.value.length} 条喇叭吗？删除后不可恢复。`,
    details: ['移动端喇叭站将立即移除已删除内容；失败项会在完成后提示。'],
    confirmText: '确认删除',
    danger: true,
  })
  if (!confirmed) return
  try {
    const result = await operationsApi.batchDeleteBroadcasts(selectedRows.value)
    const failed = result?.failed?.length || 0
    app.showToast(failed
      ? `已删除 ${result.deleted.length} 条，${failed} 条失败`
      : `已删除 ${result.deleted.length} 条`)
    selectedRows.value = []
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '批量删除失败')
  }
}

/** 主操作只在服务端状态机允许的源状态下展示，避免点击后 40904。 */
function canPrimaryAction(row: any): boolean {
  if (module.value === 'help') {
    if (row.kindCode === 'OFFER' && row.statusCode === 'PENDING_REVIEW') return true
    return row.kindCode === 'HELP'
      && ['OPEN', 'MATCHING'].includes(row.statusCode)
      && Number(row.responses || 0) > 0
  }
  if (module.value === 'items') return row.statusCode === 'PENDING_REVIEW'
  return row.statusCode === 'PENDING_REVIEW'
}

function canOffline(row: any): boolean {
  if (module.value === 'items') return !ITEM_OFFLINE_BLOCKED.includes(row.statusCode)
  if (module.value === 'help') return ['OPEN', 'MATCHING', 'IN_PROGRESS'].includes(row.statusCode)
  // 内容状态机只允许 定时发布/已发布 → 已下线；待审核内容应先审核或删除。
  return ['SCHEDULED', 'PUBLISHED'].includes(row.statusCode)
}

function rowActionIcon(row: any) {
  if (module.value === 'help') {
    return row.kindCode === 'OFFER' || row.statusCode === 'PENDING_REVIEW' ? ShieldCheck : HandHeart
  }
  return ShieldCheck
}

function rowActionLabel(row: any) {
  if (module.value === 'help') {
    return row.kindCode === 'OFFER' || row.statusCode === 'PENDING_REVIEW' ? '审核服务' : '人工撮合'
  }
  if (module.value === 'items') return '审核物品'
  return row.statusCode === 'PENDING_REVIEW' ? '审核内容' : '查看内容'
}

function rowOfflineLabel() {
  if (module.value === 'items') return '下架物品'
  return module.value === 'help' ? '关闭互助' : '下架内容'
}

function rowOfflineIcon() {
  // 「下架」类操作全局统一使用 ArchiveX；互助的「关闭」语义使用 CircleX。
  return module.value === 'help' ? CircleX : ArchiveX
}

/** 待办铃铛会带 ?tab=PENDING_REVIEW 跳转，直接落到待审核列表。 */
function applyRouteTab(): void {
  if (module.value === 'help') {
    const requestedKind = String(route.query.kind || '').toUpperCase()
    const map: Record<string, string> = {
      HELP: '邻里求助', '求助': '邻里求助',
      OFFER: '邻里服务', '提供': '邻里服务', '服务': '邻里服务',
    }
    if (map[requestedKind]) helpKind.value = map[requestedKind]
  }
  const requested = String(route.query.tab || '')
  if (!requested) return
  const label = tabs.value.includes(requested)
    ? requested
    : tabs.value.find((tab: string) => tabStatusCode(tab) === requested)
  if (label) activeTab.value = label
}

onMounted(() => {
  applyRouteTab()
  load()
})
watch(() => route.fullPath, () => {
  activeTab.value = '全部'
  helpKind.value = '全部'
  query.value = ''
  page.value = 1
  applyRouteTab()
  load()
})
watch(() => app.currentCommunityId, () => {
  page.value = 1
  load()
})
</script>

<template>
  <CommunityFilterBar :owner-label="config.ownerLabel" :scope-note="config.scopeNote" />

  <section class="community-operation-metrics">
    <div v-for="metric in metrics" :key="metric.label">
      <span>{{ metric.label }}</span>
      <strong>{{ metric.value }}</strong>
      <em :class="{ attention: metric.attention }">{{ metric.note }}</em>
    </div>
  </section>

  <section class="community-operation-panel">
    <div v-if="module === 'help'" class="community-operation-kind-tabs">
      <button
        v-for="kind in HELP_KIND_TABS"
        :key="kind.label"
        :class="{ active: helpKind === kind.label }"
        @click="selectHelpKind(kind.label)"
      >
        {{ kind.label }}
      </button>
    </div>
    <div class="community-operation-tabs">
      <button v-for="tab in tabs" :key="tab" :class="{ active: activeTab === tab }" @click="selectTab(tab)">
        {{ tab }}<em>{{ statusCount(tab) }}</em>
      </button>
    </div>
    <div class="community-operation-toolbar">
      <div class="table-search">
        <Search :size="17" />
        <input v-model="query" :placeholder="`搜索${config.title}标题、发布人或分类…`" @keyup.enter="load" />
      </div>
      <div>
        <button><SlidersHorizontal :size="16" />高级筛选</button>
        <button v-if="canCreate" class="primary-button" @click="create"><Plus :size="16" />{{ config.create }}</button>
      </div>
    </div>
    <div v-if="selectedRows.length" class="batch-bar community-operation-batch">
      <span>已选择 <strong>{{ selectedRows.length }}</strong> 项</span>
      <button v-if="module === 'broadcast' && canDeleteBroadcast" class="danger-button" @click="batchDeleteBroadcasts">
        批量删除
      </button>
      <button v-else-if="module === 'help' && canDeleteHelp" class="danger-button" @click="batchDeleteHelp">
        批量删除
      </button>
      <button v-else @click="app.showToast('批量状态变更已完成')">批量变更状态</button>
      <button @click="selectedRows = []">取消选择</button>
    </div>
    <div class="table-wrap community-operation-table-wrap">
      <table class="community-operation-table">
        <thead>
          <tr>
            <th><input type="checkbox" :checked="rows.length > 0 && selectedRows.length === rows.length" @change="selectAll" /></th>
            <th>内容信息</th><th>发布人 / 来源</th><th>内容分类</th><th>运营表现</th><th>状态</th><th>更新时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredRows" :key="row.id">
            <td><input type="checkbox" :checked="selectedRows.includes(row.id)" @change="toggleRow(row.id)" /></td>
            <td>
              <div class="operation-content-cell">
                <span :class="config.tone"><component :is="config.icon" :size="16" /></span>
                <div><strong :title="row.title">{{ row.title }}</strong><em :title="row.subtitle">{{ row.code }} · {{ row.subtitle }}</em></div>
              </div>
            </td>
            <td><span class="cell-ellipsis md" :title="row.owner">{{ row.owner }}</span></td>
            <td><span class="operation-category cell-ellipsis sm" :title="row.category">{{ row.category }}</span></td>
            <td><span class="operation-performance cell-ellipsis md" :title="row.performance">{{ row.performance }}</span></td>
            <td><StatusBadge :value="row.status" /></td>
            <td>{{ row.updatedAt }}</td>
            <td>
              <div class="row-actions">
                <button v-if="canPrimaryAction(row)" class="row-icon-button" :aria-label="rowActionLabel(row)" :data-tip="rowActionLabel(row)" @click="review(row)">
                  <component :is="rowActionIcon(row)" :size="15" />
                </button>
                <button v-if="canEditRow(row)" class="row-icon-button" :aria-label="rowEditLabel()" :data-tip="rowEditLabel()" @click="editRow(row)">
                  <Pencil :size="15" />
                </button>
                <button v-if="canOffline(row)" class="row-icon-button danger" :aria-label="rowOfflineLabel()" :data-tip="rowOfflineLabel()" @click="offline(row)">
                  <component :is="rowOfflineIcon()" :size="15" />
                </button>
                <button v-if="canDeleteRow(row)" class="row-icon-button danger" :aria-label="rowDeleteLabel()" :data-tip="rowDeleteLabel()" @click="confirmDelete(row)">
                  <Trash2 :size="15" />
                </button>
                <span v-if="!canPrimaryAction(row) && !canOffline(row) && !canEditRow(row) && !canDeleteRow(row)" class="cell-ellipsis sm">—</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" />
    </div>
    <div class="community-operation-footer">
      <span>共 {{ total }} 条内容 · 数据每 5 分钟同步至移动端</span>
      <div>
        <button :disabled="page <= 1" @click="page--; load()">上一页</button>
        <button class="current">1</button>
        <button @click="page++; load()">下一页</button>
      </div>
    </div>
  </section>

  <NiDrawer
    :open="drawerOpen"
    :title="broadcastEditTarget ? '编辑喇叭' : '发布喇叭'"
    eyebrow="社区喇叭"
    @close="drawerOpen = false"
  >
    <div class="form-grid">
      <label class="full"><span>标题 *</span><input v-model="form.title" maxlength="120" placeholder="请输入喇叭标题" /></label>
      <label class="full"><span>副标题 / 摘要</span><input v-model="form.subtitle" maxlength="255" placeholder="如：今晚 19:30 · 中心广场" /></label>
      <label>
        <span>喇叭类型</span>
        <select v-model="form.type">
          <option v-for="item in BROADCAST_TYPES" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <label>
        <span>生效方式</span>
        <select v-model="form.effectiveMode" @change="onBroadcastModeChange">
          <option value="IMMEDIATE">即时生效</option>
          <option value="SCHEDULED">指定时间段</option>
        </select>
      </label>
      <label v-if="form.effectiveMode === 'SCHEDULED'">
        <span>开始时间 *</span>
        <input v-model="form.startAt" type="datetime-local" />
      </label>
      <label>
        <span>结束时间 *</span>
        <input v-model="form.endAt" type="datetime-local" />
      </label>
      <label class="full broadcast-important">
        <span style="display: flex; align-items: center; gap: 8px">
          <input v-model="form.important" type="checkbox" style="width: auto" />
          设为重要喇叭（移动端优先展示）
        </span>
      </label>
      <label class="full"><span>正文</span><textarea v-model="form.content" placeholder="请输入喇叭详细内容" /></label>
    </div>
    <p style="margin-top: 12px; color: #958b9f; font-size: var(--font-size-caption)">
      发布后无需审批立即生效；未单独设置时默认生效 24 小时。指定时间段会在到点后自动生效，到期自动下架。
    </p>
    <template #footer>
      <button @click="drawerOpen = false">取消</button>
      <button class="primary-button" @click="save">{{ broadcastEditTarget ? '保存修改' : '发布' }}</button>
    </template>
  </NiDrawer>

  <NiDrawer
    :open="reviewOpen"
    :title="reviewTarget ? `物品复核 · ${reviewTarget.title}` : '物品复核'"
    eyebrow="社区物品"
    @close="reviewOpen = false"
  >
    <template v-if="reviewTarget">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <ShieldCheck :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">
            {{ reviewTarget.code }} · {{ reviewTarget.communityName }}
          </span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ reviewTarget.title }}</strong>
        </div>
        <StatusBadge :value="reviewTarget.status" />
      </div>

      <h4 class="section-title">物品信息</h4>
      <div class="form-grid">
        <label><span>发布人</span><input :value="reviewTarget.seller" disabled /></label>
        <label><span>分类 / 成色</span><input :value="`${reviewTarget.category || '—'} · ${reviewTarget.condition || '—'}`" disabled /></label>
        <label><span>交易方式</span><input :value="mapTradeType(reviewTarget.tradeType)" disabled /></label>
        <label><span>价格</span><input :value="reviewTarget.price" disabled /></label>
      </div>

      <h4 class="section-title" style="margin-top: 20px">质量说明</h4>
      <p style="color: #554761; font-size: var(--font-size-body); line-height: 1.7">
        {{ reviewDetail?.qualityDesc || reviewTarget.subtitle || '—' }}
      </p>

      <h4 class="section-title" style="margin-top: 20px">实拍照片</h4>
      <div v-if="reviewDetail?.media?.length" style="display: flex; flex-wrap: wrap; gap: 8px">
        <template v-for="media in reviewDetail.media" :key="media.objectKey">
          <a v-if="media.mediaType === 'IMAGE' && media.url" :href="media.url" target="_blank" rel="noopener">
            <img :src="media.url" alt="物品照片" style="width: 76px; height: 76px; object-fit: cover; border: 1px solid #ebe9ef; border-radius: 8px" />
          </a>
        </template>
      </div>
      <p v-else style="color: #988da2; font-size: var(--font-size-body)">无照片</p>

      <h4 class="section-title" style="margin-top: 20px">AI 质检报告</h4>
      <p v-if="reviewLoading" style="color: #988da2">正在加载 AI 质检报告…</p>
      <template v-else-if="reviewAudit">
        <div class="form-grid">
          <label><span>总体结论</span><input :value="reviewAudit.overall" disabled /></label>
          <label><span>置信度</span><input :value="`${Math.round(Number(reviewAudit.confidence || 0) * 100)}%`" disabled /></label>
        </div>
        <div style="margin-top: 10px; display: flex; flex-direction: column; gap: 6px">
          <div v-for="dimension in reviewAudit.dimensions || []" :key="dimension.name"
            style="display: flex; gap: 10px; align-items: baseline; color: #554761; font-size: var(--font-size-body)">
            <strong style="min-width: 84px">{{ dimension.name }}</strong>
            <span>{{ dimension.score ?? (dimension.pass === false ? '未通过' : '通过') }}</span>
            <em style="color: #958b9f; font-style: normal">
              {{ (dimension.issues || dimension.conflicts || dimension.labels || []).join('；') || dimension.value || '正常' }}
            </em>
          </div>
        </div>
        <p v-if="reviewAudit.risks?.length" style="margin-top: 8px; color: #c08a35; font-size: var(--font-size-caption)">
          风险：{{ reviewAudit.risks.join('；') }}
        </p>
        <p v-if="reviewAudit.suggestions?.length" style="margin-top: 4px; color: #958b9f; font-size: var(--font-size-caption)">
          改进建议：{{ reviewAudit.suggestions.join('；') }}
        </p>
      </template>
      <p v-else style="color: #988da2; font-size: var(--font-size-body)">暂无 AI 质检记录</p>

      <h4 class="section-title" style="margin-top: 20px">复核结论</h4>
      <div style="display: flex; flex-wrap: wrap; gap: 8px">
        <button v-for="option in reviewDecisions" :key="option.value"
          :class="{ 'primary-button': reviewForm.decision === option.value }"
          @click="reviewForm.decision = option.value">
          {{ option.label }}
        </button>
      </div>
      <label class="full" style="display: block; margin-top: 12px">
        <span style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 4px">
          复核备注{{ reviewForm.decision === 'REJECT' ? '（驳回必填，≥5 字，将通知卖家）' : '（选填）' }}
        </span>
        <textarea v-model="reviewForm.reason" style="width: 100%; min-height: 72px"
          placeholder="例如：照片无法看清瑕疵处，请补充特写照片后重新提交" />
      </label>
      <label v-if="reviewForm.decision === 'APPROVE'" style="display: flex; align-items: center; gap: 8px; margin-top: 12px; color: #554761">
        <input v-model="reviewForm.recommend" type="checkbox" />
        <span>加入热门推荐位</span>
      </label>
    </template>
    <template #footer>
      <button @click="reviewOpen = false">取消</button>
      <button class="primary-button" :disabled="reviewSubmitting" @click="submitReview">
        {{ reviewSubmitting ? '提交中…' : '提交复核结论' }}
      </button>
    </template>
  </NiDrawer>

  <NiDrawer
    :open="helpReviewOpen"
    :title="helpReviewTarget ? `邻里服务审核 · ${helpReviewTarget.title}` : '邻里服务审核'"
    eyebrow="邻里互助"
    @close="helpReviewOpen = false"
  >
    <template v-if="helpReviewTarget">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <HandHeart :size="18" style="color: #7955b8" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">
            {{ helpReviewTarget.code }} · {{ helpReviewTarget.communityName }} · {{ helpReviewTarget.requester }}
          </span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ helpReviewTarget.title }}</strong>
        </div>
        <StatusBadge :value="helpReviewTarget.status" />
      </div>

      <p v-if="helpReviewLoading" style="color: #988da2">正在加载服务详情…</p>
      <template v-else>
        <div class="form-grid">
          <label><span>发布类型</span><input :value="helpReviewDetail?.kindLabel || helpReviewTarget.kindLabel" disabled /></label>
          <label><span>分类</span><input :value="helpReviewDetail?.category || helpReviewTarget.category" disabled /></label>
          <label><span>可服务时间</span><input :value="helpReviewDetail?.expectedTime || helpReviewTarget.expectedTime || '—'" disabled /></label>
          <label><span>服务地点 / 范围</span><input :value="helpReviewDetail?.location || helpReviewTarget.location || '—'" disabled /></label>
          <label><span>收费方式</span><input :value="helpReviewDetail?.reward || helpReviewTarget.reward || '—'" disabled /></label>
          <label><span>紧急</span><input :value="(helpReviewDetail?.urgent ?? helpReviewTarget.urgent) ? '是' : '否'" disabled /></label>
        </div>

        <h4 class="section-title" style="margin-top: 20px">详细说明</h4>
        <p style="color: #554761; font-size: var(--font-size-body); line-height: 1.7; white-space: pre-wrap">
          {{ helpReviewDetail?.description || '无详细说明' }}
        </p>

        <h4 class="section-title" style="margin-top: 20px">图片 / 视频</h4>
        <div v-if="helpReviewDetail?.media?.length" style="display: flex; flex-wrap: wrap; gap: 8px">
          <template v-for="(url, index) in helpReviewDetail.media" :key="url">
            <a :href="url" target="_blank" rel="noopener">
              <img
                v-if="helpReviewDetail.mediaType !== 'VIDEO' || index > 0"
                :src="url"
                alt="互助媒体"
                style="width: 92px; height: 92px; object-fit: cover; border: 1px solid #ebe9ef; border-radius: 8px"
              />
              <span v-else style="display: inline-flex; width: 92px; height: 92px; align-items: center; justify-content: center; border: 1px solid #ebe9ef; border-radius: 8px; color: #7955b8; font-size: var(--font-size-caption)">
                查看短视频
              </span>
            </a>
          </template>
        </div>
        <p v-else style="color: #988da2; font-size: var(--font-size-body)">无媒体文件</p>

        <h4 class="section-title" style="margin-top: 20px">审核结论</h4>
        <div style="display: flex; flex-wrap: wrap; gap: 8px">
          <button
            :class="{ 'primary-button': helpReviewForm.decision === 'APPROVE' }"
            @click="helpReviewForm.decision = 'APPROVE'"
          >
            通过并展示
          </button>
          <button
            :class="{ 'danger-button': helpReviewForm.decision === 'REJECT' }"
            @click="helpReviewForm.decision = 'REJECT'"
          >
            驳回修改
          </button>
        </div>
        <label class="full" style="display: block; margin-top: 12px">
          <span style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 4px">
            审核备注{{ helpReviewForm.decision === 'REJECT' ? '（驳回必填，≥5 字，将通知发布人）' : '（选填）' }}
          </span>
          <textarea
            v-model="helpReviewForm.reason"
            style="width: 100%; min-height: 72px"
            placeholder="例如：请补充服务资质说明或更清晰的服务内容"
          />
        </label>
        <p style="margin-top: 10px; color: #958b9f; font-size: var(--font-size-caption)">
          通过后服务将进入「待响应」并展示在移动端邻里服务；驳回会通知发布人。
        </p>
      </template>
    </template>
    <template #footer>
      <button @click="helpReviewOpen = false">取消</button>
      <button class="primary-button" :disabled="helpReviewSubmitting || helpReviewLoading" @click="submitHelpReview">
        {{ helpReviewSubmitting ? '提交中…' : '提交审核结论' }}
      </button>
    </template>
  </NiDrawer>

  <NiDrawer
    :open="helpEditOpen"
    :title="helpEditTarget ? `编辑互助 · ${helpEditTarget.title}` : '编辑互助'"
    eyebrow="邻里互助"
    @close="helpEditOpen = false"
  >
    <template v-if="helpEditTarget">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <HandHeart :size="18" style="color: #7955b8" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">
            {{ helpEditTarget.code }} · {{ helpEditTarget.communityName }} · {{ helpEditTarget.requester }}
          </span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ helpEditTarget.title }}</strong>
        </div>
        <StatusBadge :value="helpEditTarget.status" />
      </div>

      <div class="help-edit-section">
        <span class="help-field-label">发布类型 *</span>
        <div class="help-segment">
          <button
            v-for="option in HELP_KIND_OPTIONS"
            :key="option.value"
            type="button"
            class="help-segment-button"
            :class="{ active: helpEditForm.kind === option.value }"
            @click="selectHelpEditKind(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
        <p class="help-edit-hint">
          {{ helpEditForm.kind === 'HELP' ? '求助发布后立即展示，并通过内容安全审核兜底。' : '邻里服务需平台审核，审核通过后展示。' }}
        </p>
      </div>

      <div class="form-grid">
        <label class="full">
          <span>标题 *（2–30 个字）</span>
          <input v-model="helpEditForm.title" maxlength="30" :placeholder="helpTitlePlaceholder" />
        </label>

        <div class="full help-field">
          <span class="help-field-label">互助分类</span>
          <div class="help-choice-list">
            <button
              type="button"
              class="help-choice"
              :class="{ active: !helpEditForm.category && !helpCategoryCustomMode }"
              @click="selectHelpCategory('')"
            >
              暂不选择
            </button>
            <button
              v-for="category in helpCategoryOptions"
              :key="category"
              type="button"
              class="help-choice"
              :class="{ active: helpEditForm.category === category || (category === '其他' && helpCategoryCustomMode) }"
              @click="selectHelpCategory(category)"
            >
              {{ category }}
            </button>
          </div>
          <input
            v-if="helpCategoryCustomMode"
            v-model="helpEditForm.category"
            maxlength="20"
            placeholder="请输入互助分类"
            style="margin-top: 8px"
          />
        </div>

        <div class="full help-field">
          <span class="help-field-label">{{ helpEditForm.kind === 'HELP' ? '期望时间' : '可服务时间' }}</span>
          <div class="help-time-actions">
            <button type="button" class="help-time-button" @click="openHelpTimePicker('specific')">选择具体时间</button>
            <button type="button" class="help-time-button" @click="openHelpTimePicker('range')">选择时间段</button>
          </div>
          <div v-if="helpEditForm.expectedTime" class="help-selected-row">
            <span>已选</span>
            <strong>{{ helpEditForm.expectedTime }}</strong>
            <button type="button" @click="clearHelpTime()">清除</button>
          </div>
          <div v-if="helpTimePickerOpen" class="help-time-panel">
            <span class="help-picker-label">日期</span>
            <div class="help-date-grid">
              <button
                v-for="dateOption in helpDateChoices"
                :key="dateOption.value"
                type="button"
                class="help-date-button"
                :class="{ active: helpTimePickerDate === dateOption.value }"
                @click="selectHelpTimeDate(dateOption.value)"
              >
                {{ dateOption.label }}
              </button>
            </div>
            <span class="help-picker-label">{{ helpTimePickerMode === 'range' ? '开始时间' : '时间' }}</span>
            <div class="help-time-grid">
              <button
                v-for="timeSlot in HELP_TIME_SLOTS"
                :key="`start-${timeSlot}`"
                type="button"
                class="help-time-chip"
                :class="{ active: helpTimePickerStart === timeSlot }"
                @click="selectHelpTimeStart(timeSlot)"
              >
                {{ timeSlot }}
              </button>
            </div>
            <template v-if="helpTimePickerMode === 'range'">
              <span class="help-picker-label">结束时间</span>
              <p v-if="!helpTimePickerStart" class="help-edit-hint">请先选择开始时间</p>
              <div v-else class="help-time-grid">
                <button
                  v-for="timeSlot in helpEndTimeChoices"
                  :key="`end-${timeSlot}`"
                  type="button"
                  class="help-time-chip"
                  :class="{ active: helpTimePickerEnd === timeSlot }"
                  @click="selectHelpTimeEnd(timeSlot)"
                >
                  {{ timeSlot }}
                </button>
              </div>
            </template>
            <div class="help-time-footer">
              <button type="button" @click="clearHelpTime(true)">清除已选时间</button>
              <button type="button" @click="helpTimePickerOpen = false">收起</button>
            </div>
          </div>
          <p class="help-edit-hint">可不选；支持选择一个具体时间或一个时间段。</p>
        </div>

        <label class="full">
          <span>{{ helpEditForm.kind === 'HELP' ? '地点 / 交接位置' : '服务地点 / 范围' }}</span>
          <input v-model="helpEditForm.location" maxlength="64" :placeholder="helpLocationPlaceholder" />
        </label>

        <div class="full help-field">
          <span class="help-field-label">{{ helpEditForm.kind === 'HELP' ? '酬谢方式' : '收费方式' }}</span>
          <div class="help-choice-list">
            <button
              v-for="reward in helpRewardOptions"
              :key="reward"
              type="button"
              class="help-choice"
              :class="{ active: helpEditForm.reward === reward }"
              @click="helpEditForm.reward = reward"
            >
              {{ reward }}
            </button>
          </div>
          <input
            v-model="helpEditForm.reward"
            maxlength="32"
            :placeholder="helpRewardPlaceholder"
            style="margin-top: 8px"
          />
        </div>

        <label class="full">
          <span>详细说明 *（5–500 个字）</span>
          <textarea v-model="helpEditForm.description" maxlength="500" :placeholder="helpDescriptionPlaceholder" />
        </label>
      </div>

      <h4 class="section-title" style="margin-top: 20px">图片 / 视频</h4>
      <div class="help-segment" style="margin-bottom: 10px">
        <button
          type="button"
          class="help-segment-button"
          :class="{ active: helpMediaType === 'video' }"
          @click="selectHelpMediaType('video')"
        >
          短视频
        </button>
        <button
          type="button"
          class="help-segment-button"
          :class="{ active: helpMediaType === 'gallery' }"
          @click="selectHelpMediaType('gallery')"
        >
          照片集
        </button>
      </div>
      <div class="life-media-grid">
        <div v-for="media in helpVisibleMedia" :key="media.key" class="life-media-item">
          <video v-if="media.type === 'video'" :src="media.url" controls preload="metadata" />
          <img v-else :src="media.url" :alt="media.key" />
          <button type="button" class="life-media-remove" aria-label="移除媒体" @click="removeHelpMedia(media.key)">
            <X :size="13" />
          </button>
          <span v-if="helpEditForm.coverKey === media.key" class="life-media-cover">封面</span>
        </div>
        <button
          v-if="helpMediaType === 'gallery' ? helpVisibleMedia.length < 9 : helpVisibleMedia.length === 0"
          type="button"
          class="life-media-add"
          :disabled="helpMediaUploading"
          @click="triggerHelpMediaUpload"
        >
          <Upload :size="18" />
          <span>{{ helpMediaUploading ? '上传中…' : (helpMediaType === 'video' ? '添加短视频' : '添加照片') }}</span>
        </button>
        <input
          ref="helpFileInput"
          class="life-media-input"
          type="file"
          :accept="helpMediaType === 'video' ? 'video/mp4,video/quicktime,video/webm' : 'image/jpeg,image/png,image/webp'"
          :multiple="helpMediaType === 'gallery'"
          @change="onHelpMediaPicked"
        />
      </div>
      <p class="life-media-hint">
        {{ helpMediaType === 'video'
          ? '支持 MP4 / MOV / WebM 短视频，最多 1 个；'
          : '支持 JPG / PNG / WebP 图片，最多 9 张；' }}切换类型不会丢失已上传内容，保存时仅提交当前类型，移动端同步更新。
      </p>
    </template>
    <template #footer>
      <button @click="helpEditOpen = false">取消</button>
      <button class="primary-button" :disabled="helpEditSubmitting" @click="saveHelpEdit">
        {{ helpEditSubmitting ? '保存中…' : '保存修改' }}
      </button>
    </template>
  </NiDrawer>

  <NiDrawer
    :open="lifeReviewOpen"
    :title="lifeReviewTarget ? `生活内容审核 · ${lifeReviewTarget.title}` : '生活内容审核'"
    eyebrow="社区生活"
    @close="lifeReviewOpen = false"
  >
    <template v-if="lifeReviewTarget">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <Coffee :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">
            {{ lifeReviewTarget.code }} · {{ lifeReviewTarget.communityName }} · {{ lifeReviewTarget.author }}
          </span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ lifeReviewTarget.title }}</strong>
        </div>
        <StatusBadge :value="lifeReviewTarget.status" />
      </div>

      <p v-if="lifeReviewLoading" style="color: #988da2">正在加载内容详情…</p>
      <template v-else>
        <div class="form-grid">
          <label><span>发布人</span><input :value="lifeReviewDetail?.author || lifeReviewTarget.author" disabled /></label>
          <label><span>分类</span><input :value="lifeReviewDetail?.category || lifeReviewTarget.category" disabled /></label>
        </div>

        <h4 class="section-title" style="margin-top: 20px">正文内容</h4>
        <p style="color: #554761; font-size: var(--font-size-body); line-height: 1.7; white-space: pre-wrap">
          {{ lifeReviewDetail?.description || '无正文' }}
        </p>

        <h4 class="section-title" style="margin-top: 20px">图片 / 视频</h4>
        <div v-if="lifeReviewDetail?.media?.length" style="display: flex; flex-wrap: wrap; gap: 8px">
          <template v-for="(url, index) in lifeReviewDetail.media" :key="url">
            <a :href="url" target="_blank" rel="noopener">
              <img
                v-if="lifeReviewDetail.mediaType !== 'VIDEO' || index > 0"
                :src="url"
                alt="生活动态媒体"
                style="width: 92px; height: 92px; object-fit: cover; border: 1px solid #ebe9ef; border-radius: 8px"
              />
              <span v-else style="display: inline-flex; width: 92px; height: 92px; align-items: center; justify-content: center; border: 1px solid #ebe9ef; border-radius: 8px; color: #6852c5; font-size: var(--font-size-caption)">
                查看短视频
              </span>
            </a>
          </template>
        </div>
        <p v-else style="color: #988da2; font-size: var(--font-size-body)">无媒体文件</p>

        <h4 class="section-title" style="margin-top: 20px">审核结论</h4>
        <div style="display: flex; flex-wrap: wrap; gap: 8px">
          <button
            :class="{ 'primary-button': lifeReviewForm.decision === 'APPROVE' }"
            @click="lifeReviewForm.decision = 'APPROVE'"
          >
            通过并发布
          </button>
          <button
            :class="{ 'danger-button': lifeReviewForm.decision === 'REJECT' }"
            @click="lifeReviewForm.decision = 'REJECT'"
          >
            驳回修改
          </button>
        </div>
        <label class="full" style="display: block; margin-top: 12px">
          <span style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 4px">
            审核备注{{ lifeReviewForm.decision === 'REJECT' ? '（驳回必填，≥5 字，将通知发布人）' : '（选填）' }}
          </span>
          <textarea
            v-model="lifeReviewForm.reason"
            style="width: 100%; min-height: 72px"
            placeholder="例如：请补充更清晰的小区实拍照片，并说明拍摄地点"
          />
        </label>
        <p style="margin-top: 10px; color: #958b9f; font-size: var(--font-size-caption)">
          通过后内容将立即出现在移动端首页「小区生活」，并通过站内通知告知发布人。
        </p>
      </template>
    </template>
    <template #footer>
      <button @click="lifeReviewOpen = false">取消</button>
      <button class="primary-button" :disabled="lifeReviewSubmitting || lifeReviewLoading" @click="submitLifeReview">
        {{ lifeReviewSubmitting ? '提交中…' : '提交审核结论' }}
      </button>
    </template>
  </NiDrawer>

  <NiDrawer
    :open="lifeEditOpen"
    :title="lifeEditTarget ? `编辑内容 · ${lifeEditTarget.title}` : '编辑内容'"
    eyebrow="社区生活"
    @close="lifeEditOpen = false"
  >
    <template v-if="lifeEditTarget">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <Coffee :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">
            {{ lifeEditTarget.code }} · {{ lifeEditTarget.communityName }} · {{ lifeEditTarget.author }}
          </span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ lifeEditTarget.title }}</strong>
        </div>
        <StatusBadge :value="lifeEditTarget.status" />
      </div>

      <div class="form-grid">
        <label class="full">
          <span>标题 *（2–30 个字）</span>
          <input v-model="lifeEditForm.title" maxlength="30" placeholder="请输入内容标题" />
        </label>
        <label>
          <span>内容分类 *</span>
          <select v-model="lifeEditForm.category">
            <option v-for="category in lifeCategoryOptions" :key="category" :value="category">{{ category }}</option>
          </select>
        </label>
        <label v-if="lifeMediaOptions.length">
          <span>封面</span>
          <select v-model="lifeEditForm.coverKey">
            <option value="">默认（首个媒体）</option>
            <option v-for="option in lifeMediaOptions" :key="option.key" :value="option.key">{{ option.label }}</option>
          </select>
        </label>
        <label class="full">
          <span>正文（最多 500 个字）</span>
          <textarea v-model="lifeEditForm.description" maxlength="500" placeholder="请输入正文内容" />
        </label>
      </div>

      <h4 class="section-title" style="margin-top: 20px">图片 / 视频</h4>
      <div class="life-media-grid">
        <div v-for="(media, index) in lifeEditMedia" :key="media.key" class="life-media-item">
          <video v-if="media.type === 'video'" :src="media.url" controls preload="metadata" />
          <img v-else :src="media.url" :alt="`媒体 ${index + 1}`" />
          <button type="button" class="life-media-remove" aria-label="移除媒体" @click="removeLifeMedia(index)">
            <X :size="13" />
          </button>
          <span v-if="lifeEditForm.coverKey === media.key" class="life-media-cover">封面</span>
        </div>
        <button type="button" class="life-media-add" :disabled="lifeMediaUploading" @click="triggerLifeMediaUpload">
          <Upload :size="18" />
          <span>{{ lifeMediaUploading ? '上传中…' : '添加媒体' }}</span>
        </button>
        <input
          ref="lifeFileInput"
          class="life-media-input"
          type="file"
          accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm"
          multiple
          @change="onLifeMediaPicked"
        />
      </div>
      <p class="life-media-hint">
        支持 JPG / PNG / WebP 图片（最多 12 张）或 MP4 / MOV / WebM 短视频（仅 1 个）；移除后点击「添加媒体」可重新上传，保存后移动端立即展示。
      </p>
    </template>
    <template #footer>
      <button @click="lifeEditOpen = false">取消</button>
      <button class="primary-button" :disabled="lifeEditSubmitting" @click="saveLifeEdit">
        {{ lifeEditSubmitting ? '保存中…' : '保存修改' }}
      </button>
    </template>
  </NiDrawer>

  <NiDrawer
    :open="offlineOpen"
    :title="offlineTarget ? `${rowOfflineLabel()} · ${offlineTarget.title}` : rowOfflineLabel()"
    :eyebrow="config.title"
    @close="offlineOpen = false"
  >
    <template v-if="offlineTarget">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <component :is="rowOfflineIcon()" :size="18" style="color: #c9525e" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">
            {{ offlineTarget.code }} · {{ offlineTarget.communityName || config.ownerLabel }}
          </span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ offlineTarget.title }}</strong>
        </div>
        <StatusBadge :value="offlineTarget.status" />
      </div>
      <label style="display: block">
        <span style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 6px">
          {{ module === 'items' ? '下架原因 *（至少 2 个字，将通知卖家）' : '下架原因（选填）' }}
        </span>
        <textarea
          v-model="offlineReason"
          style="width: 100%; min-height: 84px; padding: 9px; border: 1px solid #e1dee5; border-radius: 8px; font-size: var(--font-size-body); resize: vertical"
          :placeholder="module === 'items' ? '例如：物品描述与实际不符，请补充实拍照片后重新提交' : '请输入下架原因'"
        />
      </label>
      <p style="margin-top: 10px; color: #958b9f; font-size: var(--font-size-caption)">
        {{ module === 'items' ? '下架后物品将不再在移动端展示，卖家会收到通知。' : '操作会记录到审计日志。' }}
      </p>
    </template>
    <template #footer>
      <button @click="offlineOpen = false">取消</button>
      <button class="primary-button" :disabled="offlineSubmitting" @click="submitOffline">
        {{ offlineSubmitting ? '处理中…' : (module === 'items' ? '确认下架' : '确认操作') }}
      </button>
    </template>
  </NiDrawer>

  <NiDrawer
    :open="editOpen"
    :title="editTarget ? `编辑物品 · ${editTarget.title}` : '编辑物品'"
    eyebrow="社区物品"
    @close="editOpen = false"
  >
    <template v-if="editTarget">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <ShoppingBag :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">
            {{ editTarget.code }} · {{ editTarget.seller }} · {{ editTarget.communityName }}
          </span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ editTarget.title }}</strong>
        </div>
        <StatusBadge :value="editTarget.status" />
      </div>

      <div class="form-grid">
        <label class="full"><span>标题 *</span><input v-model="editForm.title" maxlength="30" placeholder="请输入物品标题" /></label>
        <label class="full">
          <span>质量说明 *（至少 20 个字）</span>
          <textarea v-model="editForm.qualityDesc" placeholder="描述成色、使用情况、瑕疵等" />
        </label>
        <label>
          <span>分类</span>
          <select v-model="editForm.categoryId">
            <option :value="null">未选择</option>
            <option v-for="category in flatCategories" :key="category.id" :value="category.id">{{ category.name }}</option>
          </select>
        </label>
        <label>
          <span>交易方式</span>
          <select v-model="editForm.tradeType">
            <option v-for="option in TRADE_TYPES" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label v-if="editForm.tradeType === 'MONETARY'">
          <span>价格（元）*</span>
          <input v-model="editForm.priceYuan" type="number" min="0.01" step="0.01" placeholder="0.00" />
        </label>
        <label>
          <span>成色</span>
          <select v-model="editForm.condition">
            <option value="" disabled>请选择成色</option>
            <option v-for="condition in ITEM_CONDITIONS" :key="condition" :value="condition">{{ condition }}</option>
          </select>
        </label>
        <label v-if="editForm.tradeType === 'BARTER'" class="full">
          <span>期望交换的物品 *</span>
          <input v-model="editForm.barterExpect" placeholder="如：儿童绘本、盆栽绿植等" />
        </label>
      </div>
      <p style="margin-top: 12px; color: #958b9f; font-size: var(--font-size-caption)">
        保存后列表与移动端将展示最新信息；已成交物品不允许编辑。
      </p>
    </template>
    <template #footer>
      <button @click="editOpen = false">取消</button>
      <button class="primary-button" :disabled="editSubmitting" @click="saveEdit">
        {{ editSubmitting ? '保存中…' : '保存修改' }}
      </button>
    </template>
  </NiDrawer>

</template>
