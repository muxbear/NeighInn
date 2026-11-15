<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Building2, ChevronDown, ChevronRight, Filter, Home, MapPin, Plus, Search, Settings2, ShieldCheck, Trash2, UserRound, Users, X } from 'lucide-vue-next'
import { communityApi, residentApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import { groupProvinces, indexRegions, type RegionEntry, type RegionNode } from '@/utils/region'

const app = useAppStore()
const auth = useAuthStore()
const rows = ref<any[]>([])
const summary = ref<any>({ total: 0, owner: 0, family: 0, pending: 0 })
const activeTab = ref('全部人员')
const query = ref('')
const page = ref(1)
const total = ref(0)
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

// 社区选择：与社区运维一致，按“省 → 市 → 区县 → 街道 → 社区”逐级定位。
const pickerRoot = ref<HTMLElement | null>(null)
const pickerOpen = ref(false)
const pickerLoading = ref(false)
const pickerError = ref('')
const regionRoots = ref<RegionNode[]>([])
const regionIndex = ref<Record<string, RegionEntry>>({})
const pickerProvinceId = ref('')
const pickerCityId = ref('')
const pickerDistrictId = ref('')
const pickerStreetId = ref('')
const pickerCommunities = ref<any[]>([])
const pickerCommunitiesLoading = ref(false)
const pickerSearch = ref('')
const pickerSearching = ref(false)
const pickerSearchResults = ref<any[]>([])
let regionTreePromise: Promise<void> | null = null
let searchTimer: number | undefined
let searchRequestId = 0
let communitiesRequestId = 0

const pickerProvinceGroups = computed(() => groupProvinces(regionRoots.value))
const pickerProvince = computed(() => regionIndex.value[pickerProvinceId.value]?.node ?? null)
const pickerCityNodes = computed<RegionNode[]>(() => pickerProvince.value?.children || [])
const pickerDistrictNodes = computed<RegionNode[]>(() => regionIndex.value[pickerCityId.value]?.node.children || [])
const pickerStreetNodes = computed<RegionNode[]>(() => regionIndex.value[pickerDistrictId.value]?.node.children || [])
const pickerPathLabel = computed(() => {
  const entry = pickerSelectionEntry()
  if (!entry) return '请选择最末级社区后应用'
  return [...entry.ancestors.map((node) => node.name), entry.node.name].join(' / ')
})
const currentCommunityPath = computed(() => {
  const row = community.value
  if (!row) return '按行政区划选择社区'
  return communityPath(row) || row.address || '按行政区划选择社区'
})

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

function pickerSelectionEntry(): RegionEntry | null {
  const ids = [pickerStreetId.value, pickerDistrictId.value, pickerCityId.value, pickerProvinceId.value]
  for (const id of ids) {
    const entry = id ? regionIndex.value[id] : undefined
    if (entry) return entry
  }
  return null
}

/** 根据社区档案的区县 / 街道反查完整行政区划路径。 */
function communityPath(row: any): string {
  const district = row?.regionId ? regionIndex.value[String(row.regionId)] : undefined
  if (!district) return row?.address || ''
  const names = [...district.ancestors.map((node) => node.name), district.node.name]
  const street = row?.streetId ? regionIndex.value[String(row.streetId)] : undefined
  if (street && street.parentId === String(district.node.id)) names.push(street.node.name)
  return names.join(' / ')
}

function ensureRegionTree(): Promise<void> {
  if (regionRoots.value.length) return Promise.resolve()
  if (regionTreePromise) return regionTreePromise
  pickerLoading.value = true
  pickerError.value = ''
  regionTreePromise = communityApi.regionTree()
    .then((roots) => {
      regionRoots.value = roots as RegionNode[]
      regionIndex.value = indexRegions(roots as RegionNode[])
    })
    .catch((exc: any) => {
      pickerError.value = exc?.message || '行政区划加载失败'
    })
    .finally(() => {
      pickerLoading.value = false
      regionTreePromise = null
    })
  return regionTreePromise
}

function initPickerSelection() {
  const row = community.value
  const district = row?.regionId ? regionIndex.value[String(row.regionId)] : undefined
  if (district && district.node.level === 'DISTRICT') {
    pickerProvinceId.value = district.ancestors[0] ? String(district.ancestors[0].id) : ''
    pickerCityId.value = district.ancestors[1] ? String(district.ancestors[1].id) : ''
    pickerDistrictId.value = String(district.node.id)
    const street = row?.streetId ? regionIndex.value[String(row.streetId)] : undefined
    pickerStreetId.value = street && street.parentId === pickerDistrictId.value ? String(street.node.id) : ''
    loadPickerCommunities()
    return
  }
  // 社区未关联区划或区划未收录时，默认落到第一个省份 / 地市 / 区县，保证列表可用。
  const firstProvince = pickerProvinceGroups.value[0]?.provinces[0]
  pickerProvinceId.value = firstProvince ? String(firstProvince.id) : ''
  const firstCity = firstProvince?.children?.[0]
  pickerCityId.value = firstCity ? String(firstCity.id) : ''
  const firstDistrict = firstCity?.children?.[0]
  pickerDistrictId.value = firstDistrict ? String(firstDistrict.id) : ''
  pickerStreetId.value = ''
  if (firstDistrict) loadPickerCommunities()
}

function syncPickerSelection(row: any) {
  const district = row?.regionId ? regionIndex.value[String(row.regionId)] : undefined
  if (!district || district.node.level !== 'DISTRICT') return
  pickerProvinceId.value = district.ancestors[0] ? String(district.ancestors[0].id) : ''
  pickerCityId.value = district.ancestors[1] ? String(district.ancestors[1].id) : ''
  pickerDistrictId.value = String(district.node.id)
  const street = row?.streetId ? regionIndex.value[String(row.streetId)] : undefined
  pickerStreetId.value = street && street.parentId === pickerDistrictId.value ? String(street.node.id) : ''
}

/** 逐级定位时把已选节点滚动到所在列的可见区域。 */
function revealSelectedRegions() {
  nextTick(() => {
    const bodies = pickerRoot.value?.querySelectorAll<HTMLElement>('.community-picker-column-body')
    bodies?.forEach((body) => {
      const item = body.querySelector<HTMLElement>('.community-picker-item.selected, .community-picker-community.current')
      if (!item) return
      const bodyRect = body.getBoundingClientRect()
      const itemRect = item.getBoundingClientRect()
      if (itemRect.top < bodyRect.top) body.scrollTop -= bodyRect.top - itemRect.top
      else if (itemRect.bottom > bodyRect.bottom) body.scrollTop += itemRect.bottom - bodyRect.bottom
    })
  })
}

async function togglePicker() {
  if (pickerOpen.value) {
    closePicker()
    return
  }
  pickerOpen.value = true
  pickerSearch.value = ''
  pickerSearchResults.value = []
  await ensureRegionTree()
  if (!pickerOpen.value || !regionRoots.value.length) return
  if (!pickerProvinceId.value) initPickerSelection()
  revealSelectedRegions()
}

function closePicker() {
  if (!pickerOpen.value) return
  pickerOpen.value = false
  clearPickerSearch()
}

async function loadPickerCommunities() {
  if (!pickerDistrictId.value) {
    pickerCommunities.value = []
    return
  }
  const requestId = ++communitiesRequestId
  pickerCommunitiesLoading.value = true
  try {
    const params: Record<string, any> = { regionId: pickerDistrictId.value, page: 1, pageSize: 50 }
    if (pickerStreetId.value) params.streetId = pickerStreetId.value
    const data = await communityApi.list(params)
    if (requestId !== communitiesRequestId) return
    pickerCommunities.value = data.items || []
    revealSelectedRegions()
  } catch (exc: any) {
    if (requestId === communitiesRequestId) {
      pickerCommunities.value = []
      app.showToast(exc?.message || '社区列表加载失败')
    }
  } finally {
    if (requestId === communitiesRequestId) pickerCommunitiesLoading.value = false
  }
}

function selectPickerProvince(province: RegionNode) {
  const id = String(province.id)
  if (id === pickerProvinceId.value) return
  pickerProvinceId.value = id
  pickerCityId.value = ''
  pickerDistrictId.value = ''
  pickerStreetId.value = ''
  pickerCommunities.value = []
}

function selectPickerCity(city: RegionNode) {
  const id = String(city.id)
  if (id === pickerCityId.value) return
  pickerCityId.value = id
  pickerDistrictId.value = ''
  pickerStreetId.value = ''
  pickerCommunities.value = []
}

function selectPickerDistrict(district: RegionNode) {
  const id = String(district.id)
  if (id === pickerDistrictId.value) return
  pickerDistrictId.value = id
  pickerStreetId.value = ''
  loadPickerCommunities()
}

function selectPickerStreet(streetId: string) {
  if (streetId === pickerStreetId.value) return
  pickerStreetId.value = streetId
  loadPickerCommunities()
}

function applyCommunity(row: any) {
  const id = Number(row.id)
  syncPickerSelection(row)
  loadPickerCommunities()
  pickerOpen.value = false
  clearPickerSearch()
  // 与社区运维一致：切换社区后重置身份页签与列表搜索。
  activeTab.value = '全部人员'
  query.value = ''
  page.value = 1
  if (id !== app.currentCommunityId) app.switchCommunity(id)
  else load()
}

function onPickerSearchInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  const keyword = pickerSearch.value.trim()
  if (!keyword) {
    searchRequestId += 1
    pickerSearching.value = false
    pickerSearchResults.value = []
    return
  }
  pickerSearching.value = true
  searchTimer = window.setTimeout(() => runPickerSearch(keyword), 250)
}

async function runPickerSearch(keyword: string) {
  const requestId = ++searchRequestId
  try {
    const results = await communityApi.search(keyword)
    if (requestId !== searchRequestId) return
    pickerSearchResults.value = Array.isArray(results) ? results : []
  } catch (exc: any) {
    if (requestId === searchRequestId) {
      pickerSearchResults.value = []
      app.showToast(exc?.message || '社区搜索失败')
    }
  } finally {
    if (requestId === searchRequestId) pickerSearching.value = false
  }
}

function clearPickerSearch() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchRequestId += 1
  pickerSearch.value = ''
  pickerSearchResults.value = []
  pickerSearching.value = false
}

function onDocumentClick(event: MouseEvent) {
  if (!pickerOpen.value) return
  if (pickerRoot.value && !pickerRoot.value.contains(event.target as Node)) closePicker()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closePicker()
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

onMounted(() => {
  load()
  document.addEventListener('click', onDocumentClick)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  window.removeEventListener('keydown', onKeydown)
  if (searchTimer) window.clearTimeout(searchTimer)
})

watch(() => app.currentCommunityId, () => { page.value = 1; load() })
</script>

<template>
  <section ref="pickerRoot" class="community-selector-card">
    <div class="community-selector-icon"><Building2 :size="21" /></div>
    <div><span>选择需要管理的社区</span><strong>当前社区人员档案</strong></div>
    <button :class="['community-selector-trigger', { active: pickerOpen }]" @click="togglePicker">
      <MapPin :size="16" />
      <span><strong>{{ community?.name || '选择社区' }}</strong><em>{{ currentCommunityPath }}</em></span>
      <ChevronDown :size="15" />
    </button>
    <div class="community-selector-meta"><span>社区类型</span><strong>{{ community?.type || '商品房社区' }}</strong></div>
    <div class="community-selector-meta"><span>社区编码</span><strong>{{ community?.code || '—' }}</strong></div>

    <div v-if="pickerOpen" class="community-picker">
      <div class="community-picker-head">
        <div>
          <strong>选择社区</strong>
          <span>按行政区划逐级定位，或直接搜索社区</span>
        </div>
        <button class="community-picker-close" aria-label="关闭社区选择" @click="closePicker"><X :size="16" /></button>
      </div>

      <div class="community-picker-search">
        <Search :size="16" />
        <input v-model="pickerSearch" placeholder="搜索社区名称、编码或完整地址" @input="onPickerSearchInput" />
        <button v-if="pickerSearch" class="community-picker-search-clear" aria-label="清空搜索" @click="clearPickerSearch"><X :size="14" /></button>
      </div>

      <div v-if="pickerSearch.trim()" class="community-picker-results">
        <div class="community-picker-results-meta">{{ pickerSearching ? '正在搜索…' : `找到 ${pickerSearchResults.length} 个匹配社区` }}</div>
        <button v-for="row in pickerSearchResults" :key="row.id" :class="['community-picker-result', { current: Number(row.id) === app.currentCommunityId }]" @click="applyCommunity(row)">
          <span class="community-picker-result-icon"><Home :size="15" /></span>
          <span class="community-picker-result-main">
            <strong>{{ row.name }}</strong>
            <em>{{ communityPath(row) || row.address || '未收录行政区划' }}</em>
          </span>
          <code>{{ row.code }}</code>
          <ChevronRight :size="14" />
        </button>
        <div v-if="!pickerSearching && !pickerSearchResults.length" class="community-picker-empty">未找到匹配社区，请调整关键词</div>
      </div>

      <div v-else class="community-picker-columns">
        <div class="community-picker-column">
          <span class="community-picker-column-title">省 / 直辖市 / 自治区</span>
          <div class="community-picker-column-body">
            <div v-if="pickerLoading" class="community-picker-hint">正在加载全国行政区划…</div>
            <div v-else-if="pickerError" class="community-picker-hint">{{ pickerError }}</div>
            <template v-else>
              <template v-for="group in pickerProvinceGroups" :key="group.label">
                <em class="community-picker-group">{{ group.label }}</em>
                <button v-for="province in group.provinces" :key="province.id" :class="['community-picker-item', { selected: pickerProvinceId === String(province.id) }]" @click="selectPickerProvince(province)">{{ province.name }}</button>
              </template>
            </template>
          </div>
        </div>
        <div class="community-picker-column">
          <span class="community-picker-column-title">地市</span>
          <div class="community-picker-column-body">
            <button v-for="city in pickerCityNodes" :key="city.id" :class="['community-picker-item', { selected: pickerCityId === String(city.id) }]" @click="selectPickerCity(city)">{{ city.name }}</button>
            <div v-if="!pickerCityNodes.length" class="community-picker-hint">{{ pickerProvinceId ? '该省份暂无地市数据' : '请选择省份' }}</div>
          </div>
        </div>
        <div class="community-picker-column">
          <span class="community-picker-column-title">区县</span>
          <div class="community-picker-column-body">
            <button v-for="district in pickerDistrictNodes" :key="district.id" :class="['community-picker-item', { selected: pickerDistrictId === String(district.id) }]" @click="selectPickerDistrict(district)">{{ district.name }}</button>
            <div v-if="!pickerDistrictNodes.length" class="community-picker-hint">{{ pickerCityId ? '该地市暂无区县数据' : '请选择地市' }}</div>
          </div>
        </div>
        <div class="community-picker-column">
          <span class="community-picker-column-title">街道</span>
          <div class="community-picker-column-body">
            <button :class="['community-picker-item', { selected: !pickerStreetId }]" @click="selectPickerStreet('')">全部街道</button>
            <button v-for="street in pickerStreetNodes" :key="street.id" :class="['community-picker-item', { selected: pickerStreetId === String(street.id) }]" @click="selectPickerStreet(String(street.id))">{{ street.name }}</button>
            <div v-if="!pickerDistrictId" class="community-picker-hint">请选择区县</div>
            <div v-else-if="!pickerStreetNodes.length" class="community-picker-hint">该区县暂无街道数据，可选择全部街道</div>
          </div>
        </div>
        <div class="community-picker-column">
          <span class="community-picker-column-title">社区</span>
          <div class="community-picker-column-body">
            <div v-if="pickerCommunitiesLoading" class="community-picker-hint">正在加载社区…</div>
            <template v-else>
              <button v-for="row in pickerCommunities" :key="row.id" :class="['community-picker-community', { current: Number(row.id) === app.currentCommunityId }]" @click="applyCommunity(row)">
                <span class="community-picker-community-icon"><Home :size="14" /></span>
                <span class="community-picker-community-main"><strong>{{ row.name }}</strong><em>{{ row.address || row.code }}</em></span>
              </button>
              <div v-if="!pickerCommunities.length" class="community-picker-hint">{{ pickerDistrictId ? '该区划暂无社区' : '请选择区县' }}</div>
            </template>
          </div>
        </div>
      </div>

      <div class="community-picker-foot">
        <span>{{ pickerPathLabel }}</span>
        <button @click="closePicker">取消</button>
      </div>
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
