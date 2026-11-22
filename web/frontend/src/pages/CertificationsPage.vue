<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ChevronDown, ClipboardCheck, Eye, FileImage, Filter, Search, ShieldCheck } from 'lucide-vue-next'
import { certificationsApi } from '@/api'
import { fmtDateTime, mapStatus } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useTodoStore } from '@/stores/todos'
import { useConfirm } from '@/composables/useConfirm'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import CommunityFilterBar from '@/components/CommunityFilterBar.vue'

const route = useRoute()
const app = useAppStore()
const auth = useAuthStore()
const todos = useTodoStore()
const { confirm } = useConfirm()
const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const activeTab = ref('PENDING')
const typeFilter = ref('')
const query = ref('')
const selected = ref<any>(null)
const drawerOpen = ref(false)
// 查看 / 审核双模式：非待审核记录只能查看，避免误触状态机返回 422。
const drawerMode = ref<'audit' | 'view'>('audit')
const rejectReason = ref('')
const loading = ref(false)
const summaryData = ref({
  pending: 0,
  pendingRealname: 0,
  pendingOwner: 0,
  supplement: 0,
  todayReviewed: 0,
  oldestPendingAt: 0,
})

const tabs = [
  { key: 'PENDING', label: '待审核' },
  { key: 'VERIFIED', label: '已通过' },
  { key: 'REJECTED', label: '已驳回' },
  { key: 'SUPPLEMENT', label: '待补充' },
  { key: '', label: '全部' },
]

const typeFilterLabel = computed(() => {
  if (typeFilter.value === 'REALNAME') return '仅实名'
  if (typeFilter.value === 'OWNER_PROOF') return '仅住户认证'
  return '全部类型'
})
const canAuditSelected = computed(() =>
  drawerMode.value === 'audit' && selected.value?.status === 'PENDING')

async function loadSummary() {
  try {
    summaryData.value = await certificationsApi.summary({ communityId: app.currentCommunityId })
  } catch {
    // 统计失败不阻塞列表，页面仍可审核。
  }
}

async function load() {
  loading.value = true
  try {
    const params: any = {
      communityId: app.currentCommunityId,
      page: page.value,
      pageSize: 20,
    }
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

/** @param mode view=只读查看；audit=进入审核（仅待审核状态有效）。 */
async function open(rowOrId: any, mode: 'audit' | 'view' = 'audit') {
  const id = typeof rowOrId === 'object' ? rowOrId.id : rowOrId
  if (!id) return
  try {
    const detail = await certificationsApi.detail(id)
    selected.value = detail
    // 已通过/驳回/待补充等历史记录不允许再次审核，自动降级为只读查看。
    drawerMode.value = mode === 'audit' && detail?.status === 'PENDING' ? 'audit' : 'view'
    rejectReason.value = ''
    drawerOpen.value = true
  } catch (exc: any) {
    app.showToast(exc?.message || '详情加载失败')
  }
}

function cycleTypeFilter() {
  const order = ['', 'REALNAME', 'OWNER_PROOF']
  const index = order.indexOf(typeFilter.value)
  typeFilter.value = order[(index + 1) % order.length]
  page.value = 1
  load()
}

function materialLabel(index: number): string {
  const material = selected.value?.materials?.[index]
  if (material?.label) return material.label
  if (selected.value?.type === 'REALNAME') {
    return index === 0 ? '身份证人像面' : '身份证国徽面'
  }
  return `证明材料 ${index + 1}`
}

function isImageMaterial(objectKey: string): boolean {
  return /\.(jpe?g|png|webp)(\?|$)/i.test(objectKey || '')
}

async function refreshAfterAction() {
  drawerOpen.value = false
  await Promise.all([load(), loadSummary()])
  todos.refresh()
}

async function approve() {
  if (!(await confirm({ title: '通过认证申请', message: '确认通过该认证申请？通过后账号将与小区强绑定。', confirmText: '确认通过' }))) return
  try {
    await certificationsApi.approve(selected.value.id)
    app.showToast('已通过并通知申请人')
    await refreshAfterAction()
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
    await refreshAfterAction()
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
    await refreshAfterAction()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

onMounted(async () => {
  if (route.query.status) activeTab.value = String(route.query.status)
  if (route.query.type) typeFilter.value = String(route.query.type)
  await Promise.all([loadSummary(), load()])
  if (route.query.certId) await open(route.query.certId)
})

// 与社区运营 / 社区业主一致：顶部筛选切换小区后重置分页并刷新队列与统计。
watch(() => app.currentCommunityId, () => {
  page.value = 1
  Promise.all([loadSummary(), load()])
})
</script>

<template>
  <CommunityFilterBar scope-note="认证队列仅展示所选小区" />

  <section class="summary-row">
    <div><span>待审核</span><strong>{{ summaryData.pending }}</strong><em class="warn">目标 SLA ≤ 24h</em></div>
    <div><span>实名认证待审</span><strong>{{ summaryData.pendingRealname }}</strong><em>独立审核</em></div>
    <div><span>住户认证待审</span><strong>{{ summaryData.pendingOwner }}</strong><em>通过后绑定小区</em></div>
    <div><span>待补充</span><strong>{{ summaryData.supplement }}</strong><em>等待申请人补齐</em></div>
  </section>

  <section class="table-panel">
    <div class="table-toolbar">
      <div class="resident-tabs" style="margin-right: 12px">
        <button v-for="tab in tabs" :key="tab.key" :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key; page = 1; load()">{{ tab.label }}</button>
      </div>
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索申请人或追踪号…" @keyup.enter="page = 1; load()" /></div>
      <div class="toolbar-actions">
        <button @click="cycleTypeFilter">
          <Filter :size="16" />{{ typeFilterLabel }}<ChevronDown :size="14" />
        </button>
        <button class="primary-button" @click="load"><ClipboardCheck :size="16" />刷新队列</button>
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
            <td>
              <div class="row-actions">
                <button class="row-icon-button" aria-label="查看认证详情" data-tip="查看详情" @click="open(row, 'view')">
                  <Eye :size="15" />
                </button>
                <button
                  v-if="row.statusCode === 'PENDING'"
                  class="row-icon-button"
                  aria-label="审核认证申请"
                  data-tip="审核"
                  @click="open(row, 'audit')"
                >
                  <ClipboardCheck :size="15" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无待审核申请" description="队列已清空，可切换状态查看历史" />
    </div>
    <div class="pagination"><span>共 {{ total }} 条记录</span><div><button :disabled="page <= 1" @click="page--; load()">上一页</button><button class="current">{{ page }}</button><button @click="page++; load()">下一页</button></div></div>
  </section>

  <NiDrawer
    :open="drawerOpen"
    :title="selected ? `${selected.typeLabel} · ${selected.user?.nickname || ''}` : '认证详情'"
    :eyebrow="drawerMode === 'audit' ? '住户认证审核' : '住户认证详情'"
    @close="drawerOpen = false"
  >
    <template v-if="selected">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <ShieldCheck :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">{{ selected.typeLabel }} / 目标小区</span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ selected.community?.name || '实名认证（不绑定小区）' }}</strong>
        </div>
        <StatusBadge :value="mapStatus(selected.status)" />
      </div>
      <h4 class="section-title">申请信息</h4>
      <div class="form-grid">
        <label><span>申请人</span><input :value="selected.user?.nickname || '—'" disabled /></label>
        <label><span>手机号（脱敏）</span><input :value="selected.user?.phone || '—'" disabled /></label>
        <label><span>身份类型</span><input :value="selected.identity === 'owner' ? '业主' : selected.identity === 'tenant' ? '租户' : selected.identity === 'family' ? '家属' : selected.identity === 'business' ? '商务人员' : '—'" disabled /></label>
        <label><span>追踪号</span><input :value="selected.traceId || '—'" disabled /></label>
        <label><span>提交时间</span><input :value="fmtDateTime(selected.submittedAt)" disabled /></label>
        <label><span>最近审核时间</span><input :value="selected.reviewedAt ? fmtDateTime(selected.reviewedAt) : '尚未审核'" disabled /></label>
        <label><span>驳回次数</span><input :value="String(selected.rejectCount || 0)" disabled /></label>
      </div>
      <template v-if="selected.rejectReason">
        <h4 class="section-title" style="margin-top: 20px">最近驳回原因</h4>
        <p style="margin: 0; color: #a3525b; font-size: var(--font-size-body); line-height: 1.7; white-space: pre-wrap">{{ selected.rejectReason }}</p>
      </template>
      <h4 class="section-title" style="margin-top: 20px">材料（私有桶签名 URL，10 分钟时效）</h4>
      <div class="material-grid">
        <a v-for="(material, index) in selected.materials || []" :key="material.objectKey"
          :href="material.signedUrl || undefined" target="_blank" rel="noopener"
          class="material-card" :class="{ 'material-card--disabled': !material.signedUrl }">
          <img v-if="material.signedUrl && isImageMaterial(material.objectKey)" class="material-thumb"
            :src="material.signedUrl" :alt="materialLabel(index)" />
          <FileImage v-else :size="15" />
          <span>{{ materialLabel(index) }}</span>
        </a>
        <p v-if="!(selected.materials || []).length" style="color: #988da2; font-size: var(--font-size-body)">无材料</p>
      </div>
      <p v-if="(selected.materials || []).some((material: any) => !material.signedUrl)"
        style="margin-top: 8px; color: #c08a35; font-size: var(--font-size-caption)">
        部分材料签名 URL 生成失败，请确认 MinIO 已启动且对象存在。
      </p>
      <div v-if="selected.type === 'OWNER_PROOF'" class="community-selector-card"
        style="min-height: 52px; padding: 9px 12px; margin-top: 12px; margin-bottom: 0">
        <ShieldCheck :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">申请人实名状态</span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">
            {{ selected.user?.realnameStatus === 'VERIFIED' ? '已实名认证' : '尚未完成实名认证（不影响本次住户认证审批）' }}
          </strong>
        </div>
      </div>
      <template v-if="canAuditSelected">
        <h4 class="section-title" style="margin-top: 20px">审核操作</h4>
        <label class="full" style="display: block"><span style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 4px">驳回原因（驳回必填，≥10 字，将通知申请人）</span>
          <textarea v-model="rejectReason" placeholder="例如：房产证照片模糊无法辨认产权人信息，请在自然光下重新拍摄" style="width: 100%; min-height: 72px" /></label>
      </template>
      <p v-else class="cert-readonly-note">
        该申请当前状态为「{{ mapStatus(selected.status) }}」，仅可查看历史信息，不能再次审核。
        <template v-if="selected.status === 'PENDING'">如需处理，请点击下方「进入审核」。</template>
      </p>
    </template>
    <template #footer>
      <template v-if="canAuditSelected">
        <button @click="requestMaterials">要求补充材料</button>
        <button @click="reject" style="color: #c0392b">驳回</button>
        <button v-if="auth.hasPermission('community:resident:audit')" class="primary-button" @click="approve">通过并绑定</button>
      </template>
      <template v-else>
        <button @click="drawerOpen = false">关闭</button>
        <button v-if="selected?.status === 'PENDING'" class="primary-button" @click="drawerMode = 'audit'">进入审核</button>
      </template>
    </template>
  </NiDrawer>
</template>

<style scoped>
.cert-readonly-note { margin: 18px 0 0; padding: 9px 11px; border-radius: 8px; color: #7a7482; background: #f7f5fa; font-size: var(--font-size-caption); line-height: 1.6; }
</style>
