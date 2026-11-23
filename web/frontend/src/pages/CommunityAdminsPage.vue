<script setup lang="ts">
/**
 * 社区管理员：为「用户管理」中的后台账号分配可管理的行政区划与社区/院校。
 * 区划授权与指定社区均由服务端持久化，保存后立即影响账号的数据范围。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  GraduationCap,
  Info,
  MapPin,
  MapPinned,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-vue-next'
import { adminUsersApi, communityApi } from '@/api'
import { fmtRelative } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useConfirm } from '@/composables/useConfirm'
import { groupProvinces, indexRegions, type RegionEntry, type RegionNode } from '@/utils/region'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

type CommunityRef = {
  id: string
  name: string
  code?: string
  type?: string
  address?: string
}

type ScopeGrant = {
  id: string
  mode: 'REGION' | 'COMMUNITY'
  regionIds: string[]
  path: string[]
  level: string
  communities: CommunityRef[]
  updatedAt: number
}

type GrantStore = Record<string, ScopeGrant[]>

type ScopeFilter = 'ALL' | 'ASSIGNED' | 'EMPTY'

const app = useAppStore()
const auth = useAuthStore()
const { confirm } = useConfirm()

const adminRows = ref<any[]>([])
const adminTotal = ref(0)
const adminStats = ref({ total: 0, active: 0, disabled: 0, locked: 0 })
const adminLoading = ref(false)
const adminQuery = ref('')
const scopeFilter = ref<ScopeFilter>('ALL')
const selectedUserId = ref('')

const grantsByUser = ref<GrantStore>({})
const loadingScopeUsers = ref<Set<string>>(new Set())
const scopeSaving = ref(false)

const regionRoots = ref<RegionNode[]>([])
const regionIndex = ref<Record<string, RegionEntry>>({})
const regionLoading = ref(false)
const regionError = ref('')
let regionPromise: Promise<void> | null = null

const grantQuery = ref('')
const collapsedProvinces = ref<Set<string>>(new Set())

const grantDrawerOpen = ref(false)
const pickerProvinceId = ref('')
const pickerCityId = ref('')
const pickerDistrictId = ref('')
const pickerStreetId = ref('')
const pickerMode = ref<'REGION' | 'COMMUNITY'>('COMMUNITY')
const pickerModeAuto = ref(false)
const pickerKeyword = ref('')
const pickerCommunities = ref<any[]>([])
const pickerSelected = ref<Record<string, CommunityRef>>({})
const pickerPage = ref(1)
const pickerTotal = ref(0)
const pickerLoading = ref(false)
let pickerSearchTimer: number | undefined
let pickerRequestId = 0

const selectedUser = computed(() =>
  adminRows.value.find((row) => String(row.id) === selectedUserId.value) || null)

const currentGrants = computed(() =>
  selectedUserId.value ? grantsByUser.value[selectedUserId.value] || [] : [])

const scopeLoading = computed(() =>
  Boolean(selectedUserId.value) && loadingScopeUsers.value.has(selectedUserId.value))

const editBlockedReason = computed(() => {
  const user = selectedUser.value
  if (!user) return ''
  if (user.isSuperAdmin) return '超级管理员默认拥有全部社区权限，无需单独分配管理范围。'
  if (user.status !== 'ACTIVE') return '该账号已停用，请先在「用户管理」中启用后再分配管理范围。'
  if (!auth.hasPermission('system:admin-user:update')) {
    return '当前账号仅有查看权限，不能调整社区管理范围。'
  }
  if (!auth.isSuperAdmin && auth.dataScope !== 'ALL') {
    return '仅全局数据范围的管理员可调整社区管理范围。'
  }
  return ''
})

const canEditSelected = computed(() => Boolean(selectedUser.value) && !editBlockedReason.value)

const filteredAdmins = computed(() => {
  const keyword = adminQuery.value.trim().toLowerCase()
  return adminRows.value.filter((row) => {
    if (scopeFilter.value === 'ASSIGNED' && !hasAssignments(row)) return false
    if (scopeFilter.value === 'EMPTY' && hasAssignments(row)) return false
    if (!keyword) return true
    const haystack = [
      row.realName,
      row.username,
      row.communityName,
      ...(row.roles || []).map((role: any) => role.name),
    ].join(' ').toLowerCase()
    return haystack.includes(keyword)
  })
})

const adminCounts = computed(() => {
  let assigned = 0
  for (const row of adminRows.value) {
    if (hasAssignments(row)) assigned += 1
  }
  return {
    all: adminRows.value.length,
    assigned,
    empty: adminRows.value.length - assigned,
  }
})

const pageStats = computed(() => {
  const communityIds = new Set<string>()
  let assigned = 0
  for (const row of adminRows.value) {
    const id = String(row.id)
    if (hasLoadedScope(id)) {
      const grants = grantsByUser.value[id] || []
      if (grants.length) assigned += 1
      grants.forEach((grant) => {
        if (grant.mode === 'COMMUNITY') grant.communities.forEach((item) => communityIds.add(item.id))
      })
    } else if (Number(row.scopeRegionCount || 0) > 0 || (row.communities || []).length) {
      assigned += 1
      row.communities.forEach((item: any) => communityIds.add(String(item.id)))
    }
  }
  const total = adminTotal.value || adminRows.value.length
  return {
    total,
    assigned,
    pending: Math.max(0, total - assigned),
    communities: communityIds.size,
    active: adminStats.value.active,
  }
})

const coverage = computed(() => {
  const levels = [new Set<string>(), new Set<string>(), new Set<string>(), new Set<string>()]
  const communities = new Set<string>()
  for (const grant of currentGrants.value) {
    grant.regionIds.forEach((id, index) => {
      if (index < levels.length) levels[index].add(id)
    })
    if (grant.mode === 'COMMUNITY') {
      grant.communities.forEach((item) => communities.add(item.id))
    }
  }
  return {
    provinces: levels[0].size,
    cities: levels[1].size,
    districts: levels[2].size,
    streets: levels[3].size,
    communities: communities.size,
  }
})

const filteredGrants = computed(() => {
  const keyword = grantQuery.value.trim().toLowerCase()
  return currentGrants.value
    .filter((grant) => {
      if (!keyword) return true
      const haystack = [
        ...grant.path,
        ...grant.communities.map((item) => `${item.name} ${item.code || ''} ${item.type || ''}`),
      ].join(' ').toLowerCase()
      return haystack.includes(keyword)
    })
    .slice()
    .sort((a, b) => a.path.join('/').localeCompare(b.path.join('/'), 'zh-CN') || b.updatedAt - a.updatedAt)
})

const grantGroups = computed(() => {
  const groups = new Map<string, {
    province: string
    grants: ScopeGrant[]
    communityCount: number
    regionCount: number
  }>()
  for (const grant of filteredGrants.value) {
    const province = grant.path[0] || '未归属区划'
    let group = groups.get(province)
    if (!group) {
      group = { province, grants: [], communityCount: 0, regionCount: 0 }
      groups.set(province, group)
    }
    group.grants.push(grant)
    if (grant.mode === 'REGION') group.regionCount += 1
    else group.communityCount += grant.communities.length
  }
  return Array.from(groups.values())
    .sort((a, b) => a.province.localeCompare(b.province, 'zh-CN'))
})

const provinceGroups = computed(() => groupProvinces(regionRoots.value))
const pickerProvinceNode = computed(() =>
  (pickerProvinceId.value ? regionIndex.value[pickerProvinceId.value]?.node : undefined) || null)
const pickerCityNodes = computed<RegionNode[]>(() => pickerProvinceNode.value?.children || [])
const pickerDistrictNodes = computed<RegionNode[]>(() =>
  (pickerCityId.value ? regionIndex.value[pickerCityId.value]?.node.children : undefined) || [])
const pickerStreetNodes = computed<RegionNode[]>(() =>
  (pickerDistrictId.value ? regionIndex.value[pickerDistrictId.value]?.node.children : undefined) || [])

const pickerPathIds = computed(() =>
  [pickerProvinceId.value, pickerCityId.value, pickerDistrictId.value, pickerStreetId.value]
    .filter(Boolean))

const pickerRegionPath = computed(() =>
  pickerPathIds.value
    .map((id) => regionIndex.value[id]?.node.name)
    .filter((name): name is string => Boolean(name)))

const pickerLevel = computed(() => {
  const id = pickerPathIds.value[pickerPathIds.value.length - 1]
  return id ? regionIndex.value[id]?.node.level || '' : ''
})

const pickerSelectedList = computed(() => Object.values(pickerSelected.value))
const pickerSelectedCount = computed(() => pickerSelectedList.value.length)
const pickerHasMore = computed(() => pickerCommunities.value.length < pickerTotal.value)
const pickerAllVisibleSelected = computed(() =>
  pickerCommunities.value.length > 0
  && pickerCommunities.value.every((item) => Boolean(pickerSelected.value[String(item.id)])))

const pickerValid = computed(() => {
  if (!canEditSelected.value) return false
  if (!pickerProvinceId.value) return false
  if (pickerMode.value === 'REGION') return true
  return pickerSelectedCount.value > 0
})

function hasLoadedScope(userId: string): boolean {
  return Object.prototype.hasOwnProperty.call(grantsByUser.value, userId)
}

function setUserGrants(userId: string, grants: ScopeGrant[]) {
  grantsByUser.value = { ...grantsByUser.value, [userId]: grants }
}

function hasAssignments(row: any): boolean {
  const id = String(row.id)
  if (hasLoadedScope(id)) return (grantsByUser.value[id] || []).length > 0
  return Number(row.scopeRegionCount || 0) > 0 || (row.communities || []).length > 0
}

/** 服务端范围 -> 页面分组。区划授权与指定社区分开返回，社区按所在区划路径分组。 */
function scopeFromPayload(data: any): ScopeGrant[] {
  const grants: ScopeGrant[] = []
  const coveredRegionPaths: string[][] = []
  for (const item of data?.regionGrants || []) {
    const nodes = item?.path || []
    const regionIds = nodes.map((node: any) => String(node.id))
    const grant: ScopeGrant = {
      id: `region-${item?.regionId || regionIds[regionIds.length - 1] || uniqueId()}`,
      mode: 'REGION',
      regionIds,
      path: nodes.map((node: any) => String(node.name || '')),
      level: String(item?.level || nodes[nodes.length - 1]?.level || 'UNKNOWN'),
      communities: [],
      updatedAt: Number(item?.updatedAt || 0),
    }
    grants.push(grant)
    if (regionIds.length) coveredRegionPaths.push(regionIds)
  }

  const groups = new Map<string, ScopeGrant>()
  for (const community of data?.communities || []) {
    const nodes = community?.path || []
    const regionIds = nodes.map((node: any) => String(node.id))
    // 区划授权已经覆盖的社区不在“社区授权”中重复展示。
    if (coveredRegionPaths.some((prefix) => isPrefix(prefix, regionIds))) continue
    const key = regionIds.join('/') || `unassigned-${community?.id || ''}`
    let grant = groups.get(key)
    if (!grant) {
      grant = {
        id: `community-${key}`,
        mode: 'COMMUNITY',
        regionIds,
        path: nodes.map((node: any) => String(node.name || '')),
        level: String(nodes[nodes.length - 1]?.level || 'UNKNOWN'),
        communities: [],
        updatedAt: 0,
      }
      groups.set(key, grant)
    }
    grant.communities.push({
      id: String(community.id),
      name: String(community.name || '社区'),
      code: String(community.code || ''),
      type: String(community.type || ''),
      address: String(community.address || ''),
    })
  }
  return grants.concat(Array.from(groups.values()))
}

/** 页面分组 -> 服务端全量替换载荷。区划只提交最末级节点，由服务端展开子树。 */
function serializeScope(grants: ScopeGrant[]): { regionIds: number[]; communityIds: number[] } {
  const regionIds = new Set<number>()
  const communityIds = new Set<number>()
  for (const grant of grants) {
    if (grant.mode === 'REGION') {
      const deepest = Number(grant.regionIds[grant.regionIds.length - 1] || 0)
      if (deepest > 0) regionIds.add(deepest)
      continue
    }
    grant.communities.forEach((item) => {
      const id = Number(item.id)
      if (id > 0) communityIds.add(id)
    })
  }
  return { regionIds: Array.from(regionIds), communityIds: Array.from(communityIds) }
}

function uniqueId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `grant-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function sameIds(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((id, index) => id === right[index])
}

function isPrefix(prefix: string[], ids: string[]): boolean {
  return prefix.length <= ids.length && prefix.every((id, index) => id === ids[index])
}

function levelLabel(level: string): string {
  switch (level) {
    case 'PROVINCE': return '省级'
    case 'CITY': return '市级'
    case 'DISTRICT': return '区县级'
    case 'STREET': return '街道级'
    default: return '区划'
  }
}

function modeLabel(mode: string): string {
  return mode === 'REGION' ? '区划授权' : '社区授权'
}

function isCampus(community: CommunityRef): boolean {
  return /院校|学校|大学|学院/.test(community?.type || '')
}

function avatarText(row: any): string {
  return (row?.realName || row?.username || '?').charAt(0)
}

function roleNames(row: any): string {
  const names = (row?.roles || []).map((role: any) => role.name).filter(Boolean)
  return names.length ? names.join(' / ') : '未分配角色'
}

function adminScopeText(row: any): string {
  const id = String(row.id)
  if (hasLoadedScope(id)) {
    const grants = grantsByUser.value[id] || []
    if (!grants.length) return '未分配管理范围'
    const communities = new Set<string>()
    let regionCount = 0
    grants.forEach((grant) => {
      if (grant.mode === 'REGION') regionCount += 1
      else grant.communities.forEach((item) => communities.add(item.id))
    })
    const parts: string[] = []
    if (regionCount) parts.push(`${regionCount} 项区划授权`)
    if (communities.size) parts.push(`${communities.size} 个指定社区`)
    return parts.join(' · ') || '未分配管理范围'
  }
  const parts: string[] = []
  const regionCount = Number(row.scopeRegionCount || 0)
  const communityCount = (row.communities || []).length
  if (regionCount) parts.push(`${regionCount} 项区划授权`)
  if (communityCount) parts.push(`${communityCount} 个指定社区`)
  return parts.join(' · ') || '未分配管理范围'
}

function grantLocation(grant: ScopeGrant): string {
  if (!grant.path.length) return '未归属区划'
  if (grant.path.length === 1) return `${grant.path[0]} · 全部辖区`
  return grant.path.slice(1).join(' / ')
}

function toggleProvince(province: string) {
  const next = new Set(collapsedProvinces.value)
  if (next.has(province)) next.delete(province)
  else next.add(province)
  collapsedProvinces.value = next
}

async function loadAdmins() {
  adminLoading.value = true
  try {
    const first = await adminUsersApi.list({ page: 1, pageSize: 50 })
    let items = first?.items || []
    const total = Number(first?.total || items.length)
    adminTotal.value = total
    adminStats.value = first?.stats || {
      total,
      active: items.filter((row: any) => row.status === 'ACTIVE').length,
      disabled: items.filter((row: any) => row.status !== 'ACTIVE').length,
      locked: 0,
    }
    let page = 1
    while (items.length < total && page < 10) {
      page += 1
      const next = await adminUsersApi.list({ page, pageSize: 50 })
      const nextItems = next?.items || []
      if (!nextItems.length) break
      items = items.concat(nextItems)
    }
    adminRows.value = items
    if (!items.length) {
      selectedUserId.value = ''
      return
    }
    if (!items.some((row: any) => String(row.id) === selectedUserId.value)) {
      const preferred = items.find((row: any) =>
        !row.isSuperAdmin && row.status === 'ACTIVE' && hasAssignments(row))
        || items.find((row: any) => !row.isSuperAdmin && row.status === 'ACTIVE')
        || items[0]
      selectedUserId.value = String(preferred.id)
    }
  } catch (exc: any) {
    adminRows.value = []
    adminTotal.value = 0
    selectedUserId.value = ''
    app.showToast(exc?.message || '后台账号加载失败')
  } finally {
    adminLoading.value = false
  }
}

async function refreshAll() {
  grantsByUser.value = {}
  loadingScopeUsers.value = new Set()
  await loadAdmins()
  if (selectedUser.value) await loadUserScope(selectedUser.value)
}

function ensureRegions(): Promise<void> {
  if (regionRoots.value.length) return Promise.resolve()
  if (regionPromise) return regionPromise
  regionLoading.value = true
  regionError.value = ''
  regionPromise = communityApi.regionTree()
    .then((roots) => {
      regionRoots.value = (roots as RegionNode[]) || []
      regionIndex.value = indexRegions(regionRoots.value)
    })
    .catch((exc: any) => {
      regionError.value = exc?.message || '行政区划加载失败'
    })
    .finally(() => {
      regionLoading.value = false
      regionPromise = null
    })
  return regionPromise
}

function retryRegions() {
  communityApi.clearRegionCache()
  regionRoots.value = []
  regionIndex.value = {}
  regionPromise = null
  ensureRegions()
}

async function loadUserScope(row: any) {
  const id = String(row.id)
  if (hasLoadedScope(id) || loadingScopeUsers.value.has(id)) return
  const pending = new Set(loadingScopeUsers.value)
  pending.add(id)
  loadingScopeUsers.value = pending
  try {
    const data = await adminUsersApi.communityScope(id)
    setUserGrants(id, scopeFromPayload(data))
  } catch (exc: any) {
    app.showToast(exc?.message || '管理范围加载失败')
  } finally {
    const done = new Set(loadingScopeUsers.value)
    done.delete(id)
    loadingScopeUsers.value = done
  }
}

async function persistScope(grants: ScopeGrant[], message: string): Promise<boolean> {
  const user = selectedUser.value
  if (!user || scopeSaving.value) return false
  scopeSaving.value = true
  try {
    const data = await adminUsersApi.saveCommunityScope(user.id, serializeScope(grants))
    setUserGrants(String(user.id), scopeFromPayload(data))
    app.showToast(message)
    return true
  } catch (exc: any) {
    app.showToast(exc?.message || '管理范围保存失败')
    return false
  } finally {
    scopeSaving.value = false
  }
}

watch(selectedUserId, async (id) => {
  grantQuery.value = ''
  collapsedProvinces.value = new Set()
  if (!id) return
  const row = adminRows.value.find((item) => String(item.id) === id)
  if (row) await loadUserScope(row)
})

function selectUser(row: any) {
  selectedUserId.value = String(row.id)
}

function selectFilter(filter: ScopeFilter) {
  scopeFilter.value = filter
}

function resetPicker() {
  pickerProvinceId.value = ''
  pickerCityId.value = ''
  pickerDistrictId.value = ''
  pickerStreetId.value = ''
  pickerMode.value = 'COMMUNITY'
  pickerModeAuto.value = false
  pickerKeyword.value = ''
  pickerCommunities.value = []
  pickerSelected.value = {}
  pickerPage.value = 1
  pickerTotal.value = 0
  pickerLoading.value = false
  pickerRequestId += 1
  if (pickerSearchTimer) window.clearTimeout(pickerSearchTimer)
}

async function openGrantDrawer() {
  if (!canEditSelected.value) return
  resetPicker()
  grantDrawerOpen.value = true
  await ensureRegions()
}

function closeGrantDrawer() {
  grantDrawerOpen.value = false
  if (pickerSearchTimer) window.clearTimeout(pickerSearchTimer)
}

function handlePickerRegionChange() {
  if (pickerSearchTimer) {
    window.clearTimeout(pickerSearchTimer)
    pickerSearchTimer = undefined
  }
  pickerKeyword.value = ''
  pickerCommunities.value = []
  pickerTotal.value = 0
  pickerSelected.value = {}
  pickerPage.value = 1
  pickerRequestId += 1
  if (pickerProvinceId.value && !pickerCityId.value && pickerMode.value === 'COMMUNITY') {
    pickerMode.value = 'REGION'
    pickerModeAuto.value = true
  } else if (pickerCityId.value && pickerModeAuto.value && pickerMode.value === 'REGION') {
    pickerMode.value = 'COMMUNITY'
    pickerModeAuto.value = false
  }
  if (pickerMode.value === 'COMMUNITY' && pickerCityId.value) {
    loadPickerCommunities(true)
  }
}

function onPickerProvinceChange() {
  pickerCityId.value = ''
  pickerDistrictId.value = ''
  pickerStreetId.value = ''
  handlePickerRegionChange()
}

function onPickerCityChange() {
  pickerDistrictId.value = ''
  pickerStreetId.value = ''
  handlePickerRegionChange()
}

function onPickerDistrictChange() {
  pickerStreetId.value = ''
  handlePickerRegionChange()
}

function onPickerStreetChange() {
  handlePickerRegionChange()
}

function resetPickerRegion() {
  pickerProvinceId.value = ''
  pickerCityId.value = ''
  pickerDistrictId.value = ''
  pickerStreetId.value = ''
  pickerMode.value = 'COMMUNITY'
  pickerModeAuto.value = false
  handlePickerRegionChange()
}

function selectPickerMode(mode: 'REGION' | 'COMMUNITY') {
  if (mode === 'COMMUNITY' && !pickerCityId.value) return
  if (mode === 'REGION' && !pickerProvinceId.value) return
  pickerMode.value = mode
  pickerModeAuto.value = false
  if (mode === 'COMMUNITY' && pickerCityId.value && !pickerCommunities.value.length) {
    loadPickerCommunities(true)
  }
}

async function loadPickerCommunities(reset = false) {
  if (pickerMode.value !== 'COMMUNITY') return
  if (!pickerDistrictId.value && !pickerCityId.value) {
    pickerCommunities.value = []
    pickerTotal.value = 0
    return
  }
  const requestId = ++pickerRequestId
  pickerLoading.value = true
  if (reset) pickerPage.value = 1
  const params: Record<string, any> = { page: pickerPage.value, pageSize: 50 }
  if (pickerKeyword.value.trim()) params.keyword = pickerKeyword.value.trim()
  if (pickerStreetId.value) params.streetId = pickerStreetId.value
  else if (pickerDistrictId.value) params.regionId = pickerDistrictId.value
  else if (pickerCityId.value) params.cityId = pickerCityId.value
  try {
    const data = await communityApi.list(params)
    if (requestId !== pickerRequestId) return
    const items = (data?.items || []).filter(
      (row: any) => !['PENDING', 'REJECTED'].includes(String(row.statusCode || row.status || '')),
    )
    pickerTotal.value = Number(data?.total || 0)
    pickerCommunities.value = reset ? items : pickerCommunities.value.concat(items)
  } catch (exc: any) {
    if (requestId === pickerRequestId) {
      if (reset) {
        pickerCommunities.value = []
        pickerTotal.value = 0
      } else if (pickerPage.value > 1) {
        // 加载更多失败时回退页码，避免下次跳页漏数据。
        pickerPage.value -= 1
      }
      app.showToast(exc?.message || '社区检索失败')
    }
  } finally {
    if (requestId === pickerRequestId) pickerLoading.value = false
  }
}

function onPickerSearchInput() {
  if (pickerSearchTimer) window.clearTimeout(pickerSearchTimer)
  pickerSearchTimer = window.setTimeout(() => loadPickerCommunities(true), 260)
}

function loadMoreCommunities() {
  if (pickerLoading.value || !pickerHasMore.value) return
  pickerPage.value += 1
  loadPickerCommunities(false)
}

function togglePickerCommunity(community: any) {
  const id = String(community.id)
  const next = { ...pickerSelected.value }
  if (next[id]) {
    delete next[id]
  } else {
    next[id] = {
      id,
      name: community.name || '社区',
      code: community.code || '',
      type: community.type || '',
      address: community.address || '',
    }
  }
  pickerSelected.value = next
}

function removePickerCommunity(id: string) {
  const next = { ...pickerSelected.value }
  delete next[id]
  pickerSelected.value = next
}

function clearPickerSelection() {
  pickerSelected.value = {}
}

function toggleAllVisibleCommunities() {
  if (pickerAllVisibleSelected.value) {
    const next = { ...pickerSelected.value }
    pickerCommunities.value.forEach((item) => delete next[String(item.id)])
    pickerSelected.value = next
    return
  }
  const next = { ...pickerSelected.value }
  pickerCommunities.value.forEach((item) => {
    next[String(item.id)] = {
      id: String(item.id),
      name: item.name || '社区',
      code: item.code || '',
      type: item.type || '',
      address: item.address || '',
    }
  })
  pickerSelected.value = next
}

async function submitGrant() {
  const user = selectedUser.value
  if (!user || !pickerValid.value || scopeSaving.value) return
  const existing = currentGrants.value.slice()
  const pathIds = pickerPathIds.value.slice()
  const pathNames = pickerRegionPath.value.slice()
  const level = pickerLevel.value || 'UNKNOWN'
  const now = Date.now()

  if (pickerMode.value === 'REGION') {
    if (existing.some((grant) => grant.mode === 'REGION' && sameIds(grant.regionIds, pathIds))) {
      app.showToast('该区划已整体授权，无需重复添加')
      return
    }
    if (existing.some((grant) => grant.mode === 'REGION' && isPrefix(grant.regionIds, pathIds))) {
      app.showToast('该区划已包含在现有区划授权中')
      return
    }
    // 上级区划授权会覆盖其下所有社区与子区划，自动合并冗余的下级授权。
    const kept = existing.filter((grant) => !isPrefix(pathIds, grant.regionIds))
    const merged = existing.length - kept.length
    kept.push({
      id: `region-${pathIds[pathIds.length - 1] || uniqueId()}`,
      mode: 'REGION',
      regionIds: pathIds,
      path: pathNames,
      level,
      communities: [],
      updatedAt: now,
    })
    const saved = await persistScope(
      kept,
      merged ? `已添加区划授权，并合并 ${merged} 项下级授权` : '区划授权已添加',
    )
    if (saved) grantDrawerOpen.value = false
    return
  }

  const chosen = Object.values(pickerSelected.value)
  if (!chosen.length) return
  if (existing.some((grant) => grant.mode === 'REGION' && isPrefix(grant.regionIds, pathIds))) {
    app.showToast('该区划已整体授权，无需重复添加社区')
    return
  }
  const index = existing.findIndex((grant) =>
    grant.mode === 'COMMUNITY' && sameIds(grant.regionIds, pathIds))

  if (index >= 0) {
    const target = existing[index]
    const merged = new Map(target.communities.map((item) => [item.id, item]))
    let added = 0
    chosen.forEach((item) => {
      if (!merged.has(item.id)) {
        merged.set(item.id, item)
        added += 1
      }
    })
    if (!added) {
      app.showToast('所选社区已在管理范围内')
      return
    }
    existing[index] = {
      ...target,
      path: pathNames,
      level,
      communities: Array.from(merged.values()),
      updatedAt: now,
    }
    const saved = await persistScope(existing, `已追加 ${added} 个社区到现有授权`)
    if (saved) grantDrawerOpen.value = false
    return
  }

  existing.push({
    id: `community-${pathIds.join('/') || uniqueId()}`,
    mode: 'COMMUNITY',
    regionIds: pathIds,
    path: pathNames,
    level,
    communities: chosen,
    updatedAt: now,
  })
  const saved = await persistScope(existing, `已添加 ${chosen.length} 个社区`)
  if (saved) grantDrawerOpen.value = false
}

async function removeGrant(grant: ScopeGrant) {
  const user = selectedUser.value
  if (!user || !canEditSelected.value || scopeSaving.value) return
  const ok = await confirm({
    title: '移除管理范围',
    message: `确定从“${user.realName || user.username}”的管理范围中移除“${grant.path.join(' / ')}”吗？`,
    details: ['移除后该账号将不能再管理此范围下的社区；可随时重新分配。'],
    confirmText: '移除范围',
    danger: true,
  })
  if (!ok) return
  await persistScope(
    currentGrants.value.filter((item) => item.id !== grant.id),
    '管理范围已移除',
  )
}

async function clearAllGrants() {
  const user = selectedUser.value
  if (!user || !canEditSelected.value || !currentGrants.value.length || scopeSaving.value) return
  const ok = await confirm({
    title: '清空管理范围',
    message: `确定清空“${user.realName || user.username}”的全部管理范围吗？`,
    details: [`将移除 ${currentGrants.value.length} 项授权，该账号之后将无法管理这些社区。`],
    confirmText: '清空范围',
    danger: true,
  })
  if (!ok) return
  await persistScope([], '管理范围已清空')
}

onMounted(loadAdmins)

onBeforeUnmount(() => {
  if (pickerSearchTimer) window.clearTimeout(pickerSearchTimer)
  pickerRequestId += 1
})
</script>

<template>
  <div class="community-admins-page">
    <header class="admin-heading">
      <div class="admin-heading-main">
        <h1>社区管理员</h1>
        <p class="admin-subtitle">为后台账号分配可管理的社区范围，一次配置一个账号，支持跨省份、地市、区县与街道授权。</p>
      </div>
      <div class="admin-heading-side">
        <div class="admin-stat"><strong>{{ pageStats.total }}</strong><span>后台账号</span></div>
        <div class="admin-stat"><strong>{{ pageStats.assigned }}</strong><span>已配置</span></div>
        <div class="admin-stat"><strong>{{ pageStats.communities }}</strong><span>指定社区</span></div>
        <button class="admin-refresh" type="button" title="刷新账号与管理范围" :disabled="adminLoading || scopeLoading || scopeSaving" @click="refreshAll">
          <RefreshCw :size="17" :class="{ spinning: adminLoading }" />
        </button>
      </div>
    </header>

    <div class="admin-guidance">
      <span class="guidance-icon"><Info :size="16" /></span>
      <p><strong>一个账号可同时管理多个省份、地市、区县、街道及社区/院校。</strong>区划授权会覆盖该区划下全部社区，后续新增社区自动纳入；保存后立即影响该账号的数据范围。</p>
    </div>

    <div class="admin-workspace">
      <aside class="admin-list-panel">
        <div class="admin-list-head">
          <div>
            <strong>后台管理员</strong>
            <span>共 {{ pageStats.total }} 个账号 · {{ pageStats.active }} 个启用</span>
          </div>
          <ShieldCheck :size="17" />
        </div>

        <div class="admin-search">
          <Search :size="15" />
          <input v-model="adminQuery" aria-label="搜索后台管理员" placeholder="搜索姓名、用户名或角色…" />
        </div>

        <div class="admin-filter-tabs">
          <button type="button" :class="{ active: scopeFilter === 'ALL' }" @click="selectFilter('ALL')">
            全部 <em>{{ adminCounts.all }}</em>
          </button>
          <button type="button" :class="{ active: scopeFilter === 'ASSIGNED' }" @click="selectFilter('ASSIGNED')">
            已配置 <em>{{ adminCounts.assigned }}</em>
          </button>
          <button type="button" :class="{ active: scopeFilter === 'EMPTY' }" @click="selectFilter('EMPTY')">
            待配置 <em>{{ adminCounts.empty }}</em>
          </button>
        </div>

        <div class="admin-list">
          <button
            v-for="row in filteredAdmins"
            :key="row.id"
            type="button"
            :class="['admin-list-item', { active: String(row.id) === selectedUserId }]"
            @click="selectUser(row)"
          >
            <span :class="['admin-avatar', {
              super: row.isSuperAdmin,
              disabled: row.status !== 'ACTIVE',
            }]">{{ avatarText(row) }}</span>
            <span class="admin-item-main">
              <span class="admin-item-name">
                <strong>{{ row.realName || row.username }}</strong>
                <em v-if="row.isSuperAdmin" class="tag-super">超管</em>
                <em v-else-if="row.source === 'RESIDENT'" class="tag-resident">住户</em>
                <em v-if="row.status !== 'ACTIVE'" class="tag-disabled">停用</em>
              </span>
              <span class="admin-item-sub">{{ row.username }} · {{ roleNames(row) }}</span>
              <span :class="['admin-item-scope', { empty: !hasAssignments(row) }]">
                {{ adminScopeText(row) }}
              </span>
            </span>
            <ChevronRight :size="15" class="admin-item-chevron" />
          </button>

          <div v-if="adminLoading" class="admin-list-loading">
            <RefreshCw :size="15" class="spinning" />正在加载后台账号…
          </div>
          <EmptyState
            v-else-if="!filteredAdmins.length"
            title="没有匹配的账号"
            description="请调整搜索关键词或筛选条件"
          />
        </div>
      </aside>

      <section class="scope-panel">
        <template v-if="selectedUser">
          <header class="scope-header">
            <div class="scope-user">
              <span class="scope-avatar">{{ avatarText(selectedUser) }}</span>
              <div>
                <h2>
                  {{ selectedUser.realName || selectedUser.username }}
                  <span class="scope-username">@{{ selectedUser.username }}</span>
                </h2>
                <p>
                  <StatusBadge :value="selectedUser.status === 'ACTIVE' ? '正常' : '已停用'" />
                  <span class="scope-role">{{ roleNames(selectedUser) }}</span>
                  <span v-if="selectedUser.isSuperAdmin" class="scope-super">超级管理员</span>
                </p>
              </div>
            </div>
            <div class="scope-actions">
              <button
                type="button"
                class="scope-clear"
                :disabled="!currentGrants.length || !canEditSelected || scopeSaving"
                @click="clearAllGrants"
              >
                <RotateCcw :size="15" />{{ scopeSaving ? '保存中…' : '清空范围' }}
              </button>
              <button
                type="button"
                class="primary-button"
                :disabled="!canEditSelected || scopeLoading || scopeSaving"
                @click="openGrantDrawer"
              >
                <Plus :size="16" />新增管理范围
              </button>
            </div>
          </header>

          <div v-if="editBlockedReason" class="scope-readonly">
            <ShieldCheck :size="15" />
            <span>{{ editBlockedReason }}</span>
          </div>

          <div class="scope-coverage">
            <div><span>省份/直辖市</span><strong>{{ coverage.provinces }}</strong></div>
            <div><span>地市</span><strong>{{ coverage.cities }}</strong></div>
            <div><span>区县</span><strong>{{ coverage.districts }}</strong></div>
            <div><span>街道</span><strong>{{ coverage.streets }}</strong></div>
            <div class="accent"><span>指定社区/院校</span><strong>{{ coverage.communities }}</strong></div>
          </div>

          <div class="scope-toolbar">
            <div class="scope-search">
              <Search :size="15" />
              <input v-model="grantQuery" aria-label="搜索管理范围" placeholder="搜索区划、社区或院校…" />
            </div>
            <div class="scope-legend">
              <span class="region"><i />区划授权</span>
              <span class="community"><i />社区授权</span>
            </div>
          </div>

          <div class="scope-list">
            <div v-if="scopeLoading" class="scope-loading">
              <RefreshCw :size="17" class="spinning" />正在载入该账号已有的管理范围…
            </div>
            <template v-else>
              <section v-for="group in grantGroups" :key="group.province" class="grant-group">
                <button type="button" class="grant-group-head" @click="toggleProvince(group.province)">
                  <ChevronRight v-if="collapsedProvinces.has(group.province)" :size="14" />
                  <ChevronDown v-else :size="14" />
                  <span class="group-pin"><MapPin :size="13" /></span>
                  <strong>{{ group.province }}</strong>
                  <span class="grant-group-meta">
                    {{ group.grants.length }} 项授权
                    <template v-if="group.communityCount"> · {{ group.communityCount }} 个指定社区</template>
                    <template v-else-if="group.regionCount"> · 含整区授权</template>
                  </span>
                  <span class="grant-group-line" />
                </button>

                <div v-if="!collapsedProvinces.has(group.province)" class="grant-group-body">
                  <article
                    v-for="grant in group.grants"
                    :key="grant.id"
                    :class="['grant-card', grant.mode.toLowerCase()]"
                  >
                    <span class="grant-icon">
                      <MapPinned v-if="grant.mode === 'REGION'" :size="17" />
                      <Building2 v-else :size="17" />
                    </span>
                    <div class="grant-body">
                      <div class="grant-title-line">
                        <strong>{{ grantLocation(grant) }}</strong>
                        <span :class="['grant-type', grant.mode.toLowerCase()]">{{ modeLabel(grant.mode) }}</span>
                        <span class="grant-level">{{ levelLabel(grant.level) }}</span>
                      </div>

                      <p v-if="grant.mode === 'REGION'" class="grant-note">
                        覆盖该区划下全部社区与院校，含后续新增社区。
                      </p>
                      <div v-else class="community-chip-row">
                        <span
                          v-for="community in grant.communities"
                          :key="community.id"
                          class="community-chip"
                          :title="[community.name, community.code, community.address].filter(Boolean).join(' · ')"
                        >
                          <GraduationCap v-if="isCampus(community)" :size="12" />
                          <Building2 v-else :size="12" />
                          {{ community.name }}
                          <em v-if="community.type">{{ community.type }}</em>
                        </span>
                      </div>
                      <span class="grant-time">
                        {{ grant.updatedAt ? `更新于 ${fmtRelative(grant.updatedAt)}` : '配置已生效' }}
                      </span>
                    </div>
                    <div class="grant-side">
                      <strong>{{ grant.mode === 'COMMUNITY' ? grant.communities.length : '全部' }}</strong>
                      <span>社区</span>
                      <button
                        type="button"
                        class="grant-remove"
                        title="移除该管理范围"
                        :disabled="!canEditSelected || scopeSaving"
                        @click="removeGrant(grant)"
                      >
                        <Trash2 :size="15" />
                      </button>
                    </div>
                  </article>
                </div>
              </section>

              <EmptyState
                v-if="!filteredGrants.length"
                :title="currentGrants.length ? '没有匹配的管理范围' : '尚未分配管理范围'"
                :description="currentGrants.length
                  ? '请调整搜索关键词'
                  : '点击右上角「新增管理范围」，按行政区划或社区为账号授权'"
              />
            </template>
          </div>
        </template>

        <EmptyState
          v-else
          title="请选择后台管理员"
          description="从左侧账号列表选择一个账号，查看并配置其可管理的社区范围"
        />
      </section>
    </div>
  </div>

  <NiDrawer
    :open="grantDrawerOpen"
    :title="`新增管理范围 · ${selectedUser?.realName || selectedUser?.username || ''}`"
    eyebrow="为后台账号分配社区"
    @close="closeGrantDrawer"
  >
    <div class="grant-drawer">
      <div class="grant-target">
        <span class="target-avatar">{{ selectedUser ? avatarText(selectedUser) : '?' }}</span>
        <div>
          <strong>{{ selectedUser?.realName || selectedUser?.username }}</strong>
          <span>一次只为当前账号配置；可多次新增，覆盖多个省份、地市、区县、街道及社区/院校。</span>
        </div>
      </div>

      <section class="drawer-step">
        <div class="step-head">
          <i>1</i>
          <strong>选择行政区划</strong>
          <button v-if="pickerProvinceId" type="button" @click="resetPickerRegion">清除区划</button>
        </div>
        <div class="region-cascade">
          <label>
            <span>省份/直辖市</span>
            <select
              v-model="pickerProvinceId"
              aria-label="省份或直辖市"
              :disabled="regionLoading || !provinceGroups.length"
              @change="onPickerProvinceChange"
            >
              <option value="">{{ regionLoading ? '加载区划…' : '省份/直辖市' }}</option>
              <optgroup v-for="group in provinceGroups" :key="group.label" :label="group.label">
                <option v-for="province in group.provinces" :key="province.id" :value="String(province.id)">
                  {{ province.name }}
                </option>
              </optgroup>
            </select>
          </label>
          <ChevronRight :size="13" class="region-cascade-arrow" />
          <label>
            <span>地市</span>
            <select v-model="pickerCityId" aria-label="地市" :disabled="!pickerCityNodes.length" @change="onPickerCityChange">
              <option value="">{{ pickerCityNodes.length ? '地市' : '先选省份' }}</option>
              <option v-for="city in pickerCityNodes" :key="city.id" :value="String(city.id)">{{ city.name }}</option>
            </select>
          </label>
          <ChevronRight :size="13" class="region-cascade-arrow" />
          <label>
            <span>区/县</span>
            <select v-model="pickerDistrictId" aria-label="区县" :disabled="!pickerDistrictNodes.length" @change="onPickerDistrictChange">
              <option value="">{{ pickerDistrictNodes.length ? '区/县' : '先选地市' }}</option>
              <option v-for="district in pickerDistrictNodes" :key="district.id" :value="String(district.id)">{{ district.name }}</option>
            </select>
          </label>
          <ChevronRight :size="13" class="region-cascade-arrow" />
          <label>
            <span>街道（可选）</span>
            <select v-model="pickerStreetId" aria-label="街道" :disabled="!pickerStreetNodes.length" @change="onPickerStreetChange">
              <option value="">{{ pickerStreetNodes.length ? '街道（可选）' : '先选区县' }}</option>
              <option v-for="street in pickerStreetNodes" :key="street.id" :value="String(street.id)">{{ street.name }}</option>
            </select>
          </label>
        </div>

        <div v-if="pickerRegionPath.length" class="region-path-preview">
          <MapPin :size="14" />
          <span>{{ pickerRegionPath.join(' / ') }}</span>
          <em>{{ levelLabel(pickerLevel) }}</em>
        </div>
        <p v-if="regionError" class="region-error">
          {{ regionError }}
          <button type="button" @click="retryRegions">重新加载</button>
        </p>
      </section>

      <section class="drawer-step">
        <div class="step-head">
          <i>2</i>
          <strong>选择授权方式</strong>
        </div>
        <div class="mode-cards">
          <button
            type="button"
            :class="['mode-card', { active: pickerMode === 'COMMUNITY' }]"
            :disabled="!pickerCityId"
            @click="selectPickerMode('COMMUNITY')"
          >
            <span class="mode-icon"><Building2 :size="16" /></span>
            <span>
              <strong>指定社区/院校</strong>
              <em>精准勾选当前区划下的一个或多个社区、院校</em>
            </span>
            <span class="mode-radio" />
          </button>
          <button
            type="button"
            :class="['mode-card', { active: pickerMode === 'REGION' }]"
            :disabled="!pickerProvinceId"
            @click="selectPickerMode('REGION')"
          >
            <span class="mode-icon"><MapPinned :size="16" /></span>
            <span>
              <strong>整个区划</strong>
              <em>授予所选区划下全部社区，后续新增社区自动覆盖</em>
            </span>
            <span class="mode-radio" />
          </button>
        </div>
      </section>

      <section v-if="pickerMode === 'COMMUNITY'" class="drawer-step">
        <div class="step-head">
          <i>3</i>
          <strong>选择社区/院校</strong>
          <em v-if="pickerTotal">共 {{ pickerTotal }} 个</em>
        </div>

        <div v-if="!pickerCityId" class="picker-empty">请先选择到地市或更细区划，再勾选社区/院校</div>
        <template v-else>
          <div class="picker-search-row">
            <div class="picker-search">
              <Search :size="15" />
              <input
                v-model="pickerKeyword"
                aria-label="搜索社区或院校"
                placeholder="搜索社区名称、编码或地址…"
                @input="onPickerSearchInput"
                @keyup.enter="loadPickerCommunities(true)"
              />
            </div>
            <button type="button" class="select-all" @click="toggleAllVisibleCommunities">
              {{ pickerAllVisibleSelected ? '取消全选' : '全选当前结果' }}
            </button>
          </div>

          <div v-if="pickerSelectedCount" class="picker-selected-summary">
            <div class="picker-selected-head">
              <span>已选 <strong>{{ pickerSelectedCount }}</strong> 个社区/院校</span>
              <button type="button" @click="clearPickerSelection">清空选择</button>
            </div>
            <div class="picker-selected-chips">
              <span v-for="community in pickerSelectedList" :key="community.id" class="picker-selected-chip">
                {{ community.name }}
                <button type="button" :aria-label="`移除 ${community.name}`" @click="removePickerCommunity(community.id)">
                  <X :size="11" />
                </button>
              </span>
            </div>
          </div>

          <div class="picker-community-list">
            <button
              v-for="community in pickerCommunities"
              :key="community.id"
              type="button"
              :class="['picker-community-option', { selected: Boolean(pickerSelected[String(community.id)]) }]"
              @click="togglePickerCommunity(community)"
            >
              <span class="picker-check">
                <Check v-if="pickerSelected[String(community.id)]" :size="11" />
              </span>
              <span class="picker-community-main">
                <strong>
                  {{ community.name }}
                  <em v-if="community.type">{{ community.type }}</em>
                </strong>
                <span>{{ [community.code, community.address].filter(Boolean).join(' · ') || '暂无编码与地址' }}</span>
              </span>
              <span class="picker-community-households">
                {{ Number(community.households || 0).toLocaleString() }} 户
              </span>
            </button>

            <div v-if="pickerLoading" class="picker-loading">
              <RefreshCw :size="14" class="spinning" />正在检索社区…
            </div>
            <div v-else-if="!pickerCommunities.length" class="picker-empty">该区划下暂无可选社区</div>
            <button
              v-if="pickerHasMore && !pickerLoading"
              type="button"
              class="picker-load-more"
              @click="loadMoreCommunities"
            >
              加载更多（已显示 {{ pickerCommunities.length }} / {{ pickerTotal }}）
            </button>
          </div>
        </template>
      </section>

      <section v-else class="drawer-step">
        <div class="step-head">
          <i>3</i>
          <strong>确认授权范围</strong>
        </div>
        <div v-if="pickerRegionPath.length" class="region-preview">
          <span class="region-preview-icon"><MapPinned :size="17" /></span>
          <div>
            <strong>{{ pickerRegionPath.join(' / ') }}</strong>
            <p>将授予该{{ levelLabel(pickerLevel) }}下全部社区与院校的管理权限；后续新增社区自动纳入。</p>
          </div>
        </div>
        <div v-else class="picker-empty">请先选择省份/直辖市</div>
      </section>
    </div>

    <template #footer>
      <span class="grant-drawer-total">
        本次将添加
        <strong>{{ pickerMode === 'REGION' ? '整个区划' : `${pickerSelectedCount} 个社区` }}</strong>
      </span>
      <button type="button" @click="closeGrantDrawer">取消</button>
      <button type="button" class="primary-button" :disabled="!pickerValid || scopeSaving" @click="submitGrant">
        {{ scopeSaving ? '保存中…' : '添加管理范围' }}
      </button>
    </template>
  </NiDrawer>
</template>

<style scoped>
.community-admins-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.admin-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; }
.admin-heading h1 { margin: 0; color: #2c2838; font-size: var(--font-size-page-title); font-weight: 700; letter-spacing: -.03em; }
.admin-subtitle { margin: 6px 0 0; color: #8d8997; font-size: var(--font-size-body); }
.admin-heading-side { display: flex; align-items: center; gap: 20px; flex: 0 0 auto; }
.admin-stat { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
.admin-stat strong { color: #37333f; font-size: var(--font-size-heading); line-height: 1.1; }
.admin-stat span { color: #9a95a1; font-size: var(--font-size-caption); }
.admin-refresh {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid #e3e0e8;
  border-radius: 9px;
  color: #6f59d4;
  background: #fff;
}
.admin-refresh:hover { border-color: #c9bce9; background: #faf8ff; }
.admin-refresh:disabled { opacity: .5; cursor: not-allowed; }

.admin-guidance {
  min-height: 46px;
  padding: 9px 13px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid #e2dcf7;
  border-radius: 11px;
  background: #f6f3fe;
}
.guidance-icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 8px;
  color: #6f59d4;
  background: #fff;
}
.admin-guidance p { margin: 0; flex: 1; color: #7b7590; font-size: var(--font-size-caption); line-height: 1.55; }
.admin-guidance p strong { color: #554b78; font-weight: 600; }

.admin-workspace {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: 328px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #e6e3eb;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 4px 16px rgba(40, 35, 58, .03);
}

.admin-list-panel {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e8e5ec;
  background: #fbfafd;
}
.admin-list-head {
  min-height: 58px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid #ebe8ef;
}
.admin-list-head strong { display: block; color: #403c48; font-size: var(--font-size-body); font-weight: 600; }
.admin-list-head span { display: block; margin-top: 2px; color: #9e9aa6; font-size: var(--font-size-caption); }
.admin-list-head > svg { color: #6f59d4; }
.admin-search {
  height: 34px;
  margin: 10px 10px 6px;
  padding: 0 10px;
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid #e3e0e7;
  border-radius: 8px;
  color: #9d99a5;
  background: #fff;
}
.admin-search input { flex: 1; min-width: 0; border: 0; background: transparent; color: #504c58; font-size: var(--font-size-body); }
.admin-search input::placeholder { color: #aaa6b1; }
.admin-filter-tabs { display: flex; gap: 4px; padding: 0 10px 8px; }
.admin-filter-tabs button { height: 28px; padding: 0 8px; border-radius: 7px; color: #898591; font-size: var(--font-size-caption); }
.admin-filter-tabs button:hover { background: #f1eef7; }
.admin-filter-tabs button.active { color: #5f4abd; background: #eeeafd; font-weight: 600; }
.admin-filter-tabs em { margin-left: 3px; font-style: normal; opacity: .68; }

.admin-list { flex: 1; min-height: 0; padding: 4px 8px 10px; overflow-y: auto; }
.admin-list-item {
  width: 100%;
  padding: 10px 9px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid transparent;
  border-radius: 10px;
  text-align: left;
}
.admin-list-item:hover { background: #f4f1fb; }
.admin-list-item.active { border-color: #ddd4f5; background: #fff; box-shadow: 0 4px 12px rgba(77, 58, 143, .07); }
.admin-avatar {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 9px;
  color: #5f4abd;
  background: #eeeafd;
  font-size: 13px;
  font-weight: 700;
}
.admin-avatar.super { color: #fff; background: linear-gradient(135deg, #6f59d4, #8f7ae3); }
.admin-avatar.disabled { color: #8f8a97; background: #efedf1; }
.admin-item-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.admin-item-name { display: flex; align-items: center; gap: 5px; min-width: 0; }
.admin-item-name strong {
  overflow: hidden;
  color: #403c48;
  font-size: var(--font-size-body);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.admin-item-name em { flex: 0 0 auto; padding: 1px 5px; border-radius: 5px; font-size: 10px; font-style: normal; }
.tag-super { color: #5f4abd; background: #ece7fb; }
.tag-resident { color: #3b76ad; background: #e9f2fb; }
.tag-disabled { color: #a8646a; background: #fcebed; }
.admin-item-sub {
  overflow: hidden;
  color: #9a95a1;
  font-size: var(--font-size-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.admin-item-scope { display: flex; align-items: center; gap: 5px; color: #776f8e; font-size: 11px; }
.admin-item-scope::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: #6f59d4; opacity: .55; }
.admin-item-scope.empty { color: #b0abb8; }
.admin-item-scope.empty::before { background: #cbc6d2; }
.admin-item-chevron { flex: 0 0 auto; color: #b5b0bc; }
.admin-list-item.active .admin-item-chevron { color: #6f59d4; }
.admin-list-loading { padding: 24px 12px; display: flex; align-items: center; justify-content: center; gap: 7px; color: #9a95a1; font-size: var(--font-size-caption); }

.scope-panel { min-width: 0; min-height: 0; display: flex; flex-direction: column; background: #fff; }
.scope-header {
  min-height: 76px;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-bottom: 1px solid #ebe8ef;
}
.scope-user { display: flex; align-items: center; gap: 11px; min-width: 0; }
.scope-user > div { min-width: 0; }
.scope-avatar {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 11px;
  color: #fff;
  background: linear-gradient(135deg, #6f59d4, #8d78e0);
  font-size: 15px;
  font-weight: 700;
}
.scope-user h2 { margin: 0; display: flex; align-items: center; gap: 7px; color: #37333f; font-size: var(--font-size-title); font-weight: 600; }
.scope-username { color: #aaa6b1; font-size: var(--font-size-caption); font-weight: 400; }
.scope-user p { margin: 4px 0 0; display: flex; align-items: center; gap: 7px; flex-wrap: wrap; color: #918d99; font-size: var(--font-size-caption); }
.scope-role { padding-left: 7px; border-left: 1px solid #e6e3e9; }
.scope-super { color: #6f59d4; }
.scope-actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.scope-actions .primary-button { height: 36px; padding: 0 13px; }
.scope-clear {
  height: 36px;
  padding: 0 11px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #e3e0e8;
  border-radius: 8px;
  color: #7a7582;
  background: #fff;
  font-size: var(--font-size-body);
}
.scope-clear:hover { color: #c9525e; border-color: #efcdd1; background: #fdf6f7; }
.scope-clear:disabled { opacity: .45; cursor: not-allowed; }
.scope-readonly {
  padding: 9px 16px;
  display: flex;
  align-items: center;
  gap: 7px;
  border-bottom: 1px solid #f0e2cf;
  color: #9a6a2f;
  background: #fdf6ea;
  font-size: var(--font-size-caption);
}

.scope-coverage {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  padding: 0 16px;
  border-bottom: 1px solid #ebe8ef;
  background: #fcfbfd;
}
.scope-coverage > div { padding: 10px 8px; display: flex; flex-direction: column; gap: 1px; }
.scope-coverage > div + div { border-left: 1px solid #eeebf2; }
.scope-coverage span { color: #9a95a1; font-size: var(--font-size-caption); }
.scope-coverage strong { color: #4d4858; font-size: var(--font-size-title); font-weight: 600; }
.scope-coverage .accent strong { color: #6f59d4; }

.scope-toolbar {
  min-height: 52px;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid #f0edf3;
}
.scope-search {
  width: 260px;
  height: 34px;
  padding: 0 9px;
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid #e5e2e9;
  border-radius: 8px;
  color: #a19daa;
}
.scope-search input { width: 100%; border: 0; background: transparent; color: #514d58; font-size: var(--font-size-body); }
.scope-search input::placeholder { color: #aaa6b1; }
.scope-legend { display: flex; align-items: center; gap: 13px; color: #8f8a97; font-size: var(--font-size-caption); }
.scope-legend span { display: inline-flex; align-items: center; gap: 5px; }
.scope-legend i { width: 7px; height: 7px; border-radius: 2px; }
.scope-legend .region i { background: #6f59d4; }
.scope-legend .community i { background: #5b8dcc; }

.scope-list { flex: 1; min-height: 0; padding: 12px 16px 18px; overflow-y: auto; background: #fff; }
.scope-loading { height: 100%; display: flex; align-items: center; justify-content: center; gap: 8px; color: #9a95a1; font-size: var(--font-size-body); }
.grant-group + .grant-group { margin-top: 14px; }
.grant-group-head { width: 100%; padding: 4px 0 8px; display: flex; align-items: center; gap: 7px; text-align: left; }
.grant-group-head > svg { color: #a19daa; }
.group-pin { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 6px; color: #6f59d4; background: #f1edfc; }
.grant-group-head strong { color: #4a4552; font-size: var(--font-size-body); font-weight: 600; }
.grant-group-meta { color: #a19daa; font-size: var(--font-size-caption); }
.grant-group-line { flex: 1; height: 1px; margin-left: 4px; background: #efecf3; }
.grant-group-body { display: flex; flex-direction: column; gap: 8px; }

.grant-card {
  padding: 11px 13px;
  display: flex;
  align-items: flex-start;
  gap: 11px;
  border: 1px solid #eae7ef;
  border-radius: 11px;
  background: #fff;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.grant-card:hover { border-color: #dcd3f3; box-shadow: 0 4px 14px rgba(70, 53, 135, .06); }
.grant-icon { width: 34px; height: 34px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 9px; }
.grant-card.region .grant-icon { color: #6f59d4; background: #f1edfc; }
.grant-card.community .grant-icon { color: #4f82c4; background: #eaf2fb; }
.grant-body { flex: 1; min-width: 0; }
.grant-title-line { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.grant-title-line strong { color: #403c48; font-size: var(--font-size-body); font-weight: 600; }
.grant-type { padding: 2px 7px; border-radius: 5px; font-size: 10px; }
.grant-type.region { color: #5f4abd; background: #ece7fb; }
.grant-type.community { color: #3b76ad; background: #e9f2fb; }
.grant-level { color: #aaa6b1; font-size: var(--font-size-caption); }
.grant-note { margin: 5px 0 0; color: #8f8a97; font-size: var(--font-size-caption); }
.community-chip-row { margin-top: 7px; display: flex; flex-wrap: wrap; gap: 5px; }
.community-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border-radius: 6px;
  color: #5d6572;
  background: #f4f5f8;
  font-size: 11px;
}
.community-chip svg { color: #7a93b4; flex: 0 0 auto; }
.community-chip em { color: #a19daa; font-size: 10px; font-style: normal; }
.grant-time { display: block; margin-top: 6px; color: #b1adb8; font-size: 11px; }
.grant-side { flex: 0 0 auto; display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
.grant-side strong { color: #4a4552; font-size: var(--font-size-title); font-weight: 600; }
.grant-side span { color: #a19daa; font-size: 11px; }
.grant-remove { width: 28px; height: 28px; margin-top: 6px; display: grid; place-items: center; border-radius: 7px; color: #b7b2bd; background: transparent; }
.grant-remove:hover { color: #c9525e; background: #fdf2f3; }
.grant-remove:disabled { opacity: .4; cursor: not-allowed; }

.grant-drawer { display: flex; flex-direction: column; gap: 20px; }
.grant-target {
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid #e6e1ef;
  border-radius: 9px;
  background: #faf8ff;
}
.target-avatar {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 8px;
  color: #fff;
  background: linear-gradient(135deg, #6f59d4, #8d78e0);
  font-size: 12px;
  font-weight: 700;
}
.grant-target strong { display: block; color: #4a4552; font-size: var(--font-size-body); font-weight: 600; }
.grant-target span { display: block; margin-top: 2px; color: #8f8799; font-size: var(--font-size-caption); line-height: 1.5; }

.drawer-step { display: flex; flex-direction: column; }
.step-head { margin-bottom: 8px; display: flex; align-items: center; gap: 7px; }
.step-head i {
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
.step-head strong { color: #4a4552; font-size: var(--font-size-body); font-weight: 600; }
.step-head em { margin-left: auto; color: #9a95a1; font-size: var(--font-size-caption); font-style: normal; }
.step-head button { margin-left: auto; color: #6f59d4; font-size: var(--font-size-caption); }

.region-cascade { display: flex; align-items: flex-end; gap: 6px; flex-wrap: wrap; }
.region-cascade label { flex: 1 1 130px; min-width: 0; }
.region-cascade label > span { display: block; margin-bottom: 4px; color: #8f8a97; font-size: 11px; }
.region-cascade select {
  width: 100%;
  height: 34px;
  padding: 0 8px;
  border: 1px solid #e1dee5;
  border-radius: 8px;
  color: #514d58;
  background: #fff;
  font-size: var(--font-size-body);
}
.region-cascade select:disabled { color: #b1adb8; background: #f8f7fa; }
.region-cascade-arrow { flex: 0 0 auto; margin-bottom: 9px; color: #b3aec0; }
.region-path-preview {
  margin-top: 9px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  gap: 7px;
  border-radius: 8px;
  color: #6f59d4;
  background: #f7f4fe;
  font-size: var(--font-size-caption);
}
.region-path-preview span { flex: 1; color: #5b4a9a; }
.region-path-preview em { padding: 1px 6px; border-radius: 5px; color: #7a6bb0; background: #ece7fb; font-style: normal; }
.region-error { margin: 8px 0 0; color: #b06a6a; font-size: var(--font-size-caption); }
.region-error button { margin-left: 6px; color: #6f59d4; font-size: var(--font-size-caption); }

.mode-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.mode-card {
  padding: 11px 12px;
  display: flex;
  align-items: flex-start;
  gap: 9px;
  border: 1px solid #e6e3e9;
  border-radius: 9px;
  background: #fff;
  text-align: left;
}
.mode-card:hover:not(:disabled) { border-color: #cfc5ef; background: #fbfaff; }
.mode-card.active { border-color: #b7a7ea; background: #f7f4ff; box-shadow: 0 0 0 2px rgba(111, 89, 212, .07); }
.mode-card:disabled { opacity: .5; cursor: not-allowed; }
.mode-icon { width: 30px; height: 30px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 8px; color: #6f59d4; background: #f1edfc; }
.mode-card.active .mode-icon { color: #fff; background: #6f59d4; }
.mode-card > span:nth-child(2) { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.mode-card strong { color: #4a4552; font-size: var(--font-size-body); font-weight: 600; }
.mode-card em { color: #9a95a1; font-size: 11px; font-style: normal; line-height: 1.5; }
.mode-radio { width: 15px; height: 15px; flex: 0 0 auto; margin-top: 2px; border: 1.5px solid #cfc8db; border-radius: 50%; background: #fff; }
.mode-card.active .mode-radio { border-color: #6f59d4; background: radial-gradient(circle, #6f59d4 0 4px, #fff 4.5px 100%); }

.picker-search-row { display: flex; align-items: center; gap: 8px; }
.picker-search {
  flex: 1;
  height: 34px;
  padding: 0 9px;
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid #e3e0e7;
  border-radius: 8px;
  color: #9d99a5;
}
.picker-search input { flex: 1; min-width: 0; border: 0; background: transparent; color: #514d58; font-size: var(--font-size-body); }
.picker-search input::placeholder { color: #aaa6b1; }
.select-all {
  flex: 0 0 auto;
  height: 34px;
  padding: 0 10px;
  border: 1px solid #ded8ee;
  border-radius: 8px;
  color: #6750c4;
  background: #fff;
  font-size: var(--font-size-caption);
}
.select-all:hover { background: #f8f5fe; }
.picker-selected-summary { margin-top: 8px; padding: 8px 10px; border: 1px solid #ddd5f5; border-radius: 8px; background: #faf8ff; }
.picker-selected-head { display: flex; align-items: center; gap: 8px; color: #6f6a79; font-size: var(--font-size-caption); }
.picker-selected-head strong { color: #5f4abd; font-size: var(--font-size-body); }
.picker-selected-head button { margin-left: auto; color: #8f8a97; font-size: var(--font-size-caption); }
.picker-selected-head button:hover { color: #c9525e; }
.picker-selected-chips { max-height: 70px; margin-top: 6px; display: flex; flex-wrap: wrap; gap: 5px; overflow-y: auto; }
.picker-selected-chip { display: inline-flex; align-items: center; gap: 3px; padding: 2px 5px 2px 7px; border-radius: 6px; color: #5f4abd; background: #ece7fb; font-size: 11px; }
.picker-selected-chip button { width: 15px; height: 15px; display: grid; place-items: center; border-radius: 4px; color: #8b79c7; }
.picker-selected-chip button:hover { color: #fff; background: #8b79c7; }

.picker-community-list { margin-top: 8px; max-height: 260px; overflow-y: auto; border: 1px solid #ece9f0; border-radius: 9px; }
.picker-community-option { width: 100%; padding: 8px 10px; display: flex; align-items: center; gap: 9px; border-bottom: 1px solid #f4f2f6; text-align: left; }
.picker-community-option:hover { background: #faf8ff; }
.picker-community-option.selected { background: #f6f2ff; }
.picker-check { width: 16px; height: 16px; flex: 0 0 auto; display: grid; place-items: center; border: 1.5px solid #cfc8db; border-radius: 5px; color: #fff; background: #fff; }
.picker-community-option.selected .picker-check { border-color: #6f59d4; background: #6f59d4; }
.picker-community-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.picker-community-main strong { display: flex; align-items: center; gap: 6px; color: #3f3b46; font-size: var(--font-size-body); font-weight: 600; }
.picker-community-main strong em { padding: 1px 5px; border-radius: 4px; color: #7d7790; background: #f2f0f6; font-size: 10px; font-style: normal; font-weight: 400; }
.picker-community-main > span { overflow: hidden; color: #9a95a1; font-size: var(--font-size-caption); text-overflow: ellipsis; white-space: nowrap; }
.picker-community-households { flex: 0 0 auto; color: #a19daa; font-size: var(--font-size-caption); }
.picker-loading, .picker-empty { padding: 20px 12px; display: flex; align-items: center; justify-content: center; gap: 6px; color: #aaa6b1; font-size: var(--font-size-caption); text-align: center; }
.picker-load-more { width: 100%; height: 36px; color: #6f59d4; background: #fbfaff; font-size: var(--font-size-caption); }
.picker-load-more:hover { background: #f5f1ff; }

.region-preview { padding: 12px 13px; display: flex; align-items: flex-start; gap: 10px; border: 1px solid #ded6f5; border-radius: 10px; background: #faf8ff; }
.region-preview-icon { width: 34px; height: 34px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 9px; color: #6f59d4; background: #fff; }
.region-preview strong { display: block; color: #4a4552; font-size: var(--font-size-body); font-weight: 600; }
.region-preview p { margin: 3px 0 0; color: #8f8799; font-size: var(--font-size-caption); line-height: 1.6; }

.grant-drawer-total { margin-right: auto; display: inline-flex; align-items: center; gap: 5px; color: #8f8a97; font-size: var(--font-size-caption); }
.grant-drawer-total strong { color: #5f4abd; font-size: var(--font-size-body); }

@media (max-width: 1180px) {
  .admin-workspace { grid-template-columns: 290px minmax(0, 1fr); }
  .admin-heading-side { gap: 13px; }
}

@media (max-width: 960px) {
  .community-admins-page { height: auto; min-height: 0; }
  .admin-heading { align-items: flex-start; flex-direction: column; gap: 10px; }
  .admin-heading-side { width: 100%; }
  .admin-refresh { margin-left: auto; }
  .admin-workspace { display: flex; flex-direction: column; overflow: visible; }
  .admin-list-panel { height: 340px; flex: 0 0 340px; border-right: 0; border-bottom: 1px solid #e8e5ec; }
  .scope-panel { min-height: 480px; }
  .scope-list { overflow: visible; }
  .mode-cards { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .admin-heading-side { flex-wrap: wrap; }
  .admin-stat { align-items: flex-start; }
  .scope-header { align-items: flex-start; flex-direction: column; }
  .scope-actions { width: 100%; }
  .scope-actions .primary-button { flex: 1; justify-content: center; }
  .scope-coverage { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .scope-coverage > div:nth-child(4) { border-left: 0; border-top: 1px solid #eeebf2; }
  .scope-coverage > div:nth-child(5) { border-top: 1px solid #eeebf2; }
  .scope-toolbar { align-items: stretch; flex-direction: column; }
  .scope-search { width: 100%; }
  .scope-legend { justify-content: flex-start; }
  .region-cascade label { flex: 1 1 calc(50% - 10px); }
  .region-cascade-arrow { display: none; }
  .picker-search-row { align-items: stretch; flex-direction: column; }
  .select-all { width: 100%; }
  .picker-community-households { display: none; }
}
</style>
