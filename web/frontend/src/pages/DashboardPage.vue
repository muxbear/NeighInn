<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  FileText,
  Flag,
  MessageCircleMore,
  MoreHorizontal,
  Plus,
  ShoppingBag,
  TrendingUp,
  Users,
  Wrench,
} from 'lucide-vue-next'
import { dashboardApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useTodoStore } from '@/stores/todos'

const router = useRouter()
const app = useAppStore()
const todoStore = useTodoStore()
const summary = ref<any>(null)
const trend = ref<any>({ labels: [], active: [], interaction: [] })
const activities = ref<any[]>([])
const loading = ref(true)

const metrics = computed(() => {
  const m = summary.value?.metrics || {}
  return [
    { label: '社区用户', value: Number(m.users || 12680).toLocaleString(), change: m.usersChange || '+8.2%', detail: m.usersDetail || '本月新增 326', icon: Users, tone: 'violet' },
    { label: '今日活跃', value: Number(m.active || 3428).toLocaleString(), change: m.activeChange || '+12.4%', detail: m.activeDetail || '活跃率 27.0%', icon: Activity, tone: 'blue' },
    { label: '待办事项', value: String(m.todos ?? 0), change: m.todoChange || '需关注', detail: m.todoDetail || '认证与运营待办', icon: ClipboardCheck, tone: 'orange' },
    { label: '服务满意度', value: `${Number(m.satisfaction || 96.8).toFixed(1)}%`, change: m.satisfactionChange || '+1.6%', detail: m.satisfactionDetail || '基于 1,284 份评价', icon: TrendingUp, tone: 'green' },
  ]
})
const distribution = computed(() => summary.value?.distribution || { total: 4582, owner: 2864, tenant: 1214, other: 504, ownerPct: '62.5%', tenantPct: '26.5%', otherPct: '11.0%' })
const donutStyle = computed(() => {
  const d = distribution.value
  return { background: `conic-gradient(#7460d3 0 ${d.ownerPct}, #9f91df ${d.ownerPct} 89%, #d8d1f2 89% 100%)` }
})
const todos = computed(() => {
  const source = todoStore.items.length ? todoStore.items : (summary.value?.todos || [])
  return source.filter((item: any) => Number(item.count || 0) > 0)
})
const todoIcon = (name: string) => ({ Wrench, ClipboardCheck, Flag, MessageCircleMore, ShoppingBag }[name] || ClipboardCheck)

function openTodo(item: any) {
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
  router.push(item.route || '/dashboard')
}
async function load() {
  loading.value = true
  try {
    const cid = app.currentCommunityId
    const [summaryData, trendData, activityData] = await Promise.all([
      dashboardApi.summary(cid),
      dashboardApi.trend(7, cid),
      dashboardApi.activities(cid, 4),
    ])
    summary.value = summaryData
    trend.value = trendData
    activities.value = activityData
    todoStore.refresh()
  } catch (exc: any) {
    app.showToast(exc?.message || '工作台数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => app.currentCommunityId, load)
</script>

<template>
  <section class="dashboard-toolbar">
    <button class="secondary-button" @click="app.showToast('运营简报已生成')"><FileText :size="17" />生成简报</button>
    <button class="primary-button" @click="router.push('/communication/notices')"><Plus :size="17" />发布公告</button>
  </section>

  <section class="metric-grid">
    <div v-for="metric in metrics" :key="metric.label" class="metric-card">
      <div :class="['metric-icon', metric.tone]"><component :is="metric.icon" :size="20" /></div>
      <div class="metric-top"><span>{{ metric.label }}</span><button><MoreHorizontal :size="18" /></button></div>
      <strong>{{ metric.value }}</strong>
      <div class="metric-bottom"><em>{{ metric.change }}</em><span>{{ metric.detail }}</span></div>
    </div>
  </section>

  <section class="dashboard-grid">
    <div class="panel trend-panel">
      <div class="panel-heading">
        <div><h2>社区活跃趋势</h2><p>近 7 日访问与内容互动数据</p></div>
        <button class="period-button">近 7 天<ChevronDown :size="14" /></button>
      </div>
      <div class="legend"><span><i class="purple" />活跃用户</span><span><i class="light" />内容互动</span></div>
      <div class="chart-area">
        <div v-for="(label, index) in trend.labels" :key="label" class="chart-column">
          <div class="bars">
            <i :style="{ height: `${trend.active[index] || 0}%` }" />
            <b :style="{ height: `${trend.interaction[index] || 0}%` }" />
          </div>
          <span>{{ label }}</span>
        </div>
      </div>
    </div>

    <div class="panel todo-panel">
      <div class="panel-heading">
        <div><h2>待办事项</h2><p>按优先级聚合的运营任务</p></div>
        <button @click="router.push('/governance/repair-orders')">查看全部<ChevronRight :size="14" /></button>
      </div>
      <button v-for="item in todos.slice(0, 4)" :key="item.key || item.title" class="todo-item" @click="openTodo(item)">
        <span :class="['todo-icon', item.color]"><component :is="todoIcon(item.icon)" :size="18" /></span>
        <div><strong>{{ item.title }}</strong><p>{{ item.description || item.sub }}</p></div>
        <em>{{ item.count }}</em>
        <ChevronRight :size="16" />
      </button>
    </div>

    <div class="panel community-panel">
      <div class="panel-heading">
        <div><h2>社区运行概览</h2><p>核心业务结构与服务状态</p></div>
        <button><MoreHorizontal :size="18" /></button>
      </div>
      <div class="community-content">
        <div class="donut" :style="donutStyle"><div><strong>{{ Number(distribution.total).toLocaleString() }}</strong><span>认证住户</span></div></div>
        <div class="donut-legend">
          <div><i class="a" /><span>业主</span><strong>{{ Number(distribution.owner).toLocaleString() }}</strong><em>{{ distribution.ownerPct }}</em></div>
          <div><i class="b" /><span>租户</span><strong>{{ Number(distribution.tenant).toLocaleString() }}</strong><em>{{ distribution.tenantPct }}</em></div>
          <div><i class="c" /><span>商户及其他</span><strong>{{ Number(distribution.other).toLocaleString() }}</strong><em>{{ distribution.otherPct }}</em></div>
        </div>
      </div>
    </div>

    <div class="panel activity-panel">
      <div class="panel-heading">
        <div><h2>最新动态</h2><p>社区内刚刚发生的事情</p></div>
        <button @click="router.push('/community/content')">查看全部<ChevronRight :size="14" /></button>
      </div>
      <div v-for="item in activities" :key="item.time" class="activity-row">
        <span :class="['mini-avatar', item.tone]">{{ item.mark }}</span>
        <div><p><strong>{{ item.name }}</strong> {{ item.action }}</p><span>{{ item.target }}</span></div>
        <time>{{ item.time }}</time>
      </div>
    </div>
  </section>
</template>
