<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Banknote, ChevronDown, Filter, MoreHorizontal, ReceiptText, Scale, Search, Wallet } from 'lucide-vue-next'
import { financeApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const app = useAppStore()
const overview = ref<any>(null)
const rows = ref<any[]>([])
const query = ref('')
const loading = ref(false)
const tab = computed(() => String(route.params.tab || 'overview'))
const titles: Record<string, { title: string; desc: string; action: string }> = {
  overview: { title: '资金看板', desc: '监控平台托管资金、放款、退款与提现风险', action: '导出对账单' },
  transactions: { title: '资金流水', desc: '按订单、用户、时间与类型检索全部资金流水', action: '导出流水' },
  withdrawals: { title: '提现管理', desc: '审核提现申请、跟踪打款状态并处理失败', action: '批量复核' },
  reconciliations: { title: '对账管理', desc: '按渠道与账单日核对平台流水与渠道账单', action: '重新对账' },
  orders: { title: '订单查询', desc: '查询全量订单、托管状态与双方确认记录', action: '导出订单' },
}
const meta = computed(() => titles[tab.value] || titles.overview)
const overviewMetrics = computed(() => overview.value?.metrics || [])
const trend = computed(() => overview.value?.trend || { labels: [], escrow: [], release: [], refund: [] })
const structure = computed(() => overview.value?.structure || [])

async function load() {
  loading.value = true
  try {
    if (tab.value === 'overview') overview.value = await financeApi.overview()
    if (tab.value === 'overview' || tab.value === 'transactions') {
      const data = await financeApi.transactions({ keyword: query.value, page: 1, pageSize: 50 })
      rows.value = data.items || []
    } else if (tab.value === 'withdrawals') {
      const data = await financeApi.withdrawals({ keyword: query.value, page: 1, pageSize: 50 })
      rows.value = data.items || []
    } else if (tab.value === 'reconciliations') {
      rows.value = await financeApi.reconciliations()
    } else if (tab.value === 'orders') {
      const data = await financeApi.orders({ keyword: query.value, page: 1, pageSize: 50 })
      rows.value = data.items || []
    }
  } catch (exc: any) {
    app.showToast(exc?.message || '资金数据加载失败')
  } finally {
    loading.value = false
  }
}

async function review(row: any) {
  if (!window.confirm(`确认审核通过提现单 ${row.withdrawalNo}？`)) return
  try {
    await financeApi.reviewWithdrawal(row.id, { decision: 'APPROVE', note: '资料齐全，风控已核' })
    app.showToast('提现审核完成')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '审核失败')
  }
}

async function recheck(row: any) {
  try {
    await financeApi.recheck(row.id)
    app.showToast('对账已重新核对')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '对账失败')
  }
}

onMounted(load)
watch(() => route.params.tab, load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>资金与治理 / {{ meta.title }}</p><h1>{{ meta.title }}</h1><span>{{ meta.desc }}</span></div>
    <button class="primary-button" @click="app.showToast(`${meta.action}已开始`)">{{ meta.action }}</button>
  </section>

  <template v-if="tab === 'overview'">
    <section class="metric-grid">
      <div v-for="metric in overviewMetrics" :key="metric.label" class="metric-card">
        <div :class="['metric-icon', metric.tone]"><Wallet :size="20" /></div>
        <div class="metric-top"><span>{{ metric.label }}</span></div>
        <strong>{{ metric.value }}</strong>
        <div class="metric-bottom"><em>{{ metric.change }}</em><span>{{ metric.detail }}</span></div>
      </div>
    </section>
    <section class="dashboard-grid" style="margin-top: 15px">
      <div class="panel trend-panel">
        <div class="panel-heading"><div><h2>托管资金趋势</h2><p>近 7 日托管、放款与退款</p></div><button class="period-button">近 7 天<ChevronDown :size="14" /></button></div>
        <div class="legend"><span><i class="purple" />托管</span><span><i class="light" />放款</span></div>
        <div class="chart-area">
          <div v-for="(label, index) in trend.labels" :key="label" class="chart-column">
            <div class="bars"><i :style="{ height: `${trend.escrow[index] || 0}%` }" /><b :style="{ height: `${trend.release[index] || 0}%` }" /></div>
            <span>{{ label }}</span>
          </div>
        </div>
      </div>
      <div class="panel community-panel">
        <div class="panel-heading"><div><h2>资金结构</h2><p>托管中 / 待放款 / 退款中</p></div></div>
        <div class="community-content">
          <div class="donut" style="background: conic-gradient(#7460d3 0 62.5%, #9f91df 62.5% 89%, #d8d1f2 89% 100%)"><div><strong>62.5%</strong><span>托管中</span></div></div>
          <div class="donut-legend">
            <div v-for="(item, index) in structure" :key="item.label"><i :class="['a', 'b', 'c'][index]" /><span>{{ item.label }}</span><strong>{{ item.pct }}</strong><em /></div>
          </div>
        </div>
      </div>
    </section>
  </template>

  <section v-if="tab !== 'overview' || rows.length" class="table-panel" style="margin-top: 15px">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" :placeholder="`搜索${meta.title}…`" @keyup.enter="load" /></div>
      <div class="toolbar-actions"><button><Filter :size="16" />筛选<ChevronDown :size="14" /></button><button><MoreHorizontal :size="17" /></button></div>
    </div>
    <div class="table-wrap">
      <table v-if="tab === 'transactions'">
        <thead><tr><th>流水号</th><th>订单号</th><th>用户</th><th>类型</th><th>金额</th><th>渠道</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><code>{{ row.txnNo }}</code></td><td>{{ row.orderNo }}</td><td>{{ row.user }}</td><td>{{ row.type }}</td><td>{{ row.amount }}</td><td>{{ row.channel }}</td><td><StatusBadge :value="row.status" /></td><td>{{ row.createdAt }}</td><td><button class="row-action" @click="app.showToast(`查看流水 ${row.txnNo}`)">详情</button></td></tr></tbody>
      </table>
      <table v-else-if="tab === 'withdrawals'">
        <thead><tr><th>提现单号</th><th>用户</th><th>金额</th><th>手续费</th><th>到账账户</th><th>风控</th><th>状态</th><th>申请时间</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><code>{{ row.withdrawalNo }}</code></td><td>{{ row.user }}</td><td>{{ row.amount }}</td><td>{{ row.fee }}</td><td>{{ row.account }}</td><td>{{ row.risk }}</td><td><StatusBadge :value="row.status" /></td><td>{{ row.createdAt }}</td><td><button class="row-action" @click="review(row)">审核</button></td></tr></tbody>
      </table>
      <table v-else-if="tab === 'reconciliations'">
        <thead><tr><th>渠道</th><th>账单日期</th><th>渠道总额</th><th>平台总额</th><th>差异金额</th><th>差异笔数</th><th>状态</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.channel }}</td><td>{{ row.billDate }}</td><td>{{ row.channelAmount }}</td><td>{{ row.platformAmount }}</td><td>{{ row.diff }}</td><td>{{ row.diffCount }}</td><td><StatusBadge :value="row.status" /></td><td><button class="row-action" @click="recheck(row)">重新核对</button></td></tr></tbody>
      </table>
      <table v-else-if="tab === 'orders'">
        <thead><tr><th>订单号</th><th>物品</th><th>买家</th><th>卖家</th><th>交易方式</th><th>金额</th><th>订单状态</th><th>托管状态</th><th>创建时间</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><code>{{ row.orderNo }}</code></td><td>{{ row.itemTitle }}</td><td>{{ row.buyer }}</td><td>{{ row.seller }}</td><td>{{ row.tradeType }}</td><td>{{ row.amountCents ? `¥${(row.amountCents / 100).toFixed(2)}` : '—' }}</td><td><StatusBadge :value="row.status" /></td><td><StatusBadge :value="row.escrowStatus" /></td><td>{{ row.createdLabel }}</td></tr></tbody>
      </table>
      <table v-else>
        <thead><tr><th>流水号</th><th>订单号</th><th>用户</th><th>类型</th><th>金额</th><th>渠道</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><code>{{ row.txnNo }}</code></td><td>{{ row.orderNo }}</td><td>{{ row.user }}</td><td>{{ row.type }}</td><td>{{ row.amount }}</td><td>{{ row.channel }}</td><td><StatusBadge :value="row.status" /></td><td>{{ row.createdAt }}</td><td><button class="row-action" @click="app.showToast(`查看流水 ${row.txnNo}`)">详情</button></td></tr></tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无数据" />
    </div>
    <div class="pagination"><span>共 {{ rows.length }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>
</template>
