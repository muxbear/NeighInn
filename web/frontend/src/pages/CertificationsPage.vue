<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ChevronDown, ClipboardCheck, Eye, FileImage, Filter, Plus, Search, ShieldCheck } from 'lucide-vue-next'
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
// 查看 / 审核双模式：待审核、已驳回、待补充均可进入审核；已通过/冻结/撤销只读。
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

// 驳回 / 待补充的审核单也允许复核：住户无法自行重提或线下已补验材料时，
// 管理员核对后可恢复认证，不再被「仅可查看」卡住。
const REAUDITABLE = new Set(['PENDING', 'REJECTED', 'SUPPLEMENT'])
const IDENTITY_OPTIONS = [
  { value: 'owner', label: '业主' },
  { value: 'tenant', label: '租户' },
  { value: 'family', label: '家属' },
  { value: 'business', label: '商务人员' },
  { value: 'staff', label: '教职工' },
  { value: 'student', label: '学生' },
]
const IDENTITY_CODE_BY_LABEL: Record<string, string> = {
  业主: 'owner', 租户: 'tenant', 家属: 'family', 商务人员: 'business',
  教职工: 'staff', 学生: 'student',
}
const IDENTITY_LABEL_BY_CODE: Record<string, string> = {
  owner: '业主', tenant: '租户', family: '家属', business: '商务人员',
  staff: '教职工', student: '学生',
}

// 新增认证：选择本小区认证未通过的住户，上传材料后直接人工认证。
const manualOpen = ref(false)
const manualType = ref<'OWNER_PROOF' | 'REALNAME'>('OWNER_PROOF')
const manualKeyword = ref('')
const manualLoading = ref(false)
const manualCandidates = ref<any[]>([])
const manualSelected = ref<any>(null)
const manualIdentity = ref('owner')
const manualNote = ref('')
const manualMaterials = ref<any[]>([])
const manualMaterialsLoading = ref(false)
const manualUploading = ref(false)
const manualSubmitting = ref(false)

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
  drawerMode.value === 'audit' && REAUDITABLE.has(selected.value?.status))
const selectedIsPending = computed(() => selected.value?.status === 'PENDING')
const manualCommunityName = computed(() => app.currentCommunity?.name || '当前小区')

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
    // 已通过/冻结/撤销的记录不允许再次审核，自动降级为只读查看。
    drawerMode.value = mode === 'audit' && REAUDITABLE.has(detail?.status) ? 'audit' : 'view'
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

/** 材料读取地址：优先后端同源代理（不依赖浏览器访问 MinIO 主机），回退签名 URL。 */
function materialSrc(material: any): string {
  return material?.url || material?.signedUrl || ''
}

async function refreshAfterAction() {
  drawerOpen.value = false
  await Promise.all([load(), loadSummary()])
  todos.refresh()
}

async function approve() {
  const message = selected.value?.type === 'REALNAME'
    ? '确认通过该实名认证申请？通过后账号实名状态将更新为已认证。'
    : selected.value?.status === 'PENDING'
      ? '确认通过该认证申请？通过后账号将与小区强绑定。'
      : '该申请此前未通过，确认复核通过并恢复认证？通过后账号将与小区强绑定。'
  if (!(await confirm({ title: '通过认证申请', message, confirmText: '确认通过' }))) return
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

// ---------------------------------------------------------------- 新增认证（人工认证）

function openManual() {
  manualOpen.value = true
  manualSelected.value = null
  manualMaterials.value = []
  manualNote.value = ''
  manualKeyword.value = ''
  manualType.value = 'OWNER_PROOF'
  manualIdentity.value = 'owner'
  loadCandidates()
}

function closeManual() {
  if (manualSubmitting.value) return
  manualOpen.value = false
}

async function loadCandidates() {
  manualLoading.value = true
  try {
    manualCandidates.value = (await certificationsApi.candidates({
      communityId: app.currentCommunityId,
      type: manualType.value,
      keyword: manualKeyword.value.trim() || undefined,
      limit: 30,
    })) || []
  } catch (exc: any) {
    manualCandidates.value = []
    app.showToast(exc?.message || '可认证住户加载失败')
  } finally {
    manualLoading.value = false
  }
}

async function switchManualType(type: 'OWNER_PROOF' | 'REALNAME') {
  if (manualType.value === type) return
  manualType.value = type
  manualSelected.value = null
  manualMaterials.value = []
  await loadCandidates()
}

async function selectCandidate(row: any) {
  if (row.eligible === false) {
    app.showToast(row.eligibleReason || '该住户暂不可认证')
    return
  }
  manualSelected.value = row
  manualIdentity.value = IDENTITY_CODE_BY_LABEL[row.identity] || 'owner'
  manualMaterials.value = []
  await loadManualMaterials()
}

async function loadManualMaterials() {
  if (!manualSelected.value) return
  manualMaterialsLoading.value = true
  try {
    const data = await certificationsApi.materials(manualSelected.value.id, manualType.value)
    manualMaterials.value = data?.materials || []
  } catch (exc: any) {
    manualMaterials.value = []
    app.showToast(exc?.message || '认证材料加载失败')
  } finally {
    manualMaterialsLoading.value = false
  }
}

async function onManualMaterialSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !manualSelected.value) return
  manualUploading.value = true
  try {
    const data = await certificationsApi.uploadMaterial(
      manualSelected.value.id, manualType.value, file)
    manualMaterials.value = data?.materials || []
    app.showToast('认证材料已上传')
  } catch (exc: any) {
    app.showToast(exc?.message || '认证材料上传失败')
  } finally {
    manualUploading.value = false
  }
}

async function removeManualMaterial(objectKey: string) {
  if (!manualSelected.value) return
  if (!(await confirm({
    title: '删除认证材料',
    message: '确定删除该认证材料吗？对象文件将保留在私有桶供审计追溯。',
    confirmText: '确认删除',
    danger: true,
  }))) return
  try {
    const data = await certificationsApi.removeMaterial(
      manualSelected.value.id, manualType.value, objectKey)
    manualMaterials.value = data?.materials || []
    app.showToast('认证材料已删除')
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

async function submitManualVerify() {
  if (!manualSelected.value || manualSubmitting.value) return
  const typeLabel = manualType.value === 'OWNER_PROOF' ? '住户认证' : '身份认证'
  if (!(await confirm({
    title: `确认${typeLabel}通过`,
    message: manualType.value === 'OWNER_PROOF'
      ? `确认将「${manualSelected.value.name}」的住户认证置为已认证并绑定「${manualCommunityName.value}」？请确保已核对相关证件原件。`
      : `确认将「${manualSelected.value.name}」的身份认证（实名）置为已认证？请确保已核对身份证件。`,
    confirmText: '确认通过',
  }))) return
  manualSubmitting.value = true
  try {
    await certificationsApi.verifyResident(manualSelected.value.id, manualType.value, {
      identity: manualType.value === 'OWNER_PROOF' ? manualIdentity.value : undefined,
      note: manualNote.value.trim(),
    })
    app.showToast(`${typeLabel}已通过`)
    manualOpen.value = false
    await refreshAfterAction()
  } catch (exc: any) {
    app.showToast(exc?.message || '认证失败')
  } finally {
    manualSubmitting.value = false
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
  if (manualOpen.value) {
    manualSelected.value = null
    manualMaterials.value = []
    loadCandidates()
  }
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
      <div class="table-search">
        <Search :size="17" /><input v-model="query" placeholder="搜索申请人或追踪号…" @keyup.enter="page = 1; load()" />
      </div>
      <div class="toolbar-actions">
        <button @click="cycleTypeFilter">
          <Filter :size="16" />{{ typeFilterLabel }}
          <ChevronDown :size="14" />
        </button>
        <button @click="load">
          <ClipboardCheck :size="16" />刷新队列
        </button>
        <button v-if="auth.hasPermission('community:resident:audit')" class="primary-button" @click="openManual">
          <Plus :size="16" />新增认证
        </button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>申请人</th>
            <th>类型</th>
            <th>目标小区</th>
            <th>材料</th>
            <th>驳回次数</th>
            <th>状态</th>
            <th>提交时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <div class="primary-cell"><span class="row-icon">{{ row.userName.charAt(0) }}</span>
                <div><strong>{{ row.userName }}</strong><em>{{ row.userPhone }}</em></div>
              </div>
            </td>
            <td>{{ row.typeLabel }}</td>
            <td>{{ row.communityName }}</td>
            <td>{{ row.materialsCount ?? (row.materials?.length || 0) }} 份</td>
            <td>{{ row.rejectCount || 0 }}</td>
            <td>
              <StatusBadge :value="row.status" />
            </td>
            <td>{{ row.submittedAt }}</td>
            <td>
              <div class="row-actions">
                <button class="row-icon-button" aria-label="查看认证详情" data-tip="查看详情" @click="open(row, 'view')">
                  <Eye :size="15" />
                </button>
                <button v-if="REAUDITABLE.has(row.statusCode)" class="row-icon-button"
                  aria-label="审核认证申请" data-tip="审核" @click="open(row, 'audit')">
                  <ClipboardCheck :size="15" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无待审核申请" description="队列已清空，可切换状态查看历史" />
    </div>
    <div class="pagination"><span>共 {{ total }} 条记录</span>
      <div><button :disabled="page <= 1" @click="page--; load()">上一页</button><button class="current">{{ page
          }}</button><button @click="page++; load()">下一页</button></div>
    </div>
  </section>

  <NiDrawer :open="drawerOpen" :title="selected ? `${selected.typeLabel} · ${selected.user?.nickname || ''}` : '认证详情'"
    :eyebrow="drawerMode === 'audit' ? '住户认证审核' : '住户认证详情'" @close="drawerOpen = false">
    <template v-if="selected">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <ShieldCheck :size="18" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">{{ selected.typeLabel }} /
            目标小区</span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ selected.community?.name
            || '实名认证（不绑定小区）' }}</strong>
        </div>
        <StatusBadge :value="mapStatus(selected.status)" />
      </div>
      <h4 class="section-title">申请信息</h4>
      <div class="form-grid">
        <label><span>申请人</span><input :value="selected.user?.nickname || '—'" disabled /></label>
        <label><span>手机号（脱敏）</span><input :value="selected.user?.phone || '—'" disabled /></label>
        <label><span>身份类型</span><input
            :value="IDENTITY_LABEL_BY_CODE[selected.identity] || '—'"
            disabled /></label>
        <label><span>追踪号</span><input :value="selected.traceId || '—'" disabled /></label>
        <label><span>提交时间</span><input :value="fmtDateTime(selected.submittedAt)" disabled /></label>
        <label><span>最近审核时间</span><input :value="selected.reviewedAt ? fmtDateTime(selected.reviewedAt) : '尚未审核'"
            disabled /></label>
        <label><span>驳回次数</span><input :value="String(selected.rejectCount || 0)" disabled /></label>
        <label v-if="selected.status === 'REJECTED'" class="full"><span>上次驳回原因</span>
          <textarea :value="selected.rejectReason || '—'" disabled />
        </label>
        <label v-else-if="selected.status === 'SUPPLEMENT'" class="full"><span>补充材料说明</span>
          <textarea :value="selected.reviewNote || '—'" disabled />
        </label>
      </div>
      <h4 class="section-title" style="margin-top: 20px">材料（私有桶签名 URL，10 分钟时效）</h4>
      <div class="material-grid">
        <a v-for="(material, index) in selected.materials || []" :key="material.objectKey"
          :href="materialSrc(material) || undefined" target="_blank" rel="noopener" class="material-card"
          :class="{ 'material-card--disabled': !materialSrc(material) }">
          <img v-if="materialSrc(material) && isImageMaterial(material.objectKey)" class="material-thumb"
            :src="materialSrc(material)" :alt="materialLabel(index)" />
          <FileImage v-else :size="15" />
          <span>{{ materialLabel(index) }}</span>
        </a>
        <p v-if="!(selected.materials || []).length" style="color: #988da2; font-size: var(--font-size-body)">无材料</p>
      </div>
      <p v-if="(selected.materials || []).some((material: any) => !materialSrc(material))"
        style="margin-top: 8px; color: #c08a35; font-size: var(--font-size-caption)">
        部分材料读取地址缺失，请确认对象存储已配置且对象存在。
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
        <label v-if="selectedIsPending" class="full" style="display: block"><span
            style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 4px">驳回原因（驳回必填，≥10
            字，将通知申请人）</span>
          <textarea v-model="rejectReason" placeholder="例如：房产证照片模糊无法辨认产权人信息，请在自然光下重新拍摄"
            style="width: 100%; min-height: 72px" /></label>
        <p v-else class="cert-reviewable-note">
          该申请当前为「{{ mapStatus(selected.status) }}」。线下补验材料后可直接「认证通过」；
          如需住户补充材料，请让住户在移动端重新提交，新材料会进入待审核队列。
        </p>
      </template>
      <p v-else class="cert-readonly-note">
        该申请当前状态为「{{ mapStatus(selected.status) }}」，仅可查看历史信息。
        <template v-if="selected?.status === 'FROZEN'">如需恢复认证，请在「社区业主」页调整认证状态。</template>
        <template v-else-if="selected?.status === 'REVOKED'">认证已撤销，需住户重新提交认证材料。</template>
        <template v-else>该状态不支持再次审核。</template>
      </p>
    </template>
    <template #footer>
      <template v-if="canAuditSelected">
        <template v-if="selectedIsPending">
          <button @click="requestMaterials">要求补充材料</button>
          <button @click="reject" style="color: #c0392b">驳回</button>
        </template>
        <button v-if="auth.hasPermission('community:resident:audit')" class="primary-button"
          @click="approve">{{ selectedIsPending ? '通过并绑定' : '认证通过' }}</button>
      </template>
      <template v-else>
        <button @click="drawerOpen = false">关闭</button>
        <button v-if="REAUDITABLE.has(selected?.status)" class="primary-button"
          @click="drawerMode = 'audit'">进入审核</button>
      </template>
    </template>
  </NiDrawer>

  <!-- 新增认证：未通过住户（未提交 / 待审核 / 待补充 / 已驳回）可由后台人工认证 -->
  <NiDrawer :open="manualOpen" title="新增认证" eyebrow="住户身份认证" @close="closeManual">
    <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
      <ShieldCheck :size="18" style="color: #6852c5" />
      <div style="flex: 1">
        <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">认证归属小区</span>
        <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ manualCommunityName }}</strong>
      </div>
    </div>

    <h4 class="section-title">1. 选择认证类型与住户</h4>
    <div class="manual-type-tabs">
      <button :class="{ active: manualType === 'OWNER_PROOF' }" @click="switchManualType('OWNER_PROOF')">住户认证</button>
      <button :class="{ active: manualType === 'REALNAME' }" @click="switchManualType('REALNAME')">身份认证（实名）</button>
    </div>
    <div class="table-search" style="width: 100%; margin-bottom: 10px">
      <Search :size="17" />
      <input v-model="manualKeyword" placeholder="搜索姓名、昵称或房屋…" @keyup.enter="loadCandidates" />
      <button v-if="manualKeyword" class="manual-search-clear" @click="manualKeyword = ''; loadCandidates()">清空</button>
    </div>
    <div class="manual-candidate-list">
      <div v-if="manualLoading" class="manual-hint">正在加载可认证住户…</div>
      <button v-for="row in manualCandidates" :key="row.id" type="button"
        :class="['manual-candidate', { selected: manualSelected?.id === row.id, disabled: row.eligible === false }]"
        :disabled="row.eligible === false" @click="selectCandidate(row)">
        <span class="manual-candidate-avatar">{{ (row.nickname || row.name || '?').charAt(0) }}</span>
        <span class="manual-candidate-main">
          <strong>{{ row.name || row.nickname }}</strong>
          <em>{{ row.identity }} · {{ row.building || '未填写房屋' }} · {{ row.phone || '无手机号' }}</em>
        </span>
        <span class="manual-candidate-state">
          <StatusBadge :value="row.certificationStatusLabel || mapStatus(row.certificationStatus)" />
          <em v-if="row.eligible === false" class="manual-ineligible">{{ row.eligibleReason }}</em>
        </span>
      </button>
      <EmptyState v-if="!manualLoading && !manualCandidates.length" title="未找到可认证住户"
        description="请切换认证类型、调整搜索词，或确认所选小区" />
    </div>

    <template v-if="manualSelected">
      <h4 class="section-title" style="margin-top: 20px">2. 认证信息</h4>
      <div class="form-grid">
        <label><span>住户</span><input :value="manualSelected.name || manualSelected.nickname" disabled /></label>
        <label><span>手机号（脱敏）</span><input :value="manualSelected.phone || '—'" disabled /></label>
        <label><span>房屋 / 商铺</span><input :value="manualSelected.building || '—'" disabled /></label>
        <label v-if="manualType === 'OWNER_PROOF'"><span>身份类型</span>
          <select v-model="manualIdentity">
            <option v-for="option in IDENTITY_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label><span>当前状态</span><input :value="mapStatus(manualSelected.certificationStatus)" disabled /></label>
        <label class="full"><span>审核说明（可选，写入审计记录）</span>
          <textarea v-model="manualNote" maxlength="500"
            placeholder="例如：已线下核验房产证原件及业主身份证，材料与住户信息一致" />
        </label>
      </div>

      <h4 class="section-title" style="margin-top: 20px">3. 认证材料（可选，建议上传）</h4>
      <div class="cert-material-block">
        <div v-if="manualMaterialsLoading" class="cert-material-hint">正在加载认证材料…</div>
        <div v-else-if="manualMaterials.length" class="cert-material-thumbs">
          <div v-for="material in manualMaterials" :key="material.objectKey" class="cert-material-thumb">
            <a v-if="materialSrc(material)" :href="materialSrc(material)" target="_blank" rel="noopener">
              <img v-if="isImageMaterial(material.objectKey)" :src="materialSrc(material)" :alt="material.label" />
              <div v-else class="cert-material-missing">点击查看材料</div>
            </a>
            <div v-else class="cert-material-missing">材料读取地址缺失</div>
            <div class="cert-material-foot">
              <span>{{ material.label }}</span>
              <button type="button" @click="removeManualMaterial(material.objectKey)">删除</button>
            </div>
          </div>
        </div>
        <div v-else class="cert-material-hint">暂无认证材料，可直接认证或上传留档</div>
        <label class="cert-material-upload">
          <input type="file" :accept="manualType === 'OWNER_PROOF'
            ? 'image/jpeg,image/png,image/webp,application/pdf'
            : 'image/jpeg,image/png,image/webp'"
            @change="onManualMaterialSelected" />
          <span>{{ manualUploading ? '上传中…' : '上传认证材料' }}</span>
        </label>
      </div>
      <p class="cert-reviewable-note" style="margin-top: 12px">
        确认通过后，住户认证会绑定到「{{ manualCommunityName }}」；已驳回、待补充的记录将复用原审核单并流转为已认证。
        请确保已核对证件原件或照片，操作将写入审计日志并通知住户。
      </p>
    </template>
    <template #footer>
      <button :disabled="manualSubmitting" @click="closeManual">取消</button>
      <button class="primary-button" :disabled="!manualSelected || manualSubmitting" @click="submitManualVerify">
        {{ manualSubmitting ? '提交中…' : '认证通过' }}
      </button>
    </template>
  </NiDrawer>
</template>

<style scoped>
.cert-readonly-note,
.cert-reviewable-note {
  margin: 18px 0 0;
  padding: 9px 11px;
  border-radius: 8px;
  color: #7a7482;
  background: #f7f5fa;
  font-size: var(--font-size-caption);
  line-height: 1.6;
}

.cert-reviewable-note {
  margin-top: 12px;
  color: #7d6a3f;
  background: #fdf7e9;
}

.manual-type-tabs {
  display: flex;
  gap: 4px;
  padding: 3px;
  margin-bottom: 10px;
  border: 1px solid #e7e3ed;
  border-radius: 9px;
  background: #f8f6fa;
}

.manual-type-tabs button {
  flex: 1;
  height: 32px;
  border: 0;
  border-radius: 7px;
  color: #7a7482;
  background: transparent;
  font-size: var(--font-size-body);
  cursor: pointer;
}

.manual-type-tabs button.active {
  color: #5a45b5;
  background: #fff;
  box-shadow: 0 2px 6px rgba(111, 89, 212, .12);
  font-weight: 600;
}

.manual-search-clear {
  flex: 0 0 auto;
  color: #7c6bc4;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.manual-candidate-list {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid #e7e3ed;
  border-radius: 10px;
  background: #fff;
}

.manual-candidate {
  width: 100%;
  padding: 9px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  border: 0;
  border-bottom: 1px solid #f1eef5;
  color: #4a4552;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.manual-candidate:last-child { border-bottom: 0; }
.manual-candidate:hover:not(.disabled) { background: #fbf9ff; }

.manual-candidate.selected {
  background: #f3effd;
  box-shadow: inset 3px 0 0 #6f59d4;
}

.manual-candidate.disabled {
  cursor: not-allowed;
  opacity: .62;
}

.manual-candidate-avatar {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: #fff;
  background: linear-gradient(135deg, #8b76e0, #6f59d4);
  font-size: var(--font-size-body);
  font-weight: 600;
}

.manual-candidate-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.manual-candidate-main strong {
  overflow: hidden;
  color: #4a4552;
  font-size: var(--font-size-body);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.manual-candidate-main em {
  overflow: hidden;
  color: #938d9c;
  font-size: var(--font-size-caption);
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.manual-candidate-state {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}

.manual-ineligible {
  color: #c08a35;
  font-size: var(--font-size-caption);
  font-style: normal;
}

.manual-hint {
  padding: 24px 12px;
  color: #9b96a3;
  font-size: var(--font-size-caption);
  text-align: center;
}
</style>
