<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Ban,
  ChevronRight,
  CircleCheck,
  Copy,
  Eye,
  EyeOff,
  Home,
  KeyRound,
  Lock,
  LockOpen,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  UserPlus,
  X,
} from 'lucide-vue-next'
import { adminUsersApi, communityApi, rolesApi } from '@/api'
import { fmtDateTime } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useConfirm } from '@/composables/useConfirm'
import { groupProvinces, indexRegions, type RegionEntry, type RegionNode } from '@/utils/region'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import NiActionMenu from '@/components/NiActionMenu.vue'

type ActionMenuItem = {
  key: string
  label: string
  icon?: any
  danger?: boolean
  disabled?: boolean
}

type AccountForm = {
  username: string
  password: string
  realName: string
  phone: string
  email: string
  status: string
  roleIds: number[]
  communityIds: number[]
}

const app = useAppStore()
const auth = useAuthStore()
const { confirm } = useConfirm()

const rows = ref<any[]>([])
const roles = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const query = ref('')
const statusFilter = ref('')
const sourceFilter = ref('')
const loading = ref(false)
const selected = ref<Set<string>>(new Set())
const stats = ref({ total: 0, active: 0, disabled: 0, locked: 0 })

const drawerOpen = ref(false)
const editing = ref<any>(null)
const form = ref<AccountForm>(emptyForm())

const rolePickerOpen = ref(false)
const rolePickerSelected = ref<Set<number>>(new Set())

const resetOpen = ref(false)
const resetTarget = ref<any>(null)
const newPassword = ref('')
const showPassword = ref(false)

// 关联住户弹窗：行政区划四级联动 → 小区检索 → 小区内住户选择。
const linkOpen = ref(false)
const linkTarget = ref<any>(null)
const linkSaving = ref(false)
const linkRegionLoading = ref(false)
const linkRegionError = ref('')
const linkRegionRoots = ref<RegionNode[]>([])
const linkRegionIndex = ref<Record<string, RegionEntry>>({})
const linkProvinceId = ref('')
const linkCityId = ref('')
const linkDistrictId = ref('')
const linkStreetId = ref('')
const linkCommunityKeyword = ref('')
const linkCommunityResults = ref<any[]>([])
const linkCommunitySearching = ref(false)
const linkCommunity = ref<any | null>(null)
const linkResidentKeyword = ref('')
const linkResidents = ref<any[]>([])
const linkResidentLoading = ref(false)
const linkResidentId = ref('')
const linkOriginalResidentId = ref('')
let linkRegionPromise: Promise<void> | null = null
let linkCommunityTimer: number | undefined
let linkResidentTimer: number | undefined
let linkCommunityRequestId = 0
let linkResidentRequestId = 0

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const selectedCount = computed(() => selected.value.size)
const selectableRows = computed(() => rows.value.filter((row) => canSelect(row)))
const allSelected = computed(() =>
  selectableRows.value.length > 0 && selectableRows.value.every((row) => selected.value.has(row.id)))
const passwordValid = computed(() => newPassword.value.length > 0 && !passwordError(newPassword.value))
const selectedRoles = computed(() =>
  roles.value.filter((role) => form.value.roleIds.some((id) => Number(id) === Number(role.id))))
const allRolesSelected = computed(() =>
  roles.value.length > 0 && roles.value.every((role) => rolePickerSelected.value.has(Number(role.id))))

const linkProvinceGroups = computed(() => groupProvinces(linkRegionRoots.value))
const linkProvinceNode = computed(() =>
  (linkProvinceId.value ? linkRegionIndex.value[linkProvinceId.value]?.node : undefined) ?? null)
const linkCityNodes = computed<RegionNode[]>(() => linkProvinceNode.value?.children || [])
const linkDistrictNodes = computed<RegionNode[]>(() =>
  (linkCityId.value ? linkRegionIndex.value[linkCityId.value]?.node.children : undefined) || [])
const linkStreetNodes = computed<RegionNode[]>(() =>
  (linkDistrictId.value ? linkRegionIndex.value[linkDistrictId.value]?.node.children : undefined) || [])
const linkCommunityHint = computed(() => {
  if (linkCommunitySearching.value) return '正在检索小区…'
  if (linkCommunityKeyword.value.trim()) return '未找到匹配小区，请调整关键词或区划'
  if (linkCityId.value || linkDistrictId.value || linkStreetId.value) return '所选区划下暂无小区'
  return '请先选择省份与地市，或输入小区名称检索'
})
const linkCanSubmit = computed(() => Boolean(linkResidentId.value))

const dataScopeLabels: Record<string, string> = {
  ALL: '全部数据',
  COMMUNITY_SET: '指定社区集合',
  OWN_COMMUNITY: '本社区',
  SELF: '仅本人',
}

function emptyForm(): AccountForm {
  return {
    username: '', password: '', realName: '', phone: '', email: '',
    status: 'ACTIVE', roleIds: [], communityIds: [],
  }
}

function isSelf(row: any): boolean {
  return Boolean(auth.admin?.id) && String(auth.admin?.id) === String(row.id)
}

function avatarText(row: any): string {
  return (row.realName || row.username || '?').charAt(0)
}

function communityLabel(row: any): string {
  const names = (row.communities || []).map((item: any) => item.name).filter(Boolean)
  return names.length ? names.join('、') : '—'
}

async function load() {
  loading.value = true
  try {
    const data = await adminUsersApi.list({
      keyword: query.value.trim() || undefined,
      status: statusFilter.value || undefined,
      source: sourceFilter.value || undefined,
      page: page.value,
      pageSize,
    })
    rows.value = data.items || []
    total.value = Number(data.total || 0)
    stats.value = data.stats || { total: total.value, active: 0, disabled: 0, locked: 0 }
    selected.value = new Set()
  } catch (exc: any) {
    rows.value = []
    total.value = 0
    app.showToast(exc?.message || '账号加载失败')
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    roles.value = (await rolesApi.list()) || []
  } catch (exc: any) {
    app.showToast(exc?.message || '角色加载失败')
  }
}

function search() {
  page.value = 1
  load()
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  load()
}

function toggleRow(row: any) {
  if (!canSelect(row)) return
  const next = new Set(selected.value)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  selected.value = next
}

function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(selectableRows.value.map((row) => row.id))
}

function clearSelection() {
  selected.value = new Set()
}

function openCreate() {
  editing.value = null
  form.value = emptyForm()
  drawerOpen.value = true
}

function openEdit(row: any) {
  editing.value = row
  form.value = {
    username: row.username || '',
    password: '',
    realName: row.realName || '',
    phone: row.phone && !row.phone.includes('*') ? row.phone : '',
    email: row.email || '',
    status: row.status === 'DISABLED' ? 'DISABLED' : 'ACTIVE',
    roleIds: (row.roleIds || []).map((id: string) => Number(id)),
    communityIds: (row.communityIds || []).map((id: string) => Number(id)),
  }
  drawerOpen.value = true
}

function ensureLinkRegions(): Promise<void> {
  if (linkRegionRoots.value.length) return Promise.resolve()
  if (linkRegionPromise) return linkRegionPromise
  linkRegionLoading.value = true
  linkRegionError.value = ''
  linkRegionPromise = communityApi.regionTree()
    .then((roots) => {
      linkRegionRoots.value = roots as RegionNode[]
      linkRegionIndex.value = indexRegions(roots as RegionNode[])
    })
    .catch((exc: any) => {
      linkRegionError.value = exc?.message || '行政区划加载失败'
    })
    .finally(() => {
      linkRegionLoading.value = false
      linkRegionPromise = null
    })
  return linkRegionPromise
}

function resetLinkSelections() {
  linkProvinceId.value = ''
  linkCityId.value = ''
  linkDistrictId.value = ''
  linkStreetId.value = ''
  linkCommunityKeyword.value = ''
  linkCommunityResults.value = []
  linkCommunitySearching.value = false
  linkCommunity.value = null
  linkResidentKeyword.value = ''
  linkResidents.value = []
  linkResidentLoading.value = false
  linkResidentId.value = ''
  linkCommunityRequestId += 1
  linkResidentRequestId += 1
}

/** 根据社区档案的区县 / 街道反查并同步四级联动选中项。 */
function syncLinkCascadeFromCommunity(community: any) {
  const district = community?.regionId ? linkRegionIndex.value[String(community.regionId)] : undefined
  if (!district) return
  linkProvinceId.value = district.ancestors[0] ? String(district.ancestors[0].id) : ''
  linkCityId.value = district.ancestors[1] ? String(district.ancestors[1].id) : ''
  linkDistrictId.value = String(district.node.id)
  const street = community?.streetId ? linkRegionIndex.value[String(community.streetId)] : undefined
  linkStreetId.value = street && street.parentId === linkDistrictId.value ? String(street.node.id) : ''
}

async function openLinkResident(row: any) {
  resetLinkSelections()
  linkTarget.value = row
  linkOriginalResidentId.value = row.residentId ? String(row.residentId) : ''
  linkResidentId.value = linkOriginalResidentId.value
  linkOpen.value = true
  await ensureLinkRegions()
  if (!linkOpen.value || linkTarget.value?.id !== row.id) return
  if (!row.residentId || !row.communityId) return
  const communityId = Number(row.communityId)
  let community: any = {
    id: String(communityId),
    name: row.communityName || '当前关联小区',
    code: '',
    address: '',
  }
  try {
    community = await communityApi.detail(communityId)
  } catch {
    // 详情不可用时仍可按小区 ID 加载住户列表
  }
  if (!linkOpen.value || linkTarget.value?.id !== row.id) return
  linkCommunity.value = community
  linkCommunityKeyword.value = community.name || ''
  syncLinkCascadeFromCommunity(community)
  await loadLinkResidents()
}

function closeLinkDialog() {
  linkOpen.value = false
  linkTarget.value = null
  if (linkCommunityTimer) window.clearTimeout(linkCommunityTimer)
  if (linkResidentTimer) window.clearTimeout(linkResidentTimer)
}

function onLinkProvinceChange() {
  linkCityId.value = ''
  linkDistrictId.value = ''
  linkStreetId.value = ''
  clearLinkCommunity()
  runLinkCommunitySearch()
}

function onLinkCityChange() {
  linkDistrictId.value = ''
  linkStreetId.value = ''
  clearLinkCommunity()
  runLinkCommunitySearch()
}

function onLinkDistrictChange() {
  linkStreetId.value = ''
  clearLinkCommunity()
  runLinkCommunitySearch()
}

function onLinkStreetChange() {
  clearLinkCommunity()
  runLinkCommunitySearch()
}

function onLinkCommunityInput() {
  if (linkCommunityTimer) window.clearTimeout(linkCommunityTimer)
  linkCommunityTimer = window.setTimeout(() => runLinkCommunitySearch(), 240)
}

async function runLinkCommunitySearch() {
  const requestId = ++linkCommunityRequestId
  const keyword = linkCommunityKeyword.value.trim()
  const hasScope = Boolean(linkStreetId.value || linkDistrictId.value || linkCityId.value)
  if (!keyword && !hasScope) {
    linkCommunitySearching.value = false
    linkCommunityResults.value = []
    return
  }
  linkCommunitySearching.value = true
  try {
    const params: Record<string, any> = { page: 1, pageSize: 20 }
    if (keyword) params.keyword = keyword
    // 按最末级已选区划收窄检索范围；社区档案的 region_id 指向区县。
    if (linkStreetId.value) params.streetId = linkStreetId.value
    else if (linkDistrictId.value) params.regionId = linkDistrictId.value
    else if (linkCityId.value) params.cityId = linkCityId.value
    const data = await communityApi.list(params)
    if (requestId !== linkCommunityRequestId) return
    linkCommunityResults.value = (data.items || []).filter(
      (row: any) => !['PENDING', 'REJECTED'].includes(String(row.statusCode || row.status || '')),
    )
  } catch (exc: any) {
    if (requestId !== linkCommunityRequestId) return
    linkCommunityResults.value = []
    app.showToast(exc?.message || '小区检索失败')
  } finally {
    if (requestId === linkCommunityRequestId) linkCommunitySearching.value = false
  }
}

function clearLinkCommunity() {
  linkCommunity.value = null
  linkResidentKeyword.value = ''
  linkResidents.value = []
  linkResidentLoading.value = false
  linkResidentId.value = ''
  linkResidentRequestId += 1
}

async function selectLinkCommunity(row: any) {
  linkCommunity.value = row
  linkCommunityKeyword.value = row.name || ''
  linkCommunityResults.value = []
  linkResidentKeyword.value = ''
  linkResidents.value = []
  linkResidentId.value = ''
  await loadLinkResidents()
}

function reselectLinkCommunity() {
  clearLinkCommunity()
  if (linkCommunityKeyword.value.trim() || linkCityId.value || linkDistrictId.value || linkStreetId.value) {
    runLinkCommunitySearch()
  }
}

async function loadLinkResidents() {
  const community = linkCommunity.value
  if (!community) {
    linkResidents.value = []
    return
  }
  const requestId = ++linkResidentRequestId
  linkResidentLoading.value = true
  try {
    const rows = await adminUsersApi.residentOptions({
      communityId: Number(community.id),
      keyword: linkResidentKeyword.value.trim() || undefined,
      limit: 50,
    })
    if (requestId !== linkResidentRequestId) return
    const list = rows || []
    const target = linkTarget.value
    const isOriginalCommunity = String(community.id) === String(target?.communityId || '')
    if (isOriginalCommunity && linkOriginalResidentId.value
      && !list.some((item: any) => String(item.id) === linkOriginalResidentId.value)) {
      // 当前关联住户可能不在前 50 条中，补一条占位记录保证可见且可保留选择。
      list.unshift({
        id: linkOriginalResidentId.value,
        name: target?.residentName || '当前关联住户',
        phone: '',
        building: '',
        communityId: String(community.id),
        communityName: community.name || target?.communityName || '',
        identityType: '',
        adminUserId: String(target?.id || ''),
      })
    }
    linkResidents.value = list
  } catch (exc: any) {
    if (requestId === linkResidentRequestId) {
      linkResidents.value = []
      app.showToast(exc?.message || '住户加载失败')
    }
  } finally {
    if (requestId === linkResidentRequestId) linkResidentLoading.value = false
  }
}

function onLinkResidentInput() {
  if (linkResidentTimer) window.clearTimeout(linkResidentTimer)
  linkResidentTimer = window.setTimeout(() => loadLinkResidents(), 240)
}

function linkResidentSelectable(item: any): boolean {
  return !item.adminUserId || String(item.adminUserId) === String(linkTarget.value?.id)
}

function selectLinkResident(item: any) {
  if (!linkResidentSelectable(item)) return
  linkResidentId.value = String(item.id)
}

async function submitLinkResident() {
  const target = linkTarget.value
  if (!target) return
  if (!linkResidentId.value) {
    app.showToast('请选择要关联的住户')
    return
  }
  linkSaving.value = true
  try {
    await adminUsersApi.linkResident(target.id, Number(linkResidentId.value))
    app.showToast('住户关联已更新')
    closeLinkDialog()
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '关联住户失败')
  } finally {
    linkSaving.value = false
  }
}

async function unbindLinkedResident() {
  const target = linkTarget.value
  if (!target?.residentId) return
  const ok = await confirm({
    title: '解除住户关联',
    message: `确定解除“${target.realName || target.username}”与住户“${target.residentName || '当前住户'}”的关联吗？`,
    details: ['解除后该账号将不能再以住户身份使用后台，移动端账号本身保留。'],
    confirmText: '解除关联',
    danger: true,
  })
  if (!ok) return
  linkSaving.value = true
  try {
    await adminUsersApi.linkResident(target.id, null)
    app.showToast('已解除住户关联')
    closeLinkDialog()
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '解除关联失败')
  } finally {
    linkSaving.value = false
  }
}

function openRolePicker() {
  rolePickerSelected.value = new Set(form.value.roleIds.map(Number))
  rolePickerOpen.value = true
}

function closeRolePicker() {
  rolePickerOpen.value = false
}

function toggleRolePick(role: any) {
  const id = Number(role.id)
  const next = new Set(rolePickerSelected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  rolePickerSelected.value = next
}

function toggleAllRolePick() {
  rolePickerSelected.value = allRolesSelected.value
    ? new Set()
    : new Set(roles.value.map((role) => Number(role.id)))
}

function confirmRolePicker() {
  form.value.roleIds = roles.value
    .filter((role) => rolePickerSelected.value.has(Number(role.id)))
    .map((role) => Number(role.id))
  rolePickerOpen.value = false
}

function removeRole(id: number) {
  form.value.roleIds = form.value.roleIds.filter((roleId) => Number(roleId) !== Number(id))
}

function scopeLabel(scope: string): string {
  return dataScopeLabels[scope] || scope || '—'
}

function isResidentAccount(row: any): boolean {
  return row?.source === 'RESIDENT'
}

function sourceLabel(row: any): string {
  return row.source === 'RESIDENT' ? '住户授权' : '后台创建'
}

function mobileLabel(row: any): string {
  if (!row.mobileBound) return '未绑定'
  return row.mobileStatus === 'ACTIVE' ? '已绑定' : '账号异常'
}

function passwordError(value: string, minLength = 12): string {
  if (value.length < minLength) return `密码最短 ${minLength} 位`
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((rule) => rule.test(value)).length
  if (kinds < 3) return '需包含大小写字母、数字、符号中的至少三类'
  return ''
}

async function save() {
  if (!editing.value && form.value.username.trim().length < 3) {
    app.showToast('用户名至少 3 位')
    return
  }
  if (!form.value.realName.trim()) {
    app.showToast('请填写姓名')
    return
  }
  if (!editing.value) {
    // 新建账号的初始密码最低 6 位；重置密码与修改密码仍保持 12 位策略。
    const error = passwordError(form.value.password, 6)
    if (error) {
      app.showToast(error)
      return
    }
  }
  const payload: Record<string, any> = {
    username: form.value.username.trim(),
    realName: form.value.realName.trim(),
    phone: form.value.phone.trim(),
    email: form.value.email.trim(),
    status: form.value.status,
  }
  // 住户授权账号的绑定与角色由「社区业主」页统一管理，编辑时只提交基础资料。
  if (!isResidentAccount(editing.value)) {
    payload.roleIds = form.value.roleIds.map(Number)
    // 表单不再提供“可访问社区”编辑，沿用账号已有社区集合，避免编辑时被清空。
    payload.communityIds = form.value.communityIds.map(Number)
    // 住户关联由操作列的“关联住户”单独维护，编辑基础资料时不提交 residentId。
  }
  if (!editing.value) payload.password = form.value.password
  try {
    if (editing.value) await adminUsersApi.update(editing.value.id, payload)
    else await adminUsersApi.create(payload)
    drawerOpen.value = false
    app.showToast(editing.value ? '账号已更新' : '账号已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function toggleStatus(row: any) {
  const disabling = row.status === 'ACTIVE'
  if (disabling) {
    const ok = await confirm({
      title: '停用账号',
      message: `确定停用“${row.realName || row.username}”吗？停用后该账号将无法登录后台。`,
      confirmText: '确认停用',
      danger: true,
    })
    if (!ok) return
  }
  try {
    await adminUsersApi.toggleStatus(row.id, disabling ? 'DISABLED' : 'ACTIVE')
    app.showToast(disabling ? '账号已停用' : '账号已启用')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

async function unlock(row: any) {
  try {
    await adminUsersApi.unlock(row.id)
    app.showToast('账号已解锁')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '解锁失败')
  }
}

async function remove(row: any) {
  const ok = await confirm({
    title: '删除账号',
    message: `确定删除“${row.realName || row.username}”吗？删除后不可恢复。`,
    confirmText: '确认删除',
    danger: true,
  })
  if (!ok) return
  try {
    await adminUsersApi.remove(row.id)
    app.showToast('账号已删除')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

async function batchRemove() {
  const ids = Array.from(selected.value)
  if (!ids.length) return
  const ok = await confirm({
    title: '批量删除账号',
    message: `确定删除已选择的 ${ids.length} 个账号吗？删除后不可恢复。`,
    confirmText: '确认删除',
    danger: true,
  })
  if (!ok) return
  try {
    await adminUsersApi.batchRemove(ids)
    app.showToast(`已删除 ${ids.length} 个账号`)
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '批量删除失败')
  }
}

function openReset(row: any) {
  resetTarget.value = row
  newPassword.value = ''
  showPassword.value = false
  resetOpen.value = true
}

function closeReset() {
  resetOpen.value = false
  resetTarget.value = null
  newPassword.value = ''
  showPassword.value = false
}

function randomInt(max: number): number {
  const buffer = new Uint32Array(1)
  crypto.getRandomValues(buffer)
  return buffer[0] % max
}

function generatePassword() {
  const sets = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '@#$%&*!?']
  const chars = sets.map((set) => set[randomInt(set.length)])
  const pool = sets.join('')
  while (chars.length < 16) chars.push(pool[randomInt(pool.length)])
  for (let index = chars.length - 1; index > 0; index -= 1) {
    const target = randomInt(index + 1)
    const current = chars[index]
    chars[index] = chars[target]
    chars[target] = current
  }
  newPassword.value = chars.join('')
  showPassword.value = true
}

async function copyPassword() {
  try {
    await navigator.clipboard.writeText(newPassword.value)
    app.showToast('新密码已复制')
  } catch {
    app.showToast('复制失败，请手动选择密码')
  }
}

async function submitReset() {
  if (!resetTarget.value) return
  const error = passwordError(newPassword.value)
  if (error) {
    app.showToast(error)
    return
  }
  try {
    await adminUsersApi.resetPassword(resetTarget.value.id, newPassword.value)
    app.showToast('密码已重置')
    closeReset()
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '密码重置失败')
  }
}

function rowActions(row: any): ActionMenuItem[] {
  const active = row.status === 'ACTIVE'
  return [
    { key: 'edit', label: '编辑', icon: Pencil, disabled: row.isSuperAdmin },
    {
      key: 'link-resident',
      label: '关联住户',
      icon: UserPlus,
      disabled: row.isSuperAdmin || isResidentAccount(row),
    },
    { key: 'reset', label: '重置密码', icon: KeyRound },
    {
      key: 'toggle',
      label: active ? '禁用' : '启用',
      icon: active ? Ban : CircleCheck,
      danger: active,
      disabled: row.isSuperAdmin || (active && isSelf(row)),
    },
    { key: 'unlock', label: '解锁', icon: LockOpen, disabled: !row.locked },
    {
      key: 'delete',
      label: '删除',
      icon: Trash2,
      danger: true,
      disabled: row.isSuperAdmin || isSelf(row) || isResidentAccount(row),
    },
  ]
}

function canSelect(row: any): boolean {
  return !row.isSuperAdmin && !isSelf(row) && !isResidentAccount(row)
}

function onAction(key: string, row: any) {
  if (key === 'edit') openEdit(row)
  else if (key === 'link-resident') openLinkResident(row)
  else if (key === 'reset') openReset(row)
  else if (key === 'toggle') toggleStatus(row)
  else if (key === 'unlock') unlock(row)
  else if (key === 'delete') remove(row)
}

onMounted(async () => {
  await Promise.all([load(), loadOptions()])
})
</script>

<template>
  <section class="summary-row">
    <div><span>全部账号</span><strong>{{ stats.total }}</strong><em>后台管理员</em></div>
    <div><span>启用中</span><strong>{{ stats.active }}</strong><em class="up">可正常登录</em></div>
    <div><span>已停用</span><strong>{{ stats.disabled }}</strong><em class="warn">禁止登录</em></div>
    <div><span>登录锁定</span><strong>{{ stats.locked }}</strong><em class="warn">连续失败锁定</em></div>
  </section>

  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search">
        <Search :size="17" />
        <input v-model="query" placeholder="搜索用户名或姓名…" @keyup.enter="search" />
      </div>
      <div class="toolbar-actions">
        <select v-model="statusFilter" class="status-filter" aria-label="账号状态筛选" @change="search">
          <option value="">全部状态</option>
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">停用</option>
        </select>
        <select v-model="sourceFilter" class="status-filter" aria-label="账号来源筛选" @change="search">
          <option value="">全部来源</option>
          <option value="MANUAL">后台创建</option>
          <option value="RESIDENT">住户授权</option>
        </select>
        <button class="primary-button" @click="openCreate"><Plus :size="16" />新增用户</button>
      </div>
    </div>

    <div v-if="selectedCount" class="batch-bar">
      <span>已选择 {{ selectedCount }} 个账号</span>
      <button @click="clearSelection">取消选择</button>
      <button class="danger" @click="batchRemove"><Trash2 :size="14" />批量删除</button>
    </div>

    <div class="table-wrap">
      <table class="user-table">
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                aria-label="全选当前页"
                :checked="allSelected"
                :disabled="!selectableRows.length"
                @change="toggleAll"
              />
            </th>
            <th>用户</th>
            <th>用户名</th>
            <th>来源</th>
            <th>关联住户 / 小区</th>
            <th>移动端账号</th>
            <th>手机号</th>
            <th>角色</th>
            <th>可访问社区</th>
            <th>状态</th>
            <th>最近登录</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <input
                type="checkbox"
                :aria-label="`选择 ${row.realName || row.username}`"
                :checked="selected.has(row.id)"
                :disabled="!canSelect(row)"
                :title="canSelect(row) ? '' : '超级管理员或当前登录账号不可删除'"
                @change="toggleRow(row)"
              />
            </td>
            <td>
              <div class="primary-cell">
                <span class="row-icon">{{ avatarText(row) }}</span>
                <div class="user-cell">
                  <strong>{{ row.realName || row.username }}</strong>
                  <em v-if="row.isSuperAdmin">超级管理员</em>
                  <em v-else-if="isSelf(row)">当前账号</em>
                </div>
              </div>
            </td>
            <td><span class="medium-cell">{{ row.username }}</span></td>
            <td>
              <span :class="['source-tag', { resident: row.source === 'RESIDENT' }]">{{ sourceLabel(row) }}</span>
            </td>
            <td>
              <div v-if="row.residentId" class="resident-link-cell">
                <strong>{{ row.residentName || '住户' }}</strong>
                <span>{{ row.communityName || '—' }}</span>
              </div>
              <span v-else class="muted-text">未关联</span>
            </td>
            <td>
              <span :class="['mobile-tag', { bound: row.mobileBound && row.mobileStatus === 'ACTIVE', warn: row.mobileBound && row.mobileStatus !== 'ACTIVE' }]">
                {{ mobileLabel(row) }}
              </span>
            </td>
            <td>{{ row.phone || '—' }}</td>
            <td>
              <div class="tag-row">
                <span v-for="role in row.roles" :key="role.id || role.code" class="mini-tag">{{ role.name }}</span>
                <span v-if="!row.roles?.length" class="muted-text">未分配</span>
              </div>
            </td>
            <td>
              <span class="cell-ellipsis md" :title="communityLabel(row)">{{ communityLabel(row) }}</span>
            </td>
            <td>
              <div class="status-cell">
                <StatusBadge :value="row.status === 'ACTIVE' ? '正常' : '已停用'" />
                <span v-if="row.locked" class="lock-tag" :title="`锁定至 ${fmtDateTime(row.lockedUntil)}`">
                  <Lock :size="12" />锁定
                </span>
              </div>
            </td>
            <td>{{ row.lastLoginAt ? fmtDateTime(row.lastLoginAt) : '从未登录' }}</td>
            <td>
              <div class="row-actions">
                <NiActionMenu :items="rowActions(row)" @select="(key) => onAction(key, row)" />
              </div>
            </td>
          </tr>
          <tr v-if="loading">
            <td colspan="12" class="table-loading">正在加载账号…</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length && !loading" title="暂无账号" description="点击右上角“新增用户”创建后台账号" />
    </div>

    <div class="pagination">
      <span>共 {{ total }} 个账号</span>
      <div>
        <button :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button class="current">{{ page }}</button>
        <button :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>
  </section>

  <NiDrawer
    :open="drawerOpen"
    :title="editing ? `编辑账号 · ${editing.realName || editing.username}` : '新增用户'"
    :eyebrow="editing ? '维护管理员账号' : '新建管理员账号'"
    @close="drawerOpen = false"
  >
    <div class="form-grid">
      <label>
        <span>用户名 *</span>
        <input v-model="form.username" :disabled="!!editing" maxlength="64" placeholder="登录用户名，创建后不可修改" />
      </label>
      <label>
        <span>姓名 *</span>
        <input v-model="form.realName" maxlength="64" placeholder="真实姓名" />
      </label>
      <label v-if="!editing">
        <span>初始密码 *</span>
        <input v-model="form.password" type="password" placeholder="至少 6 位，三类字符" />
      </label>
      <label>
        <span>手机号</span>
        <input v-model="form.phone" maxlength="11" :placeholder="editing ? '留空不修改' : '选填'" />
      </label>
      <label>
        <span>邮箱</span>
        <input v-model="form.email" maxlength="128" placeholder="选填" />
      </label>
      <label>
        <span>账号状态</span>
        <select v-model="form.status">
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">停用</option>
        </select>
      </label>
    </div>
    <p v-if="!editing" class="form-hint">初始密码需至少 6 位，且包含大小写字母、数字、符号中的至少三类；创建后可通过“重置密码”修改。</p>

    <h4 class="section-title" style="margin-top: 22px">角色</h4>
    <div v-if="isResidentAccount(editing)" class="muted-text">住户授权账号的角色由「社区业主」页统一配置。</div>
    <template v-else>
      <div class="role-assign">
        <div class="role-chip-list">
          <span v-for="role in selectedRoles" :key="role.id" class="role-chip">
            {{ role.name }}
            <button type="button" :aria-label="`移除角色 ${role.name}`" @click="removeRole(Number(role.id))">
              <X :size="12" />
            </button>
          </span>
          <span v-if="!selectedRoles.length" class="muted-text">尚未分配角色</span>
        </div>
        <button type="button" class="add-role-button" @click="openRolePicker"><Plus :size="14" />添加角色</button>
      </div>
      <p class="form-hint">多角色权限取并集；未分配角色时账号仅能登录，无业务权限。</p>
    </template>

    <template #footer>
      <button @click="drawerOpen = false">取消</button>
      <button class="primary-button" @click="save">保存</button>
    </template>
  </NiDrawer>

  <div v-if="rolePickerOpen" class="modal-backdrop role-picker-backdrop" @click.self="closeRolePicker">
    <div class="modal-card role-picker-card" role="dialog" aria-modal="true" aria-label="选择角色">
      <header>选择角色</header>
      <div class="modal-body">
        <div class="role-picker-table-wrap">
          <table class="role-picker-table">
            <thead>
              <tr>
                <th class="check-cell">
                  <input
                    type="checkbox"
                    aria-label="全选角色"
                    :checked="allRolesSelected"
                    :disabled="!roles.length"
                    @change="toggleAllRolePick"
                  />
                </th>
                <th>角色名称</th>
                <th>角色编码</th>
                <th>角色描述</th>
                <th>数据范围</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="role in roles"
                :key="role.id"
                :class="{ selected: rolePickerSelected.has(Number(role.id)) }"
                @click="toggleRolePick(role)"
              >
                <td class="check-cell" @click.stop>
                  <input
                    type="checkbox"
                    :aria-label="`选择角色 ${role.name}`"
                    :checked="rolePickerSelected.has(Number(role.id))"
                    @change="toggleRolePick(role)"
                  />
                </td>
                <td>
                  <div class="role-name-cell">
                    <strong>{{ role.name }}</strong>
                    <em v-if="role.builtin">内置</em>
                  </div>
                </td>
                <td><code>{{ role.code }}</code></td>
                <td><span class="cell-ellipsis lg" :title="role.description || ''">{{ role.description || '—' }}</span></td>
                <td>{{ scopeLabel(role.dataScope) }}</td>
              </tr>
              <tr v-if="!roles.length">
                <td colspan="5" class="role-picker-empty">暂无可分配角色</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="form-hint">可多选角色，点击“确定”后添加到当前账号；多角色权限取并集。</p>
      </div>
      <footer>
        <button @click="closeRolePicker">取消</button>
        <button class="primary-button" @click="confirmRolePicker">确定</button>
      </footer>
    </div>
  </div>

  <div v-if="linkOpen" class="modal-backdrop" @click.self="closeLinkDialog">
    <div class="modal-card link-resident-card" role="dialog" aria-modal="true" aria-label="关联住户">
      <header>关联住户 · {{ linkTarget?.realName || linkTarget?.username }}</header>
      <div class="modal-body link-resident-body">
        <div v-if="linkTarget?.residentId" class="link-current">
          <span>当前关联</span>
          <strong>{{ linkTarget.residentName || '住户' }} · {{ linkTarget.communityName || '—' }}</strong>
          <em>可在下方重新选择住户，或点击“解除关联”。</em>
        </div>

        <section class="link-section">
          <div class="link-section-head">
            <span><i>1</i>选择行政区划</span>
            <em>街道选填</em>
          </div>
          <div class="link-cascade">
            <label>
              <select v-model="linkProvinceId" aria-label="省份/直辖市" :disabled="linkRegionLoading || !linkProvinceGroups.length" @change="onLinkProvinceChange">
                <option value="">{{ linkRegionLoading ? '加载区划…' : '省份/直辖市' }}</option>
                <optgroup v-for="group in linkProvinceGroups" :key="group.label" :label="group.label">
                  <option v-for="province in group.provinces" :key="province.id" :value="String(province.id)">{{ province.name }}</option>
                </optgroup>
              </select>
            </label>
            <ChevronRight :size="13" class="link-cascade-arrow" />
            <label>
              <select v-model="linkCityId" aria-label="地市" :disabled="!linkCityNodes.length" @change="onLinkCityChange">
                <option value="">{{ linkCityNodes.length ? '地市' : '先选省份' }}</option>
                <option v-for="city in linkCityNodes" :key="city.id" :value="String(city.id)">{{ city.name }}</option>
              </select>
            </label>
            <ChevronRight :size="13" class="link-cascade-arrow" />
            <label>
              <select v-model="linkDistrictId" aria-label="区/县" :disabled="!linkDistrictNodes.length" @change="onLinkDistrictChange">
                <option value="">{{ linkDistrictNodes.length ? '区/县' : '先选地市' }}</option>
                <option v-for="district in linkDistrictNodes" :key="district.id" :value="String(district.id)">{{ district.name }}</option>
              </select>
            </label>
            <ChevronRight :size="13" class="link-cascade-arrow" />
            <label>
              <select v-model="linkStreetId" aria-label="街道" :disabled="!linkStreetNodes.length" @change="onLinkStreetChange">
                <option value="">{{ linkStreetNodes.length ? '街道（可选）' : '先选区县' }}</option>
                <option v-for="street in linkStreetNodes" :key="street.id" :value="String(street.id)">{{ street.name }}</option>
              </select>
            </label>
          </div>
          <p v-if="linkRegionError" class="form-hint">{{ linkRegionError }}</p>
        </section>

        <section class="link-section">
          <div class="link-section-head">
            <span><i>2</i>选择小区</span>
            <em v-if="linkCommunity">已选择</em>
          </div>
          <div v-if="linkCommunity" class="link-community-selected">
            <span class="link-community-icon"><Home :size="15" /></span>
            <div class="link-community-main">
              <strong>{{ linkCommunity.name }}</strong>
              <em>{{ [linkCommunity.code, linkCommunity.address].filter(Boolean).join(' · ') || '—' }}</em>
            </div>
            <button type="button" @click="reselectLinkCommunity">重新选择</button>
          </div>
          <template v-else>
            <div class="link-community-search">
              <Search :size="15" />
              <input
                v-model="linkCommunityKeyword"
                aria-label="小区检索"
                placeholder="输入小区名称、编码或地址检索…"
                @input="onLinkCommunityInput"
                @keyup.enter="runLinkCommunitySearch"
              />
            </div>
            <div class="link-community-results">
              <button
                v-for="row in linkCommunityResults"
                :key="row.id"
                type="button"
                class="link-community-option"
                @click="selectLinkCommunity(row)"
              >
                <span class="link-community-icon"><Home :size="14" /></span>
                <span class="link-community-main">
                  <strong>{{ row.name }}</strong>
                  <em>{{ row.code }}<template v-if="row.address"> · {{ row.address }}</template></em>
                </span>
              </button>
              <div v-if="!linkCommunityResults.length" class="link-empty">{{ linkCommunityHint }}</div>
            </div>
          </template>
        </section>

        <section class="link-section">
          <div class="link-section-head">
            <span><i>3</i>选择住户</span>
            <em v-if="linkCommunity">{{ linkCommunity.name }}</em>
          </div>
          <div v-if="!linkCommunity" class="link-empty link-empty-tall">请先选择小区</div>
          <template v-else>
            <div class="link-community-search">
              <Search :size="15" />
              <input
                v-model="linkResidentKeyword"
                aria-label="住户检索"
                placeholder="搜索住户姓名、楼栋或认证编号…"
                @input="onLinkResidentInput"
              />
            </div>
            <div class="link-resident-list">
              <button
                v-for="item in linkResidents"
                :key="item.id"
                type="button"
                :class="['link-resident-option', {
                  selected: String(item.id) === linkResidentId,
                  disabled: !linkResidentSelectable(item),
                }]"
                :disabled="!linkResidentSelectable(item)"
                @click="selectLinkResident(item)"
              >
                <span :class="['link-resident-radio', { checked: String(item.id) === linkResidentId }]" />
                <span class="link-resident-main">
                  <strong>
                    {{ item.name }}
                    <em v-if="item.identityType">{{ item.identityType }}</em>
                    <em v-if="String(item.id) === linkOriginalResidentId" class="current">当前关联</em>
                  </strong>
                  <span>{{ [item.building, item.phone || '无手机号'].filter(Boolean).join(' · ') }}</span>
                </span>
                <em v-if="!linkResidentSelectable(item)" class="link-resident-warn">已绑其他账号</em>
              </button>
              <div v-if="linkResidentLoading" class="link-empty">正在加载住户…</div>
              <div v-else-if="!linkResidents.length" class="link-empty">该小区下暂无可用住户</div>
            </div>
          </template>
        </section>
      </div>
      <footer>
        <button
          v-if="linkTarget?.residentId"
          type="button"
          class="link-unbind-button"
          :disabled="linkSaving"
          @click="unbindLinkedResident"
        >解除关联</button>
        <button type="button" :disabled="linkSaving" @click="closeLinkDialog">取消</button>
        <button class="primary-button" type="button" :disabled="!linkCanSubmit || linkSaving" @click="submitLinkResident">
          {{ linkSaving ? '保存中…' : '保存关联' }}
        </button>
      </footer>
    </div>
  </div>

  <div v-if="resetOpen" class="modal-backdrop" @click.self="closeReset">
    <div class="modal-card reset-card">
      <header>重置密码 · {{ resetTarget?.realName || resetTarget?.username }}</header>
      <div class="modal-body">
        <label class="reset-field">
          <span>新密码</span>
          <div class="password-field">
            <input
              v-model="newPassword"
              :type="showPassword ? 'text' : 'password'"
              placeholder="至少 12 位，三类字符"
              autocomplete="new-password"
            />
            <button type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
              <EyeOff v-if="showPassword" :size="16" />
              <Eye v-else :size="16" />
            </button>
          </div>
        </label>
        <p class="form-hint">重置后该账号的登录失败锁定会一并清除，需使用新密码重新登录。</p>
        <div class="password-actions">
          <button type="button" @click="generatePassword"><RefreshCw :size="14" />生成随机密码</button>
          <button type="button" :disabled="!newPassword" @click="copyPassword"><Copy :size="14" />复制</button>
        </div>
      </div>
      <footer>
        <button @click="closeReset">取消</button>
        <button class="primary-button" :disabled="!passwordValid" @click="submitReset">确认重置</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.user-table { min-width: 1080px; }
.status-filter {
  height: 34px;
  padding: 0 10px;
  border: 1px solid #e6e3e9;
  border-radius: 8px;
  color: #6f6a78;
  background: #fff;
  font-size: var(--font-size-body);
}
.user-cell strong { display: block; color: #3f3b46; font-size: var(--font-size-body); font-weight: 600; }
.user-cell em {
  display: block;
  margin-top: 2px;
  color: #8f7ea8;
  font-size: var(--font-size-caption);
  font-style: normal;
}
.tag-row { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.mini-tag {
  padding: 3px 7px;
  border-radius: 6px;
  color: #5f4abd;
  background: #f0edfb;
  font-size: var(--font-size-caption);
}
.muted-text { color: #aaa6b1; font-size: var(--font-size-caption); }
.status-cell { display: flex; align-items: center; gap: 6px; }
.lock-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 6px;
  border-radius: 8px;
  color: #b9772e;
  background: #fdf1e0;
  font-size: var(--font-size-caption);
  white-space: nowrap;
}
.table-loading { padding: 38px 0; color: #9a95a1; font-size: var(--font-size-body); text-align: center; }
.role-assign { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 10px; }
.role-chip-list { flex: 1 1 240px; min-height: 34px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.role-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 4px 6px 4px 9px;
  border-radius: 7px;
  color: #5f4abd;
  background: #f0edfb;
  font-size: var(--font-size-caption);
}
.role-chip button {
  width: 17px;
  height: 17px;
  display: grid;
  place-items: center;
  border-radius: 4px;
  color: #8b79c7;
}
.role-chip button:hover { color: #fff; background: #8b79c7; }
.add-role-button {
  height: 34px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px dashed #b8a9e6;
  border-radius: 8px;
  color: #6750c4;
  background: #fff;
  font-size: var(--font-size-body);
  white-space: nowrap;
}
.add-role-button:hover { border-color: #8f77d6; background: #faf8ff; }
.role-picker-backdrop { z-index: 95; }
.role-picker-card { width: min(760px, 100%); }
.role-picker-table-wrap { max-height: 360px; overflow: auto; border: 1px solid #ece9f0; border-radius: 10px; }
.role-picker-table { min-width: 0; }
.role-picker-table th { position: sticky; top: 0; z-index: 1; }
.role-picker-table th:last-child, .role-picker-table td:last-child { text-align: left; }
.role-picker-table tbody tr { cursor: pointer; }
.role-picker-table tbody tr:hover td { background: #faf8ff; }
.role-picker-table tbody tr.selected td { background: #f5f1ff; }
.role-picker-table td { height: 48px; }
.role-picker-table .check-cell { width: 38px; padding-right: 0; }
.role-picker-table code { padding: 2px 6px; border-radius: 5px; color: #6f59d4; background: #f4f1fb; font-size: var(--font-size-caption); }
.role-name-cell { display: flex; align-items: center; gap: 6px; }
.role-name-cell strong { color: #3f3b46; font-weight: 600; }
.role-name-cell em {
  padding: 1px 6px;
  border-radius: 6px;
  color: #8f8a97;
  background: #f2f0f6;
  font-size: var(--font-size-caption);
  font-style: normal;
}
.role-picker-table tbody tr.role-picker-empty { cursor: default; }
.role-picker-table tbody tr.role-picker-empty:hover td { background: transparent; }
.role-picker-table td.role-picker-empty { color: #aaa6b1; font-size: var(--font-size-body); text-align: center; }
.reset-card { width: min(460px, 100%); }
.reset-field { display: block; }
.reset-field > span { display: block; margin-bottom: 6px; color: #65616d; font-size: var(--font-size-body); font-weight: 500; }
.password-field {
  height: 38px;
  padding: 0 8px 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #e1dee5;
  border-radius: 8px;
  background: #fff;
}
.password-field:focus-within { border-color: #b9a9ec; box-shadow: 0 0 0 3px #f1ecfd; }
.password-field input { width: 100%; border: 0; outline: none; color: #514d58; background: transparent; font-size: var(--font-size-body); }
.password-field button { flex: 0 0 auto; color: #8f8a97; }
.password-actions { margin-top: 12px; display: flex; gap: 8px; }
.password-actions button {
  height: 32px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #e1dee5;
  border-radius: 8px;
  color: #6750c4;
  background: #fff;
  font-size: var(--font-size-caption);
}
.password-actions button:disabled { color: #b1adb8; cursor: not-allowed; }
.modal-card footer .primary-button:disabled { opacity: .5; cursor: not-allowed; }
.source-tag { display: inline-block; padding: 2px 7px; border-radius: 6px; color: #7d7790; background: #f3f2f6; font-size: var(--font-size-caption); white-space: nowrap; }
.source-tag.resident { color: #5f4bb5; background: #f1edfc; }
.resident-link-cell { display: flex; flex-direction: column; line-height: 1.35; }
.resident-link-cell strong { color: #4a4552; font-size: var(--font-size-body); font-weight: 500; }
.resident-link-cell span { color: #9a95a1; font-size: var(--font-size-caption); }
.mobile-tag { color: #9a95a1; font-size: var(--font-size-caption); white-space: nowrap; }
.mobile-tag.bound { color: #4f8a68; }
.mobile-tag.warn { color: #b06a6a; }
.link-resident-card { width: min(880px, 100%); }
.link-resident-body { max-height: min(72vh, 680px); overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
.link-current { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border: 1px solid #e6e1ef; border-radius: 9px; background: #faf8ff; }
.link-current > span { color: #8f8799; font-size: var(--font-size-caption); }
.link-current > strong { color: #4a4552; font-size: var(--font-size-body); font-weight: 500; }
.link-current > em { color: #9a95a1; font-size: var(--font-size-caption); font-style: normal; }
.link-section { min-width: 0; }
.link-section-head { margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.link-section-head > span { display: inline-flex; align-items: center; gap: 7px; color: #4a4552; font-size: var(--font-size-body); font-weight: 600; }
.link-section-head i {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 50%;
  color: #fff;
  background: #6f59d4;
  font-size: 11px;
  font-style: normal;
}
.link-section-head > em { color: #9a95a1; font-size: var(--font-size-caption); font-style: normal; }
.link-cascade { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.link-cascade label { flex: 1 1 130px; min-width: 0; }
.link-cascade select {
  width: 100%;
  height: 34px;
  padding: 0 8px;
  border: 1px solid #e1dee5;
  border-radius: 8px;
  color: #514d58;
  background: #fff;
  font-size: var(--font-size-body);
}
.link-cascade select:disabled { color: #b1adb8; background: #f8f7fa; }
.link-cascade-arrow { flex: 0 0 auto; color: #b3aec0; }
.link-community-search {
  height: 36px;
  padding: 0 11px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #e1dee5;
  border-radius: 8px;
  background: #fff;
}
.link-community-search:focus-within { border-color: #b9a9ec; box-shadow: 0 0 0 3px #f1ecfd; }
.link-community-search svg { flex: 0 0 auto; color: #9a95a1; }
.link-community-search input { width: 100%; border: 0; outline: none; color: #514d58; background: transparent; font-size: var(--font-size-body); }
.link-community-results, .link-resident-list {
  margin-top: 8px;
  max-height: 180px;
  overflow-y: auto;
  border: 1px solid #ece9f0;
  border-radius: 9px;
  background: #fff;
}
.link-resident-list { max-height: 220px; }
.link-community-option {
  width: 100%;
  padding: 9px 11px;
  display: flex;
  align-items: center;
  gap: 9px;
  border-bottom: 1px solid #f3f1f6;
  text-align: left;
  cursor: pointer;
}
.link-community-option:last-child { border-bottom: 0; }
.link-community-option:hover { background: #faf8ff; }
.link-community-icon { width: 28px; height: 28px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 8px; color: #6f59d4; background: #f1edfc; }
.link-community-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; text-align: left; }
.link-community-main strong { overflow: hidden; color: #3f3b46; font-size: var(--font-size-body); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.link-community-main em { overflow: hidden; color: #9a95a1; font-size: var(--font-size-caption); font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.link-community-selected { padding: 9px 11px; display: flex; align-items: center; gap: 10px; border: 1px solid #ddd5f5; border-radius: 9px; background: #faf8ff; }
.link-community-selected button {
  height: 28px;
  padding: 0 9px;
  flex: 0 0 auto;
  border: 1px solid #d8cff2;
  border-radius: 7px;
  color: #6750c4;
  background: #fff;
  font-size: var(--font-size-caption);
}
.link-community-selected button:hover { border-color: #b9a9ec; background: #f6f2ff; }
.link-empty { padding: 16px 12px; color: #aaa6b1; font-size: var(--font-size-caption); text-align: center; }
.link-empty-tall { padding: 24px 12px; border: 1px dashed #e6e2ee; border-radius: 9px; background: #fbfafc; }
.link-resident-option {
  width: 100%;
  padding: 9px 11px;
  display: flex;
  align-items: center;
  gap: 9px;
  border-bottom: 1px solid #f3f1f6;
  text-align: left;
  cursor: pointer;
}
.link-resident-option:last-child { border-bottom: 0; }
.link-resident-option:hover { background: #faf8ff; }
.link-resident-option.selected { background: #f5f1ff; }
.link-resident-option.disabled { opacity: .55; cursor: not-allowed; }
.link-resident-option.disabled:hover { background: transparent; }
.link-resident-radio { width: 15px; height: 15px; flex: 0 0 auto; border: 1.5px solid #cfc8db; border-radius: 50%; background: #fff; }
.link-resident-radio.checked { border-color: #6f59d4; background: radial-gradient(circle, #6f59d4 0 4px, #fff 4.5px 100%); }
.link-resident-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.link-resident-main strong { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; color: #3f3b46; font-size: var(--font-size-body); font-weight: 600; }
.link-resident-main strong em { padding: 1px 6px; border-radius: 5px; color: #7d7790; background: #f2f0f6; font-size: var(--font-size-caption); font-style: normal; font-weight: 400; }
.link-resident-main strong em.current { color: #5f4abd; background: #ece7fb; }
.link-resident-main > span { color: #9a95a1; font-size: var(--font-size-caption); }
.link-resident-warn { flex: 0 0 auto; color: #b06a6a; font-size: var(--font-size-caption); font-style: normal; }
.link-resident-card footer { display: flex; align-items: center; gap: 8px; }
.link-unbind-button { margin-right: auto; color: #c9525e; }
.link-unbind-button:hover { background: #fdf2f3; }
.link-unbind-button:disabled { opacity: .5; cursor: not-allowed; }
</style>
