<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Building2, ChevronDown, Filter, MapPin, Plus, Search, Settings2, ShieldCheck, Trash2, UserRound, Users, Home, X } from 'lucide-vue-next'
import { residentApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const auth = useAuthStore()
const rows = ref<any[]>([])
const summary = ref<any>({ total: 0, owner: 0, family: 0, pending: 0 })
const activeTab = ref('全部人员')
const query = ref('')
const page = ref(1)
const total = ref(0)
const communityOpen = ref(false)
const drawerOpen = ref(false)
const editing = ref<any>(null)
const form = ref<any>({})

const tabs = ['全部人员', '业主', '家属', '租户', '商务人员']
const community = computed(() => app.currentCommunity)
const summaryCards = computed(() => [
  { label: '全部人员', value: summary.value.total, icon: Users, tone: 'violet' },
  { label: '业主', value: summary.value.owner, icon: Home, tone: 'blue' },
  { label: '家属与租户', value: summary.value.family, icon: UserRound, tone: 'green' },
  { label: '待完成认证', value: summary.value.pending, icon: ShieldCheck, tone: 'orange' },
])

function levelClass(level: string) {
  return { 普通用户: 'basic', 活跃用户: 'active', 社区达人: 'expert', 重点关怀: 'care' }[level] || 'basic'
}

async function load() {
  try {
    const params: any = { communityId: app.currentCommunityId, page: page.value, pageSize: 50, keyword: query.value }
    if (activeTab.value !== '全部人员') params.identity = activeTab.value
    const [data, summaryData] = await Promise.all([
      residentApi.list(params),
      residentApi.summary(app.currentCommunityId),
    ])
    rows.value = data.items || []
    total.value = data.total || 0
    summary.value = summaryData
  } catch (exc: any) {
    app.showToast(exc?.message || '业主档案加载失败')
  }
}

function switchCommunity(id: number) {
  app.switchCommunity(id)
  communityOpen.value = false
  page.value = 1
  load()
}

function openCreate() {
  editing.value = null
  form.value = {
    communityId: app.currentCommunityId, name: '', gender: '女', phone: '', identity: '业主',
    building: '', relationship: '房屋产权人', certification: '未认证', certificationNo: '—',
    level: '普通用户', status: '正常', joinedAt: '2025-03-20',
  }
  drawerOpen.value = true
}

function openEdit(row: any) {
  editing.value = row
  form.value = { ...row, communityId: Number(row.communityId) }
  drawerOpen.value = true
}

async function save() {
  if (!form.value.name?.trim()) {
    app.showToast('请填写人员姓名')
    return
  }
  try {
    if (editing.value) await residentApi.update(editing.value.id, form.value)
    else await residentApi.create(form.value)
    drawerOpen.value = false
    app.showToast(editing.value ? '人员信息已更新' : '人员档案已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function remove(row: any) {
  if (!window.confirm(`确定删除“${row.name}”的社区人员档案吗？`)) return
  try {
    await residentApi.remove(row.id)
    app.showToast('人员档案已删除')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

onMounted(load)
watch(() => app.currentCommunityId, () => { page.value = 1; load() })
</script>

<template>
  <section class="page-heading list-heading resident-page-heading">
    <div><p>社区管理 / 社区业主</p><h1>社区业主</h1><span>维护社区业主、家属、租户及商务人员的身份与认证档案</span></div>
  </section>

  <section class="community-selector-card">
    <div class="community-selector-icon"><Building2 :size="21" /></div>
    <div><span>选择需要管理的社区</span><strong>当前社区人员档案</strong></div>
    <button :class="['community-selector-trigger', { active: communityOpen }]" @click="communityOpen = !communityOpen">
      <MapPin :size="16" />
      <span><strong>{{ community?.name || '云栖里社区' }}</strong><em>浙江省 / 杭州市 / 西湖区 / 文新街道</em></span>
      <ChevronDown :size="15" />
    </button>
    <div class="community-selector-meta"><span>所在街道</span><strong>文新街道</strong></div>
    <div class="community-selector-meta"><span>社区编码</span><strong>{{ community?.code || 'SQ3301060012' }}</strong></div>
    <div v-if="communityOpen" class="notification-popover" style="top: 78px; left: 17px; right: 17px; width: auto; padding: 8px; z-index: 60">
      <div style="display: flex; justify-content: space-between; padding: 8px 10px; color: #403b47; font-size: var(--font-size-body); font-weight: 600">选择社区<button @click="communityOpen = false"><X :size="16" /></button></div>
      <button v-for="item in app.communities" :key="item.id" style="width: 100%; padding: 10px; display: flex; justify-content: space-between; border-radius: 8px; text-align: left; font-size: var(--font-size-body)" :style="{ background: Number(item.id) === app.currentCommunityId ? '#f1edfc' : 'transparent' }" @click="switchCommunity(Number(item.id))">
        <span>{{ item.name }}</span><span style="color: #9995a1">{{ item.code }}</span>
      </button>
    </div>
  </section>

  <section class="resident-summary-grid">
    <div v-for="card in summaryCards" :key="card.label">
      <span :class="card.tone"><component :is="card.icon" :size="18" /></span>
      <div><p>{{ card.label }}</p><strong>{{ card.value }}</strong></div>
    </div>
  </section>

  <section class="resident-directory-panel">
    <div class="resident-tabs">
      <button v-for="tab in tabs" :key="tab" :class="{ active: activeTab === tab }" @click="activeTab = tab; page = 1; load()">
        {{ tab }}<em>{{ tab === '全部人员' ? summary.total : rows.filter((row) => row.identity === tab).length }}</em>
      </button>
    </div>
    <div class="resident-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索姓名、手机号、房屋或认证编号…" @keyup.enter="load" /></div>
      <div>
        <button><Filter :size="16" />认证状态<ChevronDown :size="14" /></button>
        <button><Settings2 :size="16" />列设置</button>
        <button v-if="auth.hasPermission('community:resident:create')" class="primary-button" @click="openCreate"><Plus :size="16" />新增人员</button>
      </div>
    </div>
    <div class="table-wrap resident-table-wrap">
      <table class="resident-table">
        <thead><tr><th>人员基本信息</th><th>身份类型</th><th>房屋 / 商铺</th><th>认证信息</th><th>用户级别</th><th>账号状态</th><th>加入时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td><div class="resident-person-cell"><span>{{ row.name.charAt(0) }}</span><div><strong>{{ row.name }}</strong><em>{{ row.gender }} · {{ row.phone }}</em></div></div></td>
            <td><span :class="['identity-tag', row.identity]">{{ row.identity }}</span></td>
            <td><div class="resident-house-cell"><strong>{{ row.building }}</strong><span>{{ row.relationship }}</span></div></td>
            <td><div class="resident-certification"><StatusBadge :value="row.certification" /><code>{{ row.certificationNo }}</code></div></td>
            <td><span :class="['resident-level', levelClass(row.level)]">{{ row.level }}</span></td>
            <td><StatusBadge :value="row.status" /></td><td>{{ row.joinedAt }}</td>
            <td><button class="row-action" @click="openEdit(row)">编辑</button><button class="row-more" @click="remove(row)"><Trash2 :size="15" /></button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无匹配人员" description="请调整身份分类或搜索关键词" />
    </div>
    <div class="resident-table-footer"><span>共 {{ total }} 条人员档案</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <NiDrawer :open="drawerOpen" :title="editing ? form.name : '新增社区人员'" :eyebrow="editing ? '维护档案' : '新建档案'" @close="drawerOpen = false">
    <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 18px">
      <Building2 :size="17" style="color: #6852c5" />
      <div style="flex: 1"><span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">所属社区</span><strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ community?.name }}</strong></div>
      <em style="color: #988da2; font-size: var(--font-size-caption)">{{ editing?.id || '新建' }}</em>
    </div>
    <h4 class="section-title">基本信息</h4>
    <div class="form-grid">
      <label><span>姓名 *</span><input v-model="form.name" placeholder="请输入姓名" /></label>
      <label><span>性别</span><select v-model="form.gender"><option>男</option><option>女</option></select></label>
      <label><span>手机号</span><input v-model="form.phone" placeholder="请输入手机号" /></label>
      <label><span>身份类型</span><select v-model="form.identity"><option>业主</option><option>家属</option><option>租户</option><option>商务人员</option></select></label>
      <label class="full"><span>房屋 / 商铺</span><input v-model="form.building" placeholder="例如：8 栋 1 单元 902" /></label>
      <label class="full"><span>与房屋关系</span><input v-model="form.relationship" /></label>
    </div>
    <h4 class="section-title" style="margin-top: 24px">认证与等级</h4>
    <div class="form-grid">
      <label><span>认证状态</span><select v-model="form.certification"><option>已认证</option><option>待审核</option><option>未认证</option><option>认证驳回</option></select></label>
      <label><span>认证编号</span><input v-model="form.certificationNo" /></label>
      <label><span>用户级别</span><select v-model="form.level"><option>普通用户</option><option>活跃用户</option><option>社区达人</option><option>重点关怀</option></select></label>
      <label><span>账号状态</span><select v-model="form.status"><option>正常</option><option>已停用</option></select></label>
    </div>
    <template #footer><button @click="drawerOpen = false">取消</button><button class="primary-button" @click="save">保存档案</button></template>
  </NiDrawer>
</template>
