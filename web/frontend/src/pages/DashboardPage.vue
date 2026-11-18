<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity,
  AlertTriangle,
  Banknote,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Coffee,
  Flag,
  Gavel,
  HandHeart,
  MessageCircleMore,
  Plus,
  RefreshCw,
  ShieldCheck,
  ShoppingBag,
  TrendingUp,
  Users,
  Wrench,
} from 'lucide-vue-next'
import { dashboardApi } from '@/api'
import { fmtMoney } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useTodoStore } from '@/stores/todos'

const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()
const todoStore = useTodoStore()

const summary = ref<any>(null)
const trend = ref<any>({
  labels: [],
  newUsers: [],
  contentPublished: [],
  interactions: [],
})
const activities = ref<any[]>([])
const loading = ref(true)
const refreshing = ref(false)
const trendLoading = ref(false)
const error = ref('')
const days = ref(7)
const now = ref(new Date())
let clockTimer: number | undefined

const WEEKDAYS = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']

function formatNumber(value: unknown): string {
  return Number(value || 0).toLocaleString('zh-CN')
}

const greeting = computed(() => {
  const hour = now.value.getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '早上好'
  if (hour < 18) return '下午好'
  return '晚上好'
})
const adminName = computed(() => auth.admin?.realName || auth.admin?.username || '管理员')
const todayLabel = computed(() => {
  const date = now.value
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日 · ${WEEKDAYS[date.getDay()]}`
})
const scopeLabel = computed(() => summary.value?.community?.name || '全平台')
const showSkeleton = computed(() => loading.value && !summary.value)

const todos = computed(() => {
  // 工作台以本次 summary 的社区范围为准；Store 仅用于首屏兜底。
  // 否则切换运营空间时，Store 里上一社区的旧待办会短暂覆盖新社区结果。
  const source = summary.value?.todos?.length ? summary.value.todos : todoStore.items
  return source.filter((item: any) => Number(item.count || 0) > 0)
})
const todoTotal = computed(() => todos.value.reduce((sum: number, item: any) => sum + Number(item.count || 0), 0))
const visibleTodos = computed(() => todos.value.slice(0, 6))
const extraTodoItems = computed(() => Math.max(0, todos.value.length - visibleTodos.value.length))

const subtitle = computed(() => {
  if (error.value && !summary.value) return '数据加载失败，请稍后重试。'
  if (loading.value && !summary.value) return '正在汇总社区运行数据…'
  if (todoTotal.value > 0) {
    return `${scopeLabel.value}实时数据已同步，今天有 ${todoTotal.value} 项事务等待处理。`
  }
  return `${scopeLabel.value}实时数据已同步，当前没有待处理事务。`
})

const metrics = computed(() => {
  const m = summary.value?.metrics || {}
  const scoped = summary.value?.scope === 'COMMUNITY'
  return [
    {
      key: 'users',
      label: scoped ? '社区住户' : '平台用户',
      value: formatNumber(m.users),
      tone: 'violet',
      icon: Users,
      primary: `今日新增 ${formatNumber(m.todayNewUsers)} 人`,
      secondary: `平台注册 ${formatNumber(m.platformUsers)} 人`,
    },
    {
      key: 'active',
      label: '近 7 日活跃',
      value: formatNumber(m.activeUsers),
      tone: 'blue',
      icon: Activity,
      primary: `活跃率 ${Number(m.activeRate || 0).toFixed(1)}%`,
      secondary: '按登录与令牌刷新统计',
    },
    {
      key: 'todos',
      label: '待办事项',
      value: formatNumber(todoTotal.value),
      tone: 'orange',
      icon: ClipboardCheck,
      primary: m.pendingReviews ? `内容待复核 ${formatNumber(m.pendingReviews)} 项` : '暂无内容待复核',
      secondary: '点击下方待办处理',
    },
    {
      key: 'gmv',
      label: '累计成交',
      value: fmtMoney(m.gmvCents),
      tone: 'green',
      icon: TrendingUp,
      primary: `已完成 ${formatNumber(m.ordersCompleted)} 笔`,
      secondary: `赠与 ${formatNumber(m.giftCompleted)} · 互换 ${formatNumber(m.barterCompleted)}`,
    },
  ]
})

const chartMax = computed(() => {
  const values = [...(trend.value.newUsers || []), ...(trend.value.contentPublished || [])]
    .map((value: any) => Number(value || 0))
  return Math.max(1, ...values)
})
function barHeight(value: unknown): string {
  const count = Number(value || 0)
  if (count <= 0) return '0%'
  return `${Math.max(4, Math.round((count / chartMax.value) * 100))}%`
}
const hasTrendData = computed(() => {
  const values = [...(trend.value.newUsers || []), ...(trend.value.contentPublished || [])]
  return values.some((value: any) => Number(value || 0) > 0)
})
const trendInteractionTotal = computed(() =>
  (trend.value.interactions || []).reduce((sum: number, value: any) => sum + Number(value || 0), 0),
)

const distribution = computed(() => summary.value?.distribution || {
  owner: 0, tenant: 0, family: 0, business: 0, total: 0,
})
const distributionRows = computed(() => {
  const d = distribution.value
  const total = Number(d.total || 0)
  const rows = [
    { key: 'owner', label: '业主', value: Number(d.owner || 0), color: '#7460d3' },
    { key: 'tenant', label: '租户', value: Number(d.tenant || 0), color: '#9f91df' },
    { key: 'family', label: '家属', value: Number(d.family || 0), color: '#c3b8ec' },
    { key: 'business', label: '商务人员', value: Number(d.business || 0), color: '#e0daf5' },
  ]
  return rows.map((row) => ({
    ...row,
    pct: total ? (row.value * 100) / total : 0,
    pctLabel: total ? `${((row.value * 100) / total).toFixed(1)}%` : '0.0%',
  }))
})
const donutStyle = computed(() => {
  const rows = distributionRows.value.filter((row) => row.value > 0)
  if (!rows.length) return { background: '#f1eff5' }
  let cursor = 0
  const stops = rows.map((row, index) => {
    const start = cursor
    cursor += row.pct
    const end = index === rows.length - 1 ? 100 : cursor
    return `${row.color} ${start}% ${end}%`
  })
  return { background: `conic-gradient(${stops.join(', ')})` }
})

const TODO_ICONS: Record<string, any> = {
  Wrench,
  ClipboardCheck,
  Flag,
  MessageCircleMore,
  ShoppingBag,
  Coffee,
  Gavel,
  Banknote,
  HandHeart,
  ShieldCheck,
}

function todoIcon(name: string) {
  return TODO_ICONS[name] || ClipboardCheck
}

function openTodo(item: any) {
  const target = router.resolve(item.route || '/dashboard')
  const communityId = Number(target.query.communityId || item.communityId || 0)
  if (communityId && communityId !== app.currentCommunityId) {
    app.switchCommunity(communityId)
  }
  if (item.key === 'certification') {
    router.push({
      path: item.route || '/governance/verification',
      query: {
        status: 'PENDING',
        ...(item.latestCertId ? { certId: item.latestCertId } : {}),
      },
    })
    return
  }
  // 保留当前运营空间上下文，便于列表页按社区过滤。
  if (!target.query.communityId && app.currentCommunityId) {
    router.push({ path: target.path, query: { ...target.query, communityId: app.currentCommunityId } })
    return
  }
  router.push(item.route || '/dashboard')
}

async function load(silent = false) {
  if (!silent) loading.value = true
  error.value = ''
  try {
    const cid = app.currentCommunityId
    const [summaryData, trendData, activityData] = await Promise.all([
      dashboardApi.summary(cid),
      dashboardApi.trend(days.value, cid),
      dashboardApi.activities(cid, 6),
    ])
    summary.value = summaryData
    trend.value = trendData
    activities.value = activityData
    todoStore.refresh(cid)
  } catch (exc: any) {
    error.value = exc?.message || '工作台数据加载失败'
    app.showToast(error.value)
  } finally {
    loading.value = false
    refreshing.value = false
    trendLoading.value = false
  }
}

async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  await load(true)
}

async function changeDays(event: Event) {
  const next = Number((event.target as HTMLSelectElement).value)
  days.value = next
  trendLoading.value = true
  try {
    trend.value = await dashboardApi.trend(next, app.currentCommunityId)
  } catch (exc: any) {
    app.showToast(exc?.message || '趋势数据加载失败')
  } finally {
    trendLoading.value = false
  }
}

onMounted(() => {
  load()
  clockTimer = window.setInterval(() => { now.value = new Date() }, 60_000)
})

onUnmounted(() => {
  if (clockTimer) window.clearInterval(clockTimer)
})

watch(() => app.currentCommunityId, () => load())
</script>

<template>
  <header class="dashboard-heading">
    <div>
      <p class="dashboard-eyebrow">{{ todayLabel }} · {{ scopeLabel }}</p>
      <h1>{{ greeting }}，{{ adminName }}</h1>
      <p class="dashboard-subtitle">{{ subtitle }}</p>
    </div>
    <div class="dashboard-actions">
      <button class="secondary-button" :disabled="refreshing || loading" @click="refresh">
        <RefreshCw :size="16" :class="{ spinning: refreshing }" />
        {{ refreshing ? '刷新中' : '刷新数据' }}
      </button>
      <button
        v-if="auth.hasPermission('communication:notice:create')"
        class="primary-button"
        @click="router.push('/communication/notices')"
      >
        <Plus :size="16" />发布公告
      </button>
    </div>
  </header>

  <div v-if="error" class="dashboard-error" role="alert">
    <AlertTriangle :size="17" />
    <span>{{ error }}</span>
    <button @click="refresh">重试</button>
  </div>

  <section v-if="showSkeleton" class="metric-grid" aria-busy="true" aria-label="指标加载中">
    <div v-for="index in 4" :key="index" class="metric-card metric-skeleton">
      <i class="skeleton-icon" />
      <i class="skeleton-line short" />
      <i class="skeleton-line value" />
      <i class="skeleton-line" />
    </div>
  </section>
  <section v-else class="metric-grid">
    <div v-for="metric in metrics" :key="metric.key" class="metric-card">
      <div :class="['metric-icon', metric.tone]"><component :is="metric.icon" :size="20" /></div>
      <div class="metric-top"><span>{{ metric.label }}</span></div>
      <strong>{{ metric.value }}</strong>
      <div class="metric-bottom"><em>{{ metric.primary }}</em><span>{{ metric.secondary }}</span></div>
    </div>
  </section>

  <section class="dashboard-grid">
    <div class="panel trend-panel">
      <div class="panel-heading">
        <div>
          <h2>社区运营趋势</h2>
          <p>近 {{ days }} 日新增注册与内容发布</p>
        </div>
        <label class="period-select">
          <select :value="days" aria-label="选择趋势周期" @change="changeDays">
            <option :value="7">近 7 天</option>
            <option :value="30">近 30 天</option>
          </select>
          <ChevronDown :size="14" />
        </label>
      </div>
      <div class="legend">
        <span><i class="purple" />新增注册</span>
        <span><i class="light" />内容发布</span>
        <span v-if="trendInteractionTotal">· 互动 {{ formatNumber(trendInteractionTotal) }} 次</span>
      </div>
      <div v-if="showSkeleton" class="panel-loading" aria-busy="true">
        <i v-for="index in 7" :key="index" class="skeleton-bar" :style="{ height: `${30 + (index % 4) * 14}%` }" />
      </div>
      <div v-else :class="['chart-area', { dense: days > 14 }]">
        <div v-for="(label, index) in trend.labels" :key="`${label}-${index}`" class="chart-column">
          <div class="bars">
            <i
              :style="{ height: barHeight(trend.newUsers[index]) }"
              :title="`${label} 新增注册 ${trend.newUsers[index] || 0}`"
            />
            <b
              :style="{ height: barHeight(trend.contentPublished[index]) }"
              :title="`${label} 内容创建 ${trend.contentPublished[index] || 0}`"
            />
          </div>
          <span>{{ label }}</span>
        </div>
        <div v-if="trendLoading" class="chart-state">正在加载趋势…</div>
        <div v-else-if="!hasTrendData" class="chart-state">近 {{ days }} 天暂无新增注册或内容发布</div>
      </div>
    </div>

    <div class="panel todo-panel">
      <div class="panel-heading">
        <div><h2>待办事项</h2><p>按当前管理员权限与运营空间聚合</p></div>
        <span v-if="todoTotal" class="panel-count">{{ todoTotal }} 项</span>
      </div>
      <template v-if="showSkeleton">
        <div v-for="index in 4" :key="index" class="todo-skeleton">
          <i class="skeleton-icon" /><i class="skeleton-line" />
        </div>
      </template>
      <template v-else-if="visibleTodos.length">
        <button v-for="item in visibleTodos" :key="item.key || item.title" class="todo-item" @click="openTodo(item)">
          <span :class="['todo-icon', item.color]"><component :is="todoIcon(item.icon)" :size="18" /></span>
          <div><strong>{{ item.title }}</strong><p>{{ item.description || '待处理事项' }}</p></div>
          <em>{{ item.count }}</em>
          <ChevronRight :size="16" />
        </button>
        <p v-if="extraTodoItems" class="todo-more">另有 {{ extraTodoItems }} 类待办，可在顶部铃铛查看全部</p>
      </template>
      <div v-else class="panel-empty">
        <ClipboardCheck :size="26" />
        <strong>暂无待办</strong>
        <span>当前没有需要处理的认证或运营事项</span>
      </div>
    </div>

    <div class="panel community-panel">
      <div class="panel-heading">
        <div><h2>社区运行概览</h2><p>已认证住户身份结构</p></div>
      </div>
      <div v-if="showSkeleton" class="community-content">
        <div class="donut skeleton-donut" />
        <div class="donut-legend">
          <div v-for="index in 4" :key="index"><i class="skeleton-dot" /><span class="skeleton-line" /></div>
        </div>
      </div>
      <div v-else-if="distribution.total" class="community-content">
        <div class="donut" :style="donutStyle">
          <div><strong>{{ formatNumber(distribution.total) }}</strong><span>认证住户</span></div>
        </div>
        <div class="donut-legend">
          <div v-for="row in distributionRows" :key="row.key">
            <i :style="{ background: row.color }" />
            <span>{{ row.label }}</span>
            <strong>{{ formatNumber(row.value) }}</strong>
            <em>{{ row.pctLabel }}</em>
          </div>
        </div>
      </div>
      <div v-else class="panel-empty">
        <Users :size="26" />
        <strong>暂无认证住户</strong>
        <span>住户认证通过后将在此按身份统计</span>
      </div>
    </div>

    <div class="panel activity-panel">
      <div class="panel-heading">
        <div><h2>最新动态</h2><p>社区内真实的业务事件</p></div>
        <span class="panel-live"><i />实时</span>
      </div>
      <template v-if="showSkeleton">
        <div v-for="index in 4" :key="index" class="activity-skeleton">
          <i class="skeleton-icon" /><i class="skeleton-line" />
        </div>
      </template>
      <template v-else-if="activities.length">
        <div v-for="item in activities" :key="item.id" class="activity-row">
          <span :class="['mini-avatar', item.tone]">{{ item.mark }}</span>
          <div><p><strong>{{ item.actor }}</strong> {{ item.action }}</p><span>{{ item.target || '—' }}</span></div>
          <time>{{ item.timeLabel }}</time>
        </div>
      </template>
      <div v-else class="panel-empty">
        <Activity :size="26" />
        <strong>暂无社区动态</strong>
        <span>认证、发布、求助或交易后将出现在这里</span>
      </div>
    </div>
  </section>
</template>
