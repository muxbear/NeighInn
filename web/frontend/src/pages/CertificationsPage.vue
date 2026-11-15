<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, ClipboardCheck, FileImage, Filter, Search, ShieldCheck } from 'lucide-vue-next'
import { certificationsApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const auth = useAuthStore()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const activeTab = ref('PENDING')
const typeFilter = ref('')
const query = ref('')
const selected = ref<any>(null)
const drawerOpen = ref(false)
const rejectReason = ref('')
const loading = ref(false)

const tabs = [
  { key: 'PENDING', label: '待审核' },
  { key: 'VERIFIED', label: '已通过' },
  { key: 'REJECTED', label: '已驳回' },
  { key: 'SUPPLEMENT', label: '待补充' },
  { key: '', label: '全部' },
]

const summary = computed(() => ({
  pending: rows.value.filter((row) => row.statusCode === 'PENDING').length,
  total: total.value,
}))

async function load() {
  loading.value = true
  try {
    const params: any = { page: page.value, pageSize: 20 }
    if (activeTab.value) params.status = activeTab.value
    if (typeFilter.value) params.type = typeFilter.value
    if (query.value) params.keyword = query.value
    const data = await certificationsApi.list(params)
    rows.value = data.items || []
    total.value = data.total || 0
  } catch (exc: any) {
    app.showToast(exc?.message || '审核队列加载失败')
  } finally {
    loading.value = false
  }
}

async function open(row: any) {
  try {
    selected.value = await certificationsApi.detail(row.id)
    rejectReason.value = ''
    drawerOpen.value = true
  } catch (exc: any) {
    app.showToast(exc?.message || '详情加载失败')
  }
}

async function approve() {
  if (!window.confirm('确认通过该认证申请？通过后账号将与小区强绑定。')) return
  try {
    await certificationsApi.approve(selected.value.id)
    app.showToast('已通过并通知申请人')
    drawerOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

async function reject() {
  if (rejectReason.value.trim().length < 10) {
    app.showToast('驳回原因必填，且不少于 10 个字')
    return
  }
  try {
    await certificationsApi.reject(selected.value.id, rejectReason.value.trim())
    app.showToast('已驳回并通知申请人')
    drawerOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

async function requestMaterials() {
  const note = window.prompt('请填写需要补充的材料说明', '请补充房产证明首页与签字页照片')
  if (!note) return
  try {
    await certificationsApi.requestMaterials(selected.value.id, note)
    app.showToast('已要求补充材料')
    drawerOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>社区管理 / 住户认证</p><h1>住户认证审核</h1><span>实名认证与业主证明审核队列；通过后账号与小区强绑定（BR-02）</span></div>
    <button class="primary-button" @click="load"><ClipboardCheck :size="17" />刷新队列</button>
  </section>

  <section class="summary-row">
    <div><span>待审核</span><strong>{{ summary.pending }}</strong><em class="warn">目标 SLA ≤ 24h</em></div>
    <div><span>当前页总数</span><strong>{{ summary.total }}</strong><em>队列规模</em></div>
    <div><span>实名认证</span><strong>{{ rows.filter((row) => row.type === 'REALNAME').length }}</strong><em>本页</em></div>
    <div><span>业主证明</span><strong>{{ rows.filter((row) => row.type === 'OWNER_PROOF').length }}</strong><em>本页</em></div>
  </section>

  <section class="table-panel">
    <div class="table-toolbar">
      <div class="resident-tabs" style="margin-right: 12px">
        <button v-for="tab in tabs" :key="tab.key" :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key; page = 1; load()">{{ tab.label }}</button>
      </div>
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索申请人或追踪号…" @keyup.enter="load" /></div>
      <div class="toolbar-actions">
        <button @click="typeFilter = typeFilter ? '' : 'REALNAME'; page = 1; load()">
          <Filter :size="16" />{{ typeFilter === 'REALNAME' ? '仅实名' : '全部类型' }}<ChevronDown :size="14" />
        </button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>申请人</th><th>类型</th><th>目标小区</th><th>材料</th><th>驳回次数</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td><div class="primary-cell"><span class="row-icon">{{ row.userName.charAt(0) }}</span><div><strong>{{ row.userName }}</strong><em>{{ row.userPhone }}</em></div></div></td>
            <td>{{ row.typeLabel }}</td>
            <td>{{ row.communityName }}</td>
            <td>{{ row.materialsCount ?? (row.materials?.length || 0) }} 份</td>
            <td>{{ row.rejectCount || 0 }}</td>
            <td><StatusBadge :value="row.status" /></td>
            <td>{{ row.submittedAt }}</td>
            <td><button class="row-action" @click="open(row)">审核</button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无待审核申请" description="队列已清空，可切换状态查看历史" />
    </div>
    <div class="pagination"><span>共 {{ total }} 条记录</span><div><button :disabled="page <= 1" @click="page--; load()">上一页</button><button class="current">{{ page }}</button><button @click="page++; load()">下一页</button></div></div>
  </section>

  <NiDrawer :open="drawerOpen" :title="selected ? `${selected.typeLabel} · ${selected.user?.nickname || ''}` : '审核详情'" eyebrow="住户认证" @close="drawerOpen = false">
    <template v-if="selected">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <ShieldCheck :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">目标小区 / 状态</span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ selected.community?.name || '实名认证' }}</strong>
        </div>
        <StatusBadge :value="selected.status" />
      </div>
      <h4 class="section-title">申请信息</h4>
      <div class="form-grid">
        <label><span>申请人</span><input :value="selected.user?.nickname" disabled /></label>
        <label><span>手机号（脱敏）</span><input :value="selected.user?.phone" disabled /></label>
        <label><span>身份类型</span><input :value="selected.identity === 'owner' ? '业主' : selected.identity === 'tenant' ? '租户' : selected.identity === 'family' ? '家属' : '—'" disabled /></label>
        <label><span>追踪号</span><input :value="selected.traceId" disabled /></label>
      </div>
      <h4 class="section-title" style="margin-top: 20px">材料（私有桶签名 URL，10 分钟时效）</h4>
      <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px">
        <a v-for="material in selected.materials || []" :key="material.objectKey"
          :href="material.signedUrl || undefined" target="_blank"
          style="display: flex; align-items: center; gap: 6px; padding: 9px 10px; border: 1px solid #e9e6ed; border-radius: 8px; color: #554761; font-size: var(--font-size-body)">
          <FileImage :size="15" />{{ material.objectKey.split('/').pop() }}
        </a>
        <p v-if="!(selected.materials || []).length" style="color: #988da2; font-size: var(--font-size-body)">无材料</p>
      </div>
      <h4 class="section-title" style="margin-top: 20px">审核操作</h4>
      <label class="full" style="display: block"><span style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 4px">驳回原因（驳回必填，≥10 字，将通知申请人）</span>
        <textarea v-model="rejectReason" placeholder="例如：房产证照片模糊无法辨认产权人信息，请在自然光下重新拍摄" style="width: 100%; min-height: 72px" /></label>
    </template>
    <template #footer>
      <button @click="requestMaterials">要求补充材料</button>
      <button @click="reject" style="color: #c0392b">驳回</button>
      <button v-if="auth.hasPermission('community:resident:audit')" class="primary-button" @click="approve">通过并绑定</button>
    </template>
  </NiDrawer>
</template>
