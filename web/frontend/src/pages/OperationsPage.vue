<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Coffee, EyeOff, HandHeart, Megaphone, Plus, Search, ShieldCheck, ShoppingBag, SlidersHorizontal } from 'lucide-vue-next'
import { operationsApi } from '@/api'
import { mapTradeType } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import CommunityFilterBar from '@/components/CommunityFilterBar.vue'

const route = useRoute()
const app = useAppStore()
const auth = useAuthStore()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const query = ref('')
const activeTab = ref('全部')
const selectedRows = ref<string[]>([])
const loading = ref(false)
const drawerOpen = ref(false)
const form = ref({ title: '', subtitle: '', owner: '社区运营 · 李知夏', category: '', content: '' })

const configs: Record<string, any> = {
  broadcast: {
    api: 'broadcasts', title: '社区喇叭', tone: 'broadcast', icon: Megaphone,
    ownerLabel: '喇叭归属小区', scopeNote: '喇叭列表仅展示所选小区',
    description: '运营社区即时播报、邻里话题、重要提醒和互动内容', create: '发布喇叭',
    tabs: ['全部', '已发布', '待审核', '定时发布', '已下架'],
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
    metrics: [
      { label: '在售物品', value: '386', note: '本周新增 52' },
      { label: '待审核', value: '12', note: '平均等待 18 分钟', attention: true },
      { label: '本周成交', value: '86', note: '成交额 ¥12,680' },
      { label: '热门推荐位', value: '8 / 12', note: '剩余 4 个展位' },
    ],
  },
  help: {
    api: 'help-requests', title: '邻里互助', tone: 'help', icon: HandHeart,
    ownerLabel: '互助归属小区', scopeNote: '互助列表仅展示所选小区',
    description: '管理居民求助、邻里响应、撮合履约及互助信用评价', create: '代发互助',
    tabs: ['全部', '待响应', '匹配中', '进行中', '已完成'],
    metrics: [
      { label: '今日求助', value: '18', note: '紧急求助 2 条' },
      { label: '待响应', value: '8', note: '平均等待 12 分钟', attention: true },
      { label: '本周完成', value: '126', note: '完成率 94.6%' },
      { label: '互助信用分', value: '96.2', note: '社区平均分' },
    ],
  },
  life: {
    api: 'life-posts', title: '社区生活', tone: 'life', icon: Coffee,
    ownerLabel: '内容归属小区', scopeNote: '生活内容仅展示所选小区',
    description: '运营社区生活频道、便民指南、探店内容和专题推荐', create: '新建内容',
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
  help: { 待响应: 'OPEN', 匹配中: 'MATCHING', 进行中: 'IN_PROGRESS', 已完成: 'COMPLETED' },
  items: { 在售: 'ON_SALE', 待审核: 'PENDING_REVIEW', 已售出: 'SOLD', 已下架: 'OFF_SHELF' },
}

const ITEM_OFFLINE_BLOCKED = ['SOLD', 'GIFTED', 'OFF_SHELF']
const HELP_TERMINAL = ['COMPLETED', 'CLOSED']

const module = computed(() => String(route.params.module || 'broadcast'))
const config = computed(() => configs[module.value] || configs.broadcast)
const tabs = computed(() => config.value.tabs)
const filteredRows = computed(() => rows.value)
const canCreate = computed(() => module.value === 'broadcast' && auth.hasPermission('community:broadcast:create'))

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
    if (query.value) params.keyword = query.value
    const data = await operationsApi.list(config.value.api, params)
    rows.value = data.items || []
    total.value = data.total || 0
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

function create() {
  form.value = { title: '', subtitle: '', owner: '社区运营 · 李知夏', category: '', content: '' }
  drawerOpen.value = true
}

async function save() {
  if (!form.value.title.trim()) {
    app.showToast('请填写标题')
    return
  }
  try {
    await operationsApi.create(config.value.api, {
      communityId: app.currentCommunityId,
      title: form.value.title,
      subtitle: form.value.subtitle,
      owner: form.value.owner,
      category: form.value.category,
      content: form.value.content,
    })
    drawerOpen.value = false
    app.showToast(`${config.value.create}已提交`)
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
  try {
    if (module.value === 'help') {
      await operationsApi.matchHelp(row.id)
    } else {
      await operationsApi.review(config.value.api, row.id, { decision: 'APPROVE' })
    }
    app.showToast('操作已完成')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
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

async function offline(row: any) {
  try {
    if (module.value === 'help') {
      await operationsApi.closeHelp(row.id)
      app.showToast('互助已关闭')
    } else {
      await operationsApi.offline(config.value.api, row.id)
      app.showToast('内容已下架')
    }
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
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

/** 主操作只在服务端状态机允许的源状态下展示，避免点击后 40904。 */
function canPrimaryAction(row: any): boolean {
  if (module.value === 'help') return ['OPEN', 'MATCHING'].includes(row.statusCode)
  if (module.value === 'items') return row.statusCode === 'PENDING_REVIEW'
  return row.statusCode === 'PENDING_REVIEW'
}

function canOffline(row: any): boolean {
  if (module.value === 'items') return !ITEM_OFFLINE_BLOCKED.includes(row.statusCode)
  if (module.value === 'help') return !HELP_TERMINAL.includes(row.statusCode)
  return ['PENDING_REVIEW', 'SCHEDULED', 'PUBLISHED'].includes(row.statusCode)
}

function rowActionIcon(row: any) {
  if (module.value === 'help') return HandHeart
  return ShieldCheck
}

function rowActionLabel(row: any) {
  if (module.value === 'help') return '人工撮合'
  if (module.value === 'items') return '审核物品'
  return row.statusCode === 'PENDING_REVIEW' ? '审核内容' : '查看内容'
}

function rowOfflineLabel() {
  return module.value === 'help' ? '关闭互助' : '下架内容'
}

onMounted(load)
watch(() => route.params.module, () => {
  activeTab.value = '全部'
  query.value = ''
  page.value = 1
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
    <div v-for="metric in config.metrics" :key="metric.label">
      <span>{{ metric.label }}</span>
      <strong>{{ metric.value }}</strong>
      <em :class="{ attention: metric.attention }">{{ metric.note }}</em>
    </div>
  </section>

  <section class="community-operation-panel">
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
      <button @click="app.showToast('批量状态变更已完成')">批量变更状态</button>
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
                <button v-if="canOffline(row)" class="row-icon-button danger" :aria-label="rowOfflineLabel()" :data-tip="rowOfflineLabel()" @click="offline(row)">
                  <EyeOff :size="15" />
                </button>
                <span v-if="!canPrimaryAction(row) && !canOffline(row)" class="cell-ellipsis sm">—</span>
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

  <NiDrawer :open="drawerOpen" :title="config.create" eyebrow="运营内容" @close="drawerOpen = false">
    <div class="form-grid">
      <label class="full"><span>标题 *</span><input v-model="form.title" placeholder="请输入标题" /></label>
      <label class="full"><span>副标题 / 摘要</span><input v-model="form.subtitle" placeholder="如：含图片 · 覆盖全体住户" /></label>
      <label><span>分类</span><input v-model="form.category" placeholder="如：邻里播报" /></label>
      <label><span>发布人</span><input v-model="form.owner" /></label>
      <label class="full"><span>正文</span><textarea v-model="form.content" placeholder="请输入正文内容" /></label>
    </div>
    <template #footer>
      <button @click="drawerOpen = false">取消</button>
      <button class="primary-button" @click="save">提交</button>
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
</template>
