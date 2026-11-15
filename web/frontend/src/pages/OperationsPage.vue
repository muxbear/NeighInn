<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ChevronDown, ChevronRight, Coffee, Filter, HandHeart, Megaphone, MoreHorizontal, Plus, Search, ShoppingBag, SlidersHorizontal } from 'lucide-vue-next'
import { operationsApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

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
    api: 'broadcasts', title: '社区喇叭', mobileTitle: '小区喇叭站', tone: 'broadcast', icon: Megaphone,
    description: '运营社区即时播报、邻里话题、重要提醒和互动内容', create: '发布喇叭',
    tabs: ['全部', '已发布', '待审核', '定时发布', '已下架'],
    metrics: [
      { label: '今日播报', value: '28', note: '较昨日 +6' },
      { label: '待审核', value: '6', note: '2 条高优先级', attention: true },
      { label: '今日互动', value: '1,286', note: '评论与点赞' },
      { label: '内容触达率', value: '82.4%', note: '近 7 日 +3.2%' },
    ],
    previews: [
      { title: '今晚中心广场有露天电影', meta: '刚刚 · 186 人互动' },
      { title: '3 栋电梯临时检修提醒', meta: '42 分钟前 · 重要' },
      { title: '社区设施期待投票', meta: '328 人参与' },
    ],
  },
  items: {
    api: 'items', title: '社区物品', mobileTitle: '最近热门商品', tone: 'items', icon: ShoppingBag,
    description: '管理邻里闲置物品、热门推荐、商品审核及交易状态', create: '新增物品',
    tabs: ['全部', '在售', '待审核', '已售出', '已下架'],
    metrics: [
      { label: '在售物品', value: '386', note: '本周新增 52' },
      { label: '待审核', value: '12', note: '平均等待 18 分钟', attention: true },
      { label: '本周成交', value: '86', note: '成交额 ¥12,680' },
      { label: '热门推荐位', value: '8 / 12', note: '剩余 4 个展位' },
    ],
    previews: [
      { title: '九成新儿童平衡车', meta: '¥128 · 18 人想要' },
      { title: '露营折叠椅两把', meta: '¥90 · 热门' },
      { title: '儿童绘本 30 册', meta: '¥60 · 12 人想要' },
    ],
  },
  help: {
    api: 'help-requests', title: '邻里互助', mobileTitle: '邻里互助', tone: 'help', icon: HandHeart,
    description: '管理居民求助、邻里响应、撮合履约及互助信用评价', create: '代发互助',
    tabs: ['全部', '待响应', '匹配中', '进行中', '已完成'],
    metrics: [
      { label: '今日求助', value: '18', note: '紧急求助 2 条' },
      { label: '待响应', value: '8', note: '平均等待 12 分钟', attention: true },
      { label: '本周完成', value: '126', note: '完成率 94.6%' },
      { label: '互助信用分', value: '96.2', note: '社区平均分' },
    ],
    previews: [
      { title: '帮忙照看两小时宠物', meta: '3 人响应 · 120m' },
      { title: '需要借用家用梯子', meta: '进行中 · 已匹配' },
      { title: '下午帮忙搬两箱书', meta: '刚刚 · 待响应' },
    ],
  },
  life: {
    api: 'life-posts', title: '社区生活', mobileTitle: '生活频道', tone: 'life', icon: Coffee,
    description: '运营社区生活频道、便民指南、探店内容和专题推荐', create: '新建内容',
    tabs: ['全部', '已发布', '草稿', '待审核', '已下线'],
    metrics: [
      { label: '频道内容', value: '248', note: '覆盖 8 个分类' },
      { label: '今日阅读', value: '6,328', note: '较昨日 +14.8%', attention: true },
      { label: '待审核', value: '9', note: '含 3 条商户投稿' },
      { label: '内容收藏率', value: '12.6%', note: '近 7 日 +1.9%' },
    ],
    previews: [
      { title: '春日赏花地图', meta: '周末去哪 · 328 收藏' },
      { title: '周边早餐店红榜', meta: '邻里探店 · 热门' },
      { title: '旧衣回收点位指南', meta: '便民指南' },
    ],
  },
}

const module = computed(() => String(route.params.module || 'broadcast'))
const config = computed(() => configs[module.value] || configs.broadcast)
const tabs = computed(() => config.value.tabs)
const filteredRows = computed(() => rows.value)

function statusCount(tab: string) {
  if (tab === '全部') return rows.value.length
  return rows.value.filter((row) => row.status === tab).length
}

async function load() {
  loading.value = true
  try {
    const params: any = { communityId: app.currentCommunityId, page: page.value, pageSize }
    if (activeTab.value !== '全部') params.status = activeTab.value
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

onMounted(load)
watch(() => route.params.module, () => {
  activeTab.value = '全部'
  query.value = ''
  page.value = 1
  load()
})
watch(() => app.currentCommunityId, load)
</script>

<template>
  <section :class="['mobile-module-overview', config.tone]">
    <div class="mobile-module-identity">
      <span><component :is="config.icon" :size="21" /></span>
      <div>
        <em>移动版首页运营位</em>
        <h2>{{ config.mobileTitle }}</h2>
        <p>数据由“{{ config.title }}”模块实时同步至邻里小栈移动端</p>
      </div>
    </div>
    <div class="mobile-module-preview">
      <div v-for="(item, index) in config.previews" :key="item.title">
        <span>{{ index + 1 }}</span>
        <p><strong>{{ item.title }}</strong><em>{{ item.meta }}</em></p>
      </div>
    </div>
    <div class="mobile-module-state">
      <span><i />展位正常</span>
      <strong>自动同步</strong>
      <button @click="app.showToast('移动端展位配置已打开')">展位配置<ChevronRight :size="13" /></button>
    </div>
  </section>

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
        <button><Filter :size="16" />所属社区<ChevronDown :size="14" /></button>
        <button><SlidersHorizontal :size="16" />高级筛选</button>
        <button v-if="auth.hasPermission('community:broadcast:create')" class="primary-button" @click="create"><Plus :size="16" />{{ config.create }}</button>
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
                <div><strong>{{ row.title }}</strong><em>{{ row.code }} · {{ row.subtitle }}</em></div>
              </div>
            </td>
            <td>{{ row.owner }}</td>
            <td><span class="operation-category">{{ row.category }}</span></td>
            <td><span class="operation-performance">{{ row.performance }}</span></td>
            <td><StatusBadge :value="row.status" /></td>
            <td>{{ row.updatedAt }}</td>
            <td>
              <button class="row-action" @click="review(row)">
                {{ module === 'help' ? '撮合' : row.status === '待审核' ? '审核' : '编辑' }}
              </button>
              <button class="row-more" @click="offline(row)"><MoreHorizontal :size="17" /></button>
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
</template>
