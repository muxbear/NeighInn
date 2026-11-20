<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Building2, Camera, ChevronDown, Copy, Filter, Home, KeyRound, Pencil, Plus, Search, Settings2, ShieldCheck, ShieldOff, Trash2, UserRound, Users, X } from 'lucide-vue-next'
import { certificationsApi, residentAdminApi, residentApi } from '@/api'
import { fmtDateTime, mapStatus } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useConfirm } from '@/composables/useConfirm'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import CommunityFilterBar from '@/components/CommunityFilterBar.vue'

const app = useAppStore()
const auth = useAuthStore()
const { confirm, confirmWithCheckbox } = useConfirm()
const rows = ref<any[]>([])
const summary = ref<any>({ total: 0, owner: 0, family: 0, pending: 0 })
const activeTab = ref('全部人员')
const query = ref('')
const page = ref(1)
const total = ref(0)
const drawerOpen = ref(false)
const editing = ref<any>(null)
const form = ref<any>({})
const selected = ref<Set<string>>(new Set())

// 认证材料查看：点击身份认证 / 业主认证状态徽标后加载签名 URL 照片。
const certViewerOpen = ref(false)
const certViewerLoading = ref(false)
const certViewerError = ref('')
const certViewerTitle = ref('')
const certViewerData = ref<any>(null)
const certPhotoErrors = ref<Record<string, boolean>>({})

// 编辑弹窗内的认证材料维护（身份认证 / 业主认证）。
const CERT_TYPE_BY_KIND = { realname: 'REALNAME', owner: 'OWNER_PROOF' } as const
const certMaterials = ref<Record<'realname' | 'owner', any[]>>({ realname: [], owner: [] })
const certMaterialsLoading = ref<Record<'realname' | 'owner', boolean>>({ realname: false, owner: false })
const certUploading = ref<Record<'realname' | 'owner', boolean>>({ realname: false, owner: false })
const certMaterialErrors = ref<Record<string, boolean>>({})

// 住户后台身份授权：社区业主页选择住户 → 授予「角色权限」中可授予住户的角色。
const grantOpen = ref(false)
const grantTarget = ref<any>(null)
const grantLoading = ref(false)
const grantSubmitting = ref(false)
const grantRoles = ref<any[]>([])
const grantState = ref<any>({ eligible: false, eligibleReason: '', account: null })
const grantForm = ref({ roleIds: [] as number[], username: '', reason: '' })
const grantResult = ref<any>(null)
const resetting = ref('')

const canGrantAdmin = computed(() => auth.hasPermission('community:resident:admin-grant'))
const canRevokeAdmin = computed(() => auth.hasPermission('community:resident:admin-revoke'))
// 注销移动端账号比删除档案更敏感：后台需额外具备「编辑用户」权限。
const canCancelAccount = computed(() => auth.hasPermission('system:user:update'))
const loginUrl = computed(() => `${window.location.origin}/login`)

const AVATAR_TONES = ['violet', 'blue', 'green', 'orange', 'plum', 'teal']

const tabs = ['全部人员', '业主', '家属', '租户', '商务人员']
const community = computed(() => app.currentCommunity)
const summaryCards = computed(() => [
  { label: '全部人员', value: summary.value.total, icon: Users, tone: 'violet' },
  { label: '业主', value: summary.value.owner, icon: Home, tone: 'blue' },
  { label: '家属与租户', value: summary.value.family, icon: UserRound, tone: 'green' },
  { label: '待完成认证', value: summary.value.pending, icon: ShieldCheck, tone: 'orange' },
])
const canBatchRemove = computed(() => auth.hasPermission('community:resident:update'))
const selectedCount = computed(() => selected.value.size)
const allSelected = computed(() =>
  rows.value.length > 0 && rows.value.every((row) => selected.value.has(row.id)))

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
    selected.value = new Set()
  } catch (exc: any) {
    app.showToast(exc?.message || '业主档案加载失败')
  }
}

function openCreate() {
  editing.value = null
  certMaterials.value = { realname: [], owner: [] }
  certMaterialErrors.value = {}
  form.value = {
    communityId: app.currentCommunityId, name: '', nickname: '', email: '', bio: '',
    gender: '女', phone: '', identity: '业主',
    building: '', relationship: '房屋产权人', certification: '未认证', certificationNo: '',
    realnameStatus: null, creditScore: null,
    level: '普通用户', status: '正常', joinedAt: '',
  }
  drawerOpen.value = true
}

function openEdit(row: any) {
  editing.value = row
  form.value = {
    ...row,
    communityId: Number(row.communityId),
    nickname: row.nickname || '',
    email: row.email || '',
    bio: row.bio || '',
    realnameStatus: row.realnameStatus || 'UNVERIFIED',
    creditScore: row.creditScore ?? 0,
    joinedAt: row.joinedAt && row.joinedAt !== '—' ? row.joinedAt : '',
  }
  drawerOpen.value = true
  certMaterials.value = { realname: [], owner: [] }
  certMaterialErrors.value = {}
  loadCertMaterials('realname')
  loadCertMaterials('owner')
}

async function save() {
  if (!form.value.name?.trim()) {
    app.showToast('请填写人员姓名')
    return
  }
  const payload: any = { ...form.value }
  // 列表返回的为脱敏手机号；未重新输入时不提交，避免覆盖真实号码。
  if (editing.value && String(payload.phone || '').includes('*')) delete payload.phone
  // 留空表示不修改身份认证状态 / 信用分。
  if (payload.realnameStatus === null || payload.realnameStatus === '') delete payload.realnameStatus
  if (payload.creditScore === null || payload.creditScore === '' || Number.isNaN(Number(payload.creditScore))) {
    delete payload.creditScore
  } else {
    payload.creditScore = Number(payload.creditScore)
  }
  try {
    if (editing.value) await residentApi.update(editing.value.id, payload)
    else await residentApi.create(payload)
    drawerOpen.value = false
    app.showToast(editing.value ? '人员信息已更新' : '人员档案已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function remove(row: any) {
  const canCancel = canCancelAccount.value && Boolean(row.userId)
  const result = await confirmWithCheckbox({
    title: '删除人员档案',
    message: `确定删除“${row.name}”的社区人员档案吗？`,
    details: [
      '删除后档案不可恢复。',
      ...(row.userId
        ? ['默认保留移动端账号，用户仍可用该手机号登录。']
        : ['该档案未绑定移动端账号，不影响任何登录账号。']),
      ...(canCancel
        ? ['勾选注销账号后会清空该账号手机号并释放给新注册；认证与交易历史保留。']
        : []),
    ],
    confirmText: '确认删除',
    danger: true,
    checkboxLabel: canCancel
      ? '同时注销该住户的移动端账号（手机号可重新注册）'
      : '',
  })
  if (!result.confirmed) return
  try {
    const data = await residentApi.remove(row.id, result.checked)
    app.showToast(data?.accountCancelled
      ? '人员档案已删除，移动端账号已注销'
      : '人员档案已删除')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

function toggleRow(row: any) {
  const next = new Set(selected.value)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  selected.value = next
}

function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(rows.value.map((row) => row.id))
}

function clearSelection() {
  selected.value = new Set()
}

async function batchRemove() {
  const ids = Array.from(selected.value)
    .map((id) => Number(id))
    .filter((id) => Number.isFinite(id))
  if (!ids.length) return
  const result = await confirmWithCheckbox({
    title: '批量删除人员档案',
    message: `确定删除已选择的 ${ids.length} 份人员档案吗？`,
    details: [
      '删除后档案将从当前社区移除，已关联的认证审核单保留历史记录。',
      ...(canCancelAccount.value
        ? ['勾选注销账号时，任一关联账号存在其他社区档案或交易/资金记录，整批操作将不会执行。']
        : []),
    ],
    confirmText: '确认删除',
    danger: true,
    checkboxLabel: canCancelAccount.value
      ? '同时注销关联的移动端账号（账号需无其他社区档案及业务数据）'
      : '',
  })
  if (!result.confirmed) return
  try {
    const data = await residentApi.batchRemove(ids, result.checked)
    const deleted = Number(data?.deleted ?? ids.length)
    const cancelled = Number(data?.cancelledAccounts ?? 0)
    app.showToast(cancelled
      ? `已删除 ${deleted} 份人员档案，已注销 ${cancelled} 个移动端账号`
      : `已删除 ${deleted} 份人员档案`)
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '批量删除失败')
  }
}

function avatarTone(row: any) {
  const key = String(row.avatarKey || row.nickname || row.name || '')
  let hash = 0
  for (let index = 0; index < key.length; index += 1) {
    hash = (hash * 31 + key.charCodeAt(index)) >>> 0
  }
  return AVATAR_TONES[hash % AVATAR_TONES.length]
}

function avatarText(row: any) {
  return (row.nickname || row.name || '?').charAt(0)
}

function certOf(row: any, kind: 'realname' | 'owner') {
  return kind === 'realname' ? row.realnameCert : row.ownerCert
}

async function openCertViewer(row: any, kind: 'realname' | 'owner') {
  const cert = certOf(row, kind)
  if (!cert?.id) {
    app.showToast(kind === 'realname' ? '该人员暂无身份认证记录' : '该人员暂无业主认证记录')
    return
  }
  certViewerTitle.value = `${kind === 'realname' ? '身份认证' : '业主认证'} · ${row.name}`
  certViewerOpen.value = true
  certViewerLoading.value = true
  certViewerError.value = ''
  certViewerData.value = null
  certPhotoErrors.value = {}
  try {
    certViewerData.value = await certificationsApi.detail(cert.id)
  } catch (exc: any) {
    certViewerError.value = exc?.message || '认证材料加载失败'
  } finally {
    certViewerLoading.value = false
  }
}

function closeCertViewer() {
  certViewerOpen.value = false
  certViewerData.value = null
  certViewerError.value = ''
  certPhotoErrors.value = {}
}

function onCertPhotoError(objectKey: string) {
  certPhotoErrors.value = { ...certPhotoErrors.value, [objectKey]: true }
}

async function loadCertMaterials(kind: 'realname' | 'owner') {
  if (!editing.value?.id) return
  certMaterialsLoading.value[kind] = true
  try {
    const data = await certificationsApi.materials(editing.value.id, CERT_TYPE_BY_KIND[kind])
    certMaterials.value[kind] = data?.materials || []
  } catch (exc: any) {
    certMaterials.value[kind] = []
    app.showToast(exc?.message || '认证材料加载失败')
  } finally {
    certMaterialsLoading.value[kind] = false
  }
}

async function onCertMaterialSelected(kind: 'realname' | 'owner', event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !editing.value?.id) return
  certUploading.value[kind] = true
  try {
    const data = await certificationsApi.uploadMaterial(editing.value.id, CERT_TYPE_BY_KIND[kind], file)
    certMaterials.value[kind] = data?.materials || []
    certMaterialErrors.value = {}
    app.showToast('认证材料已上传')
  } catch (exc: any) {
    app.showToast(exc?.message || '认证材料上传失败')
  } finally {
    certUploading.value[kind] = false
  }
}

async function removeCertMaterial(kind: 'realname' | 'owner', objectKey: string) {
  if (!editing.value?.id) return
  if (!(await confirm({ title: '删除认证材料', message: '确定删除该认证材料吗？对象文件将保留在私有桶供审计追溯。', confirmText: '确认删除', danger: true }))) return
  try {
    const data = await certificationsApi.removeMaterial(
      editing.value.id, CERT_TYPE_BY_KIND[kind], objectKey)
    certMaterials.value[kind] = data?.materials || []
    app.showToast('认证材料已删除')
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

function markCertMaterialError(objectKey: string) {
  certMaterialErrors.value = { ...certMaterialErrors.value, [objectKey]: true }
}

// ---------------------------------------------------------------- 后台身份

function adminLabel(row: any): string {
  const account = row.adminAccount
  if (!account) return '未开通'
  if (account.status === 'DISABLED') return '已停用'
  const roles = (account.roles || []).map((role: any) => role.name).filter(Boolean)
  return roles.length ? roles.join('、') : '后台用户'
}

async function openGrant(row: any) {
  grantTarget.value = row
  grantOpen.value = true
  grantLoading.value = true
  grantResult.value = null
  grantForm.value = {
    roleIds: (row.adminAccount?.roles || []).length
      ? (row.adminAccount.roles || []).map((role: any) => Number(role.id)).filter((id: number) => id)
      : [],
    username: row.adminAccount?.username || '',
    reason: '',
  }
  try {
    const [rolesData, state] = await Promise.all([
      grantRoles.value.length ? Promise.resolve(grantRoles.value) : residentAdminApi.roles(),
      residentAdminApi.account(row.id),
    ])
    grantRoles.value = rolesData || []
    grantState.value = state
    const current = (state?.account?.roles || []).map((role: any) => Number(role.id))
    if (current.length) grantForm.value.roleIds = current.filter((id: number) => Number.isFinite(id))
    else if (!grantForm.value.roleIds.length) {
      const defaultRole = (grantRoles.value || []).find((role: any) => role.code === 'community_admin')
      if (defaultRole) grantForm.value.roleIds = [Number(defaultRole.id)]
    }
    grantForm.value.username = state?.account?.username || grantForm.value.username
  } catch (exc: any) {
    app.showToast(exc?.message || '后台身份加载失败')
    grantOpen.value = false
  } finally {
    grantLoading.value = false
  }
}

function closeGrant() {
  if (grantSubmitting.value) return
  grantOpen.value = false
  grantTarget.value = null
  grantState.value = { eligible: false, eligibleReason: '', account: null }
}

function setGrantRole(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  grantForm.value.roleIds = Number.isFinite(value) && value ? [value] : []
}

async function submitGrant() {
  if (!grantTarget.value || grantSubmitting.value) return
  if (!grantForm.value.roleIds.length) {
    app.showToast('请选择要授予的角色')
    return
  }
  grantSubmitting.value = true
  try {
    const data = await residentAdminApi.grant(grantTarget.value.id, {
      roleIds: grantForm.value.roleIds.map(Number),
      username: grantForm.value.username.trim() || undefined,
      reason: grantForm.value.reason.trim() || undefined,
    })
    grantOpen.value = false
    if (data?.initialPassword) {
      grantResult.value = { ...data, residentName: grantTarget.value.name }
    } else {
      app.showToast(data?.adjusted ? '后台角色已调整' : '后台权限已开通')
    }
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '授权失败')
  } finally {
    grantSubmitting.value = false
  }
}

async function revokeGrant(row: any) {
  const ok = await confirm({
    title: '解除后台授权',
    message: `确定解除“${row.name}”的后台权限吗？`,
    details: ['解除后该住户将无法登录管理端，移动端账号与住户档案不受影响。'],
    confirmText: '确认解除',
    danger: true,
  })
  if (!ok) return
  try {
    await residentAdminApi.revoke(row.id)
    app.showToast('后台权限已解除')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '解除失败')
  }
}

async function resetGrantPassword(row: any) {
  if (resetting.value) return
  resetting.value = row.id
  try {
    const data = await residentAdminApi.resetPassword(row.id)
    grantResult.value = { admin: data, initialPassword: data?.initialPassword, residentName: row.name }
  } catch (exc: any) {
    app.showToast(exc?.message || '重置失败')
  } finally {
    resetting.value = ''
  }
}

async function copyText(value: string, label: string) {
  try {
    await navigator.clipboard.writeText(value)
    app.showToast(`${label}已复制`)
  } catch {
    app.showToast('复制失败，请手动选择文本')
  }
}

onMounted(load)
watch(() => app.currentCommunityId, () => {
  // 与社区运维一致：切换社区后重置身份页签与列表搜索。
  activeTab.value = '全部人员'
  query.value = ''
  page.value = 1
  load()
})
</script>

<template>
  <CommunityFilterBar owner-label="人员档案归属小区" scope-note="人员列表仅展示所选小区" />

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
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索姓名、昵称、房屋或认证编号…" @keyup.enter="load" /></div>
      <div>
        <button><Filter :size="16" />认证状态<ChevronDown :size="14" /></button>
        <button><Settings2 :size="16" />列设置</button>
        <button v-if="auth.hasPermission('community:resident:create')" class="primary-button" @click="openCreate"><Plus :size="16" />新增人员</button>
      </div>
    </div>
    <div v-if="selectedCount" class="batch-bar">
      <span>已选择 {{ selectedCount }} 个人员</span>
      <button @click="clearSelection">取消选择</button>
      <button class="danger" @click="batchRemove"><Trash2 :size="14" />批量删除</button>
    </div>
    <div class="table-wrap resident-table-wrap">
      <table class="resident-table">
        <thead>
          <tr>
            <th v-if="canBatchRemove" class="select-cell">
              <input
                type="checkbox"
                aria-label="全选当前页人员"
                :checked="allSelected"
                :disabled="!rows.length"
                @change="toggleAll"
              />
            </th>
            <th class="avatar-cell">头像</th><th>姓名</th><th>昵称</th><th>身份类型</th><th>房屋 / 商铺</th><th>信用</th>
            <th>身份认证</th><th>业主认证</th><th>手机号</th><th>邮箱</th><th>个人描述</th><th>账号状态</th><th>后台身份</th><th>加入时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td v-if="canBatchRemove" class="select-cell">
              <input
                type="checkbox"
                :aria-label="`选择 ${row.name}`"
                :checked="selected.has(row.id)"
                @change="toggleRow(row)"
              />
            </td>
            <td class="avatar-cell">
              <span :class="['resident-avatar', avatarTone(row)]" :title="row.nickname || row.name">{{ avatarText(row) }}</span>
            </td>
            <td><span class="cell-ellipsis sm" :title="row.name">{{ row.name }}</span></td>
            <td><span class="cell-ellipsis sm" :title="row.nickname || '—'">{{ row.nickname || '—' }}</span></td>
            <td><span :class="['identity-tag', row.identity]">{{ row.identity }}</span></td>
            <td><div class="resident-house-cell" :title="row.building || '—'"><strong>{{ row.building || '—' }}</strong><span>{{ row.relationship || '' }}</span></div></td>
            <td><div class="resident-credit"><strong>{{ row.creditScore ?? '—' }}</strong><em v-if="row.creditLevel">{{ row.creditLevel }}</em></div></td>
            <td>
              <button
                class="cert-status-button"
                :class="{ clickable: !!row.realnameCert?.id }"
                :title="row.realnameCert?.id ? '查看身份认证照片' : '暂无身份认证材料'"
                @click="openCertViewer(row, 'realname')"
              >
                <StatusBadge :value="row.realnameStatusLabel || '未认证'" />
                <Camera v-if="row.realnameCert?.id" :size="12" />
              </button>
            </td>
            <td>
              <button
                class="cert-status-button"
                :class="{ clickable: !!row.ownerCert?.id }"
                :title="row.ownerCert?.id ? '查看业主认证照片' : '暂无业主认证材料'"
                @click="openCertViewer(row, 'owner')"
              >
                <StatusBadge :value="row.certification" />
                <Camera v-if="row.ownerCert?.id" :size="12" />
              </button>
            </td>
            <td>{{ row.phone || '—' }}</td>
            <td><span class="cell-ellipsis md" :title="row.email || '—'">{{ row.email || '—' }}</span></td>
            <td><span class="cell-ellipsis lg" :title="row.bio || '—'">{{ row.bio || '—' }}</span></td>
            <td><StatusBadge :value="row.status" /></td>
            <td>
              <span
                :class="['resident-admin-badge', {
                  active: row.adminAccount && row.adminAccount.status === 'ACTIVE',
                  disabled: row.adminAccount && row.adminAccount.status !== 'ACTIVE',
                }]"
                :title="row.adminAccount?.username ? `账号：${row.adminAccount.username}` : '尚未开通后台身份'"
              >
                {{ adminLabel(row) }}
              </span>
            </td>
            <td>{{ row.joinedAt }}</td>
            <td>
              <div class="row-actions">
                <button
                  v-if="canGrantAdmin"
                  class="row-icon-button"
                  aria-label="授予后台角色"
                  data-tip="授予后台角色"
                  @click="openGrant(row)"
                ><ShieldCheck :size="15" /></button>
                <button
                  v-if="canGrantAdmin && row.adminAccount?.status === 'ACTIVE'"
                  class="row-icon-button"
                  aria-label="重置初始密码"
                  data-tip="重置初始密码"
                  :disabled="resetting === row.id"
                  @click="resetGrantPassword(row)"
                ><KeyRound :size="15" /></button>
                <button
                  v-if="canRevokeAdmin && row.adminAccount?.status === 'ACTIVE'"
                  class="row-icon-button danger"
                  aria-label="解除后台授权"
                  data-tip="解除后台授权"
                  @click="revokeGrant(row)"
                ><ShieldOff :size="15" /></button>
                <button
                  v-if="auth.hasPermission('community:resident:update')"
                  class="row-icon-button"
                  aria-label="编辑人员档案"
                  data-tip="编辑人员档案"
                  @click="openEdit(row)"
                ><Pencil :size="15" /></button>
                <button
                  v-if="auth.hasPermission('community:resident:update')"
                  class="row-icon-button danger"
                  aria-label="删除人员档案"
                  data-tip="删除人员档案"
                  @click="remove(row)"
                ><Trash2 :size="15" /></button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无匹配人员" description="请调整身份分类或搜索关键词" />
    </div>
    <div class="resident-table-footer"><span>共 {{ total }} 条人员档案</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <div v-if="certViewerOpen" class="modal-backdrop" @click.self="closeCertViewer">
    <div class="modal-card cert-photo-modal">
      <header class="cert-photo-head">
        <div>
          <strong>{{ certViewerTitle }}</strong>
          <span v-if="certViewerData">{{ mapStatus(certViewerData.status) }} · 提交于 {{ fmtDateTime(certViewerData.submittedAt) }}</span>
        </div>
        <button class="cert-photo-close" aria-label="关闭认证照片" @click="closeCertViewer"><X :size="17" /></button>
      </header>
      <div class="modal-body">
        <div v-if="certViewerLoading" class="cert-photo-hint">正在加载认证材料…</div>
        <div v-else-if="certViewerError" class="cert-photo-hint error">{{ certViewerError }}</div>
        <template v-else-if="certViewerData">
          <div v-if="(certViewerData.materials || []).length" class="cert-photo-grid">
            <a
              v-for="material in certViewerData.materials"
              :key="material.objectKey"
              class="cert-photo-card"
              :href="material.signedUrl || undefined"
              target="_blank"
              rel="noopener"
            >
              <img
                v-if="material.signedUrl && !certPhotoErrors[material.objectKey]"
                :src="material.signedUrl"
                :alt="material.label"
                @error="onCertPhotoError(material.objectKey)"
              />
              <div v-else class="cert-photo-missing">{{ material.signedUrl ? '图片加载失败，请检查 MinIO 地址' : '签名 URL 生成失败' }}</div>
              <span>{{ material.label }}</span>
            </a>
          </div>
          <EmptyState v-else title="暂无认证照片" description="该认证单未上传材料" />
        </template>
      </div>
      <footer><button @click="closeCertViewer">关闭</button></footer>
    </div>
  </div>

  <NiDrawer :open="drawerOpen" :title="editing ? form.name : '新增社区人员'" :eyebrow="editing ? '维护档案' : '新建档案'" @close="drawerOpen = false">
    <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 18px">
      <Building2 :size="17" style="color: #6852c5" />
      <div style="flex: 1"><span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">所属社区</span><strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ community?.name }}</strong></div>
      <em style="color: #988da2; font-size: var(--font-size-caption)">{{ editing?.id || '新建' }}</em>
    </div>
    <h4 class="section-title">基本信息</h4>
    <div class="form-grid">
      <label class="full">
        <span>头像</span>
        <div class="drawer-avatar-row">
          <span :class="['resident-avatar', avatarTone(form)]">{{ avatarText(form) }}</span>
          <em>头像由移动端头像库维护，后台暂不支持更换</em>
        </div>
      </label>
      <label><span>姓名 *</span><input v-model="form.name" placeholder="请输入姓名" /></label>
      <label><span>昵称</span><input v-model="form.nickname" maxlength="24" placeholder="App 展示昵称" /></label>
      <label><span>性别</span><select v-model="form.gender"><option>男</option><option>女</option></select></label>
      <label><span>手机号</span><input v-model="form.phone" placeholder="请输入手机号" /></label>
      <label><span>邮箱</span><input v-model="form.email" maxlength="128" placeholder="选填" /></label>
      <label><span>身份类型</span><select v-model="form.identity"><option>业主</option><option>家属</option><option>租户</option><option>商务人员</option></select></label>
      <label><span>房屋 / 商铺</span><input v-model="form.building" placeholder="例如：8 栋 1 单元 902" /></label>
      <label><span>与房屋关系</span><input v-model="form.relationship" placeholder="如：房屋产权人" /></label>
      <label><span>加入时间</span><input v-model="form.joinedAt" type="date" /></label>
      <label class="full"><span>个人描述</span><textarea v-model="form.bio" maxlength="500" placeholder="选填，移动端个人简介" /></label>
    </div>
    <h4 class="section-title" style="margin-top: 24px">认证与材料</h4>
    <div class="cert-material-grid">
      <div class="cert-material-block">
        <div class="cert-material-head">
          <strong>身份认证</strong>
          <span>{{ form.realnameStatus ? mapStatus(form.realnameStatus) : '未认证' }}</span>
        </div>
        <label class="cert-status-field">
          <span>认证状态</span>
          <select v-model="form.realnameStatus"><option :value="null">保持原样</option><option value="UNVERIFIED">未认证</option><option value="PENDING">待审核</option><option value="VERIFIED">已认证</option><option value="SUPPLEMENT">待补充</option><option value="REJECTED">认证驳回</option><option value="FROZEN">已冻结</option><option value="REVOKED">已撤销</option></select>
        </label>
        <template v-if="editing">
          <div v-if="certMaterialsLoading.realname" class="cert-material-hint">正在加载认证材料…</div>
          <div v-else-if="certMaterials.realname.length" class="cert-material-thumbs">
            <div v-for="material in certMaterials.realname" :key="material.objectKey" class="cert-material-thumb">
              <a v-if="material.signedUrl" :href="material.signedUrl" target="_blank" rel="noopener">
                <img
                  v-if="!certMaterialErrors[material.objectKey]"
                  :src="material.signedUrl"
                  :alt="material.label"
                  @error="markCertMaterialError(material.objectKey)"
                />
                <div v-else class="cert-material-missing">图片加载失败</div>
              </a>
              <div v-else class="cert-material-missing">签名 URL 生成失败</div>
              <div class="cert-material-foot">
                <span>{{ material.label }}</span>
                <button type="button" @click="removeCertMaterial('realname', material.objectKey)">删除</button>
              </div>
            </div>
          </div>
          <div v-else class="cert-material-hint">暂无认证材料</div>
          <label class="cert-material-upload">
            <input type="file" accept="image/jpeg,image/png,image/webp" @change="onCertMaterialSelected('realname', $event)" />
            <span>{{ certUploading.realname ? '上传中…' : '上传 / 替换照片' }}</span>
          </label>
        </template>
        <p v-else class="cert-material-hint">保存档案后可上传身份认证材料</p>
      </div>

      <div class="cert-material-block">
        <div class="cert-material-head">
          <strong>业主认证</strong>
          <span>{{ form.certification || '未认证' }}</span>
        </div>
        <label class="cert-status-field">
          <span>认证状态</span>
          <select v-model="form.certification"><option>已认证</option><option>待审核</option><option>待补充</option><option>已驳回</option><option>未认证</option><option>已冻结</option><option>已撤销</option></select>
        </label>
        <template v-if="editing">
          <div v-if="certMaterialsLoading.owner" class="cert-material-hint">正在加载认证材料…</div>
          <div v-else-if="certMaterials.owner.length" class="cert-material-thumbs">
            <div v-for="material in certMaterials.owner" :key="material.objectKey" class="cert-material-thumb">
              <a v-if="material.signedUrl" :href="material.signedUrl" target="_blank" rel="noopener">
                <img
                  v-if="!certMaterialErrors[material.objectKey]"
                  :src="material.signedUrl"
                  :alt="material.label"
                  @error="markCertMaterialError(material.objectKey)"
                />
                <div v-else class="cert-material-missing">图片加载失败</div>
              </a>
              <div v-else class="cert-material-missing">签名 URL 生成失败</div>
              <div class="cert-material-foot">
                <span>{{ material.label }}</span>
                <button type="button" @click="removeCertMaterial('owner', material.objectKey)">删除</button>
              </div>
            </div>
          </div>
          <div v-else class="cert-material-hint">暂无认证材料</div>
          <label class="cert-material-upload">
            <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" @change="onCertMaterialSelected('owner', $event)" />
            <span>{{ certUploading.owner ? '上传中…' : '上传 / 替换照片' }}</span>
          </label>
        </template>
        <p v-else class="cert-material-hint">保存档案后可上传业主认证材料</p>
      </div>
    </div>
    <p class="form-hint">支持 JPG / PNG / WebP，业主认证另支持 PDF，单文件不超过 10MB；点击缩略图可查看原图。信用等级随信用分自动更新。</p>

    <h4 class="section-title" style="margin-top: 24px">等级与账号</h4>
    <div class="form-grid">
      <label><span>认证编号</span><input v-model="form.certificationNo" /></label>
      <label><span>信用分</span><input v-model.number="form.creditScore" type="number" min="0" max="1000" step="1" placeholder="0-1000，留空不修改" /></label>
      <label><span>用户级别</span><select v-model="form.level"><option>普通用户</option><option>活跃用户</option><option>社区达人</option><option>重点关怀</option></select></label>
      <label><span>账号状态</span><select v-model="form.status"><option>正常</option><option>已停用</option><option>已离开</option></select></label>
    </div>
    <template #footer><button @click="drawerOpen = false">取消</button><button class="primary-button" @click="save">保存档案</button></template>
  </NiDrawer>

  <NiDrawer :open="grantOpen" :title="grantState.account ? '调整后台角色' : '授予后台角色'" eyebrow="后台身份" @close="closeGrant">
    <div v-if="grantLoading" class="cert-photo-hint">正在加载后台身份…</div>
    <template v-else>
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 18px">
        <Building2 :size="17" style="color: #6852c5" />
        <div style="flex: 1">
          <span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">授权住户</span>
          <strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ grantTarget?.name }}</strong>
        </div>
        <em style="color: #988da2; font-size: var(--font-size-caption)">{{ grantTarget?.communityName }}</em>
      </div>

      <div v-if="grantState.account?.source === 'MANUAL'" class="grant-warning">
        该住户的移动端账号已绑定手工后台账号「{{ grantState.account.username }}」，请到「用户管理」调整。
      </div>
      <div v-else-if="!grantState.eligible && !grantState.account" class="grant-warning">
        {{ grantState.eligibleReason || '该住户暂不满足授权条件' }}
      </div>

      <div class="form-grid">
        <label class="full">
          <span>授予角色 *</span>
          <select
            :value="grantForm.roleIds[0] || ''"
            :disabled="grantState.account?.source === 'MANUAL' || (!grantState.eligible && !grantState.account)"
            @change="setGrantRole"
          >
            <option value="" disabled>请选择可授予住户的角色</option>
            <option v-for="role in grantRoles" :key="role.id" :value="role.id">{{ role.name }}（{{ role.code }}）</option>
          </select>
        </label>
        <label class="full">
          <span>登录账号{{ grantState.account ? '' : '（选填，默认自动生成）' }}</span>
          <input
            v-model="grantForm.username"
            maxlength="64"
            :disabled="Boolean(grantState.account) || grantState.account?.source === 'MANUAL'"
            placeholder="默认 u 开头，可自定义"
          />
        </label>
        <label class="full">
          <span>授权原因</span>
          <textarea v-model="grantForm.reason" maxlength="200" placeholder="例如：业主委员会推荐，负责本社区内容运营" />
        </label>
      </div>

      <p class="form-hint">
        授权后该住户同时拥有移动端账号与后台账号，仅能查看/操作本社区数据。
        初始密码由系统生成并仅展示一次，首次登录必须修改。
      </p>
      <p v-if="grantState.account" class="form-hint">
        当前账号：{{ grantState.account.username }} · 状态 {{ grantState.account.status }}
        <template v-if="grantState.account.mustChangePassword"> · 待首次改密</template>
      </p>
    </template>
    <template #footer>
      <button @click="closeGrant">取消</button>
      <button
        class="primary-button"
        :disabled="grantSubmitting || grantLoading || (!grantState.eligible && !grantState.account) || grantState.account?.source === 'MANUAL'"
        @click="submitGrant"
      >
        {{ grantSubmitting ? '正在保存…' : grantState.account ? '保存角色调整' : '确认授权' }}
      </button>
    </template>
  </NiDrawer>

  <div v-if="grantResult" class="modal-backdrop" @click.self="grantResult = null">
    <div class="modal-card grant-result-modal">
      <header class="cert-photo-head">
        <div>
          <strong>后台账号已就绪</strong>
          <span>{{ grantResult.residentName }} · 初始密码仅展示一次，关闭后只能重置</span>
        </div>
        <button class="cert-photo-close" aria-label="关闭" @click="grantResult = null"><X :size="17" /></button>
      </header>
      <div class="modal-body">
        <div class="grant-result-row">
          <span>登录账号</span>
          <strong>{{ grantResult.admin?.username }}</strong>
          <button class="link-button" @click="copyText(grantResult.admin?.username, '登录账号')"><Copy :size="13" />复制</button>
        </div>
        <div class="grant-result-row">
          <span>初始密码</span>
          <strong class="grant-result-password">{{ grantResult.initialPassword }}</strong>
          <button class="link-button" @click="copyText(grantResult.initialPassword, '初始密码')"><Copy :size="13" />复制</button>
        </div>
        <div class="grant-result-row">
          <span>登录地址</span>
          <strong>{{ loginUrl }}</strong>
          <button class="link-button" @click="copyText(loginUrl, '登录地址')"><Copy :size="13" />复制</button>
        </div>
        <p class="form-hint">首次登录会强制修改初始密码；请通过线下可信渠道告知住户，不要通过公开群聊发送。</p>
      </div>
      <footer><button class="primary-button" @click="grantResult = null">我已记录，关闭</button></footer>
    </div>
  </div>
</template>

<style scoped>
.resident-admin-badge { display: inline-block; max-width: 150px; padding: 2px 8px; border-radius: 7px; overflow: hidden; color: #9a95a1; background: #f5f4f7; font-size: var(--font-size-caption); white-space: nowrap; text-overflow: ellipsis; }
.resident-admin-badge.active { color: #5f4bb5; background: #f1edfc; }
.resident-admin-badge.disabled { color: #b06a6a; background: #fdf0f0; }
.grant-warning { margin-bottom: 14px; padding: 10px 12px; border-radius: 9px; color: #a3525b; background: #fff5f6; font-size: var(--font-size-body); line-height: 1.6; }
.grant-result-modal { width: min(520px, 100%); }
.grant-result-row { display: flex; align-items: center; gap: 12px; padding: 11px 13px; border-radius: 9px; background: #faf9fb; }
.grant-result-row + .grant-result-row { margin-top: 9px; }
.grant-result-row > span { width: 72px; color: #958b9f; font-size: var(--font-size-caption); }
.grant-result-row strong { flex: 1; min-width: 0; overflow-wrap: anywhere; color: #3d3945; font-size: var(--font-size-body); }
.grant-result-password { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .4px; }
.link-button { display: inline-flex; align-items: center; gap: 4px; border: 0; color: #6f59d4; background: transparent; font-size: var(--font-size-caption); cursor: pointer; }
</style>
