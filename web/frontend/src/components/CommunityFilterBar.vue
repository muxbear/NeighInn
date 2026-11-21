<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronRight, Home, MapPin, Search, X } from 'lucide-vue-next'
import { communityApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { groupProvinces, indexRegions, type RegionEntry, type RegionNode } from '@/utils/region'

withDefaults(defineProps<{
  /** 展示在小区名称右侧的状态说明，如“物品列表仅展示所选小区”。 */
  scopeNote?: string
}>(), {
  scopeNote: '列表仅展示所选小区',
})

const app = useAppStore()
const regionRoots = ref<RegionNode[]>([])
const regionIndex = ref<Record<string, RegionEntry>>({})
const regionLoading = ref(false)
const regionError = ref('')
const provinceId = ref('')
const cityId = ref('')
const districtId = ref('')
const streetId = ref('')
const selectedCommunityRow = ref<any | null>(null)
const communitySearch = ref('')
const communityResults = ref<any[]>([])
const communitySearching = ref(false)
const communityOptionsOpen = ref(false)
const communitySearchRoot = ref<HTMLElement | null>(null)
let regionTreePromise: Promise<void> | null = null
let communitySearchTimer: number | undefined
let communitySearchRequestId = 0
let selectedCommunityRequestId = 0

const provinceGroups = computed(() => groupProvinces(regionRoots.value))
const provinceNode = computed(() => (provinceId.value ? regionIndex.value[provinceId.value]?.node : undefined) ?? null)
const cityNodes = computed<RegionNode[]>(() => provinceNode.value?.children || [])
const districtNodes = computed<RegionNode[]>(() => (cityId.value ? regionIndex.value[cityId.value]?.node.children : undefined) || [])
const streetNodes = computed<RegionNode[]>(() => (districtId.value ? regionIndex.value[districtId.value]?.node.children : undefined) || [])
const selectedCommunityName = computed(() => selectedCommunityRow.value?.name || '')
const selectedCommunityPath = computed(() => {
  const row = selectedCommunityRow.value
  const district = row?.regionId ? regionIndex.value[String(row.regionId)] : undefined
  if (!district) return row?.address || ''
  const names = [...district.ancestors.map((node) => node.name), district.node.name]
  const street = row?.streetId ? regionIndex.value[String(row.streetId)] : undefined
  if (street && street.parentId === String(district.node.id)) names.push(street.node.name)
  return names.join(' / ')
})
const communitySearchHint = computed(() => {
  if (communitySearch.value.trim()) return '未找到匹配小区，请调整关键词或区划'
  if (districtId.value) return '该区划下暂无小区'
  return '请输入关键词检索小区'
})

function ensureRegionTree(): Promise<void> {
  if (regionRoots.value.length) return Promise.resolve()
  if (regionTreePromise) return regionTreePromise
  regionLoading.value = true
  regionError.value = ''
  regionTreePromise = communityApi.regionTree()
    .then((roots) => {
      regionRoots.value = roots as RegionNode[]
      regionIndex.value = indexRegions(roots as RegionNode[])
    })
    .catch((exc: any) => {
      regionError.value = exc?.message || '行政区划加载失败'
    })
    .finally(() => {
      regionLoading.value = false
      regionTreePromise = null
    })
  return regionTreePromise
}

async function refreshSelectedCommunityRow() {
  const id = app.currentCommunityId
  const known = app.communities.find((item) => Number(item.id) === id)
  if (known) {
    selectedCommunityRow.value = known
    return
  }
  if (selectedCommunityRow.value && Number(selectedCommunityRow.value.id) === id) return
  const requestId = ++selectedCommunityRequestId
  try {
    const detail = await communityApi.detail(id)
    if (requestId === selectedCommunityRequestId) {
      selectedCommunityRow.value = detail
      // 详情补取成功后登记到共享列表，供抽屉、侧边栏等使用。
      app.upsertCommunity(detail)
    }
  } catch {
    // 社区详情不可用时保持现有展示
  }
}

/** 根据社区档案的区县 / 街道反查并同步四级联动选中项。 */
function syncCascadeFromCommunity(row?: any | null) {
  const target = row ?? selectedCommunityRow.value
  const district = target?.regionId ? regionIndex.value[String(target.regionId)] : undefined
  if (!district || district.node.level !== 'DISTRICT') return
  provinceId.value = district.ancestors[0] ? String(district.ancestors[0].id) : ''
  cityId.value = district.ancestors[1] ? String(district.ancestors[1].id) : ''
  districtId.value = String(district.node.id)
  const street = target?.streetId ? regionIndex.value[String(target.streetId)] : undefined
  streetId.value = street && street.parentId === districtId.value ? String(street.node.id) : ''
}

async function initCommunityContext() {
  await Promise.all([ensureRegionTree(), refreshSelectedCommunityRow()])
  syncCascadeFromCommunity()
}

function onProvinceChange() {
  cityId.value = ''
  districtId.value = ''
  streetId.value = ''
  refreshCommunityOptionsIfOpen()
}

function onCityChange() {
  districtId.value = ''
  streetId.value = ''
  refreshCommunityOptionsIfOpen()
}

function onDistrictChange() {
  streetId.value = ''
  refreshCommunityOptionsIfOpen()
}

function onStreetChange() {
  refreshCommunityOptionsIfOpen()
}

function refreshCommunityOptionsIfOpen() {
  if (communityOptionsOpen.value) runCommunitySearch(communitySearch.value.trim())
}

async function runCommunitySearch(keyword: string) {
  const requestId = ++communitySearchRequestId
  communitySearching.value = true
  try {
    const params: Record<string, any> = { page: 1, pageSize: 20 }
    if (keyword) params.keyword = keyword
    // 按最末级已选区划收窄检索范围；社区档案的 region_id 指向区县。
    if (streetId.value) params.streetId = streetId.value
    else if (districtId.value) params.regionId = districtId.value
    else if (cityId.value) params.cityId = cityId.value
    const data = await communityApi.list(params)
    if (requestId !== communitySearchRequestId) return
    communityResults.value = data.items || []
  } catch (exc: any) {
    if (requestId === communitySearchRequestId) {
      communityResults.value = []
      app.showToast(exc?.message || '小区检索失败')
    }
  } finally {
    if (requestId === communitySearchRequestId) communitySearching.value = false
  }
}

function onCommunitySearchFocus() {
  communityOptionsOpen.value = true
  runCommunitySearch(communitySearch.value.trim())
}

function onCommunitySearchInput() {
  communityOptionsOpen.value = true
  if (communitySearchTimer) window.clearTimeout(communitySearchTimer)
  communitySearchTimer = window.setTimeout(() => runCommunitySearch(communitySearch.value.trim()), 220)
}

function clearCommunitySearch() {
  communitySearch.value = ''
  if (communitySearchTimer) window.clearTimeout(communitySearchTimer)
  communityOptionsOpen.value = true
  runCommunitySearch('')
}

/** 查询按钮 / 回车：以当前关键词检索小区并展开结果。 */
function submitCommunitySearch() {
  if (communitySearchTimer) window.clearTimeout(communitySearchTimer)
  communityOptionsOpen.value = true
  runCommunitySearch(communitySearch.value.trim())
}

/** 选中小区：切换当前运营空间，页面列表随 app.currentCommunityId 重新加载。 */
function selectCommunity(row: any) {
  communityOptionsOpen.value = false
  communitySearch.value = ''
  selectedCommunityRow.value = row
  syncCascadeFromCommunity(row)
  // 传入完整行：该小区即使不在共享列表（刚创建或分页之外），也能立即用于抽屉展示。
  app.switchCommunity(Number(row.id), row)
}

function onDocumentClick(event: MouseEvent) {
  if (!communityOptionsOpen.value) return
  if (communitySearchRoot.value && !communitySearchRoot.value.contains(event.target as Node)) {
    communityOptionsOpen.value = false
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') communityOptionsOpen.value = false
}

onMounted(() => {
  initCommunityContext()
  document.addEventListener('click', onDocumentClick)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  window.removeEventListener('keydown', onKeydown)
  if (communitySearchTimer) window.clearTimeout(communitySearchTimer)
})

watch(() => app.currentCommunityId, async () => {
  await refreshSelectedCommunityRow()
  syncCascadeFromCommunity()
})
watch(() => app.communities.length, async () => {
  if (!regionRoots.value.length) return
  await refreshSelectedCommunityRow()
  syncCascadeFromCommunity()
})
</script>

<template>
  <section class="community-filter-bar">
    <div class="community-filter-cascade">
      <label class="community-filter-field">
        <select v-model="provinceId" aria-label="省份/直辖市" :disabled="regionLoading || !provinceGroups.length" @change="onProvinceChange">
          <option value="">{{ regionLoading ? '正在加载区划…' : '省份/直辖市' }}</option>
          <optgroup v-for="group in provinceGroups" :key="group.label" :label="group.label">
            <option v-for="province in group.provinces" :key="province.id" :value="String(province.id)">{{ province.name }}</option>
          </optgroup>
        </select>
      </label>
      <ChevronRight class="community-filter-arrow" :size="14" />
      <label class="community-filter-field">
        <select v-model="cityId" aria-label="地市" :disabled="!cityNodes.length" @change="onCityChange">
          <option value="">{{ cityNodes.length ? '全部地市' : '请先选择省份' }}</option>
          <option v-for="city in cityNodes" :key="city.id" :value="String(city.id)">{{ city.name }}</option>
        </select>
      </label>
      <ChevronRight class="community-filter-arrow" :size="14" />
      <label class="community-filter-field">
        <select v-model="districtId" aria-label="区/县" :disabled="!districtNodes.length" @change="onDistrictChange">
          <option value="">{{ districtNodes.length ? '全部区县' : '请先选择地市' }}</option>
          <option v-for="district in districtNodes" :key="district.id" :value="String(district.id)">{{ district.name }}</option>
        </select>
      </label>
      <ChevronRight class="community-filter-arrow" :size="14" />
      <label class="community-filter-field">
        <select v-model="streetId" aria-label="街道" :disabled="!streetNodes.length" @change="onStreetChange">
          <option value="">{{ streetNodes.length ? '全部街道' : '请先选择区县' }}</option>
          <option v-for="street in streetNodes" :key="street.id" :value="String(street.id)">{{ street.name }}</option>
        </select>
      </label>
      <div ref="communitySearchRoot" class="community-filter-search-group">
        <label class="community-filter-search">
          <div class="community-filter-search-box">
            <Search :size="15" />
            <input
              v-model="communitySearch"
              aria-label="小区检索"
              placeholder="输入小区名称、编码或地址…"
              @focus="onCommunitySearchFocus"
              @input="onCommunitySearchInput"
              @keyup.enter="submitCommunitySearch"
            />
            <button v-if="communitySearch" class="community-filter-search-clear" aria-label="清空小区检索" @click="clearCommunitySearch"><X :size="12" /></button>
            <div v-if="communityOptionsOpen" class="community-filter-options">
              <div v-if="communitySearching" class="community-filter-options-empty">正在检索小区…</div>
              <template v-else>
                <button
                  v-for="row in communityResults"
                  :key="row.id"
                  :class="['community-filter-option', { current: Number(row.id) === app.currentCommunityId }]"
                  @click="selectCommunity(row)"
                >
                  <span class="community-filter-option-icon"><Home :size="14" /></span>
                  <span class="community-filter-option-main">
                    <strong>{{ row.name }}</strong>
                    <em>{{ row.code }}<template v-if="row.address"> · {{ row.address }}</template></em>
                  </span>
                  <em v-if="Number(row.id) === app.currentCommunityId" class="community-filter-option-tag">当前小区</em>
                </button>
                <div v-if="!communityResults.length" class="community-filter-options-empty">{{ regionError || communitySearchHint }}</div>
              </template>
            </div>
          </div>
        </label>
        <button type="button" class="community-filter-search-submit" @click="submitCommunitySearch">查询</button>
      </div>
    </div>
    <div class="community-filter-head">
      <span class="community-filter-icon"><MapPin :size="13" /></span>
      <strong class="community-filter-name">{{ selectedCommunityName || '未选择小区' }}</strong>
      <span class="community-filter-path">{{ selectedCommunityPath || '通过行政区划逐级定位，或直接检索小区名称' }}</span>
      <span class="community-filter-state">{{ scopeNote }}</span>
    </div>
  </section>
</template>
