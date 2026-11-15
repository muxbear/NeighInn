import { computed, ref } from 'vue'
import type { CommunityBinding, CommunitySearchFilter, RegionNode } from '../models'
import { communityService } from '../services/community.service'
import { useToast } from './useToast'

export type RegionPickerLevel = 'province' | 'city' | 'district' | 'street' | 'community'

export interface RegionCrumb {
  label: string
  level: RegionPickerLevel
  index: number
}

/**
 * 住户认证小区选择：省份/直辖市 → 地市 → 区/县 → 小区。
 * 街道为可选筛选条件；支持按小区名称/地址搜索，搜索范围优先限定在当前街道/区县/地市。
 */
export function useCommunityRegionPicker(onSelect: (community: CommunityBinding) => void) {
  const { showToast } = useToast()

  const visible = ref(false)
  const loading = ref(false)
  const searching = ref(false)
  const level = ref<RegionPickerLevel>('province')
  const options = ref<RegionNode[]>([])
  const communities = ref<CommunityBinding[]>([])
  const searchResults = ref<CommunityBinding[]>([])
  const searchMode = ref(false)
  const keyword = ref('')
  const searchedKeyword = ref('')
  const province = ref<RegionNode | null>(null)
  const city = ref<RegionNode | null>(null)
  const district = ref<RegionNode | null>(null)
  const street = ref<RegionNode | null>(null)

  const visibleCommunities = computed(() =>
    searchMode.value ? searchResults.value : communities.value,
  )
  const selectedStreetName = computed(() => street.value?.name || '')

  const crumbs = computed<RegionCrumb[]>(() => {
    const list: RegionCrumb[] = []
    if (province.value) list.push({ label: province.value.name, level: 'province', index: 0 })
    if (city.value) list.push({ label: city.value.name, level: 'city', index: 1 })
    if (district.value) list.push({ label: district.value.name, level: 'district', index: 2 })
    if (street.value) list.push({ label: street.value.name, level: 'street', index: 3 })
    return list
  })

  const levelTitle = computed(() => {
    if (searchMode.value) return '搜索结果'
    if (level.value === 'province') return '选择省份/直辖市'
    if (level.value === 'city') return '选择地市'
    if (level.value === 'district') return '选择区/县'
    if (level.value === 'street') return '按街道筛选（可选）'
    return '选择具体小区'
  })

  const levelHint = computed(() => {
    if (searchMode.value) {
      if (searching.value) return '正在搜索小区'
      if (!searchedKeyword.value) return '输入小区名称或地址后搜索'
      if (keyword.value.trim() !== searchedKeyword.value) return '修改关键词后请点击搜索'
      return searchResults.value.length
        ? `找到 ${searchResults.value.length} 个小区，点击即可选择`
        : '没有找到匹配的小区'
    }
    if (level.value === 'province') return '请选择小区所属的省份或直辖市'
    if (level.value === 'city') return '请选择小区所属的地市'
    if (level.value === 'district') return '请选择小区所属的区/县'
    if (level.value === 'street') return '可选择街道缩小范围，也可直接选择“全部街道”'
    if (street.value) return `以下为${street.value.name}已收录的小区`
    if (district.value) return `以下为${district.value.name}已收录的小区`
    return '请选择你要认证的小区'
  })

  const emptyTitle = computed(() => {
    if (searchMode.value) return '没有找到匹配的小区'
    if (level.value === 'province') return '暂无行政区划数据'
    if (level.value === 'city') return '该省份暂无地市数据'
    if (level.value === 'district') return '该地市暂无区/县数据'
    if (level.value === 'street') return '该区/县暂无街道数据'
    if (street.value) return '该街道暂无已收录小区'
    if (district.value) return '该区/县暂无已收录小区'
    return '暂无已收录小区'
  })

  const emptyDesc = computed(() => {
    if (searchMode.value) return '换个关键词，或按省份/地市/区县选择'
    if (level.value === 'province') return '请联系管理员补充行政区划后重试'
    if (level.value === 'city') return '该省份暂未维护地市数据'
    if (level.value === 'district') return '该地市暂未维护区/县数据'
    if (level.value === 'street') return '可直接选择“全部街道”查看该区县小区'
    return '可返回上一级选择其他区划，或到小区管理申请收录'
  })

  function clearSearch(): void {
    keyword.value = ''
    searchedKeyword.value = ''
    searchMode.value = false
    searchResults.value = []
    searching.value = false
  }

  function resetSelections(): void {
    province.value = null
    city.value = null
    district.value = null
    street.value = null
    options.value = []
    communities.value = []
    level.value = 'province'
    clearSearch()
  }

  async function loadProvinces(): Promise<void> {
    loading.value = true
    try {
      options.value = await communityService.getRegionChildren()
      communities.value = []
      level.value = 'province'
    } catch (error) {
      options.value = []
      communities.value = []
      showToast(error instanceof Error ? error.message : '区划加载失败', 'alert')
    } finally {
      loading.value = false
    }
  }

  async function loadChildren(parent: RegionNode, nextLevel: RegionPickerLevel): Promise<void> {
    loading.value = true
    try {
      options.value = await communityService.getRegionChildren(parent.id)
      communities.value = []
      level.value = nextLevel
    } catch (error) {
      showToast(error instanceof Error ? error.message : '区划加载失败', 'alert')
    } finally {
      loading.value = false
    }
  }

  async function loadDistrictCommunities(districtNode: RegionNode): Promise<void> {
    loading.value = true
    try {
      communities.value = await communityService.getByRegion(districtNode.id)
      options.value = []
      level.value = 'community'
    } catch (error) {
      communities.value = []
      showToast(error instanceof Error ? error.message : '小区加载失败', 'alert')
    } finally {
      loading.value = false
    }
  }

  async function loadStreetCommunities(streetNode: RegionNode): Promise<void> {
    loading.value = true
    try {
      communities.value = await communityService.getByStreet(streetNode.id)
      options.value = []
      level.value = 'community'
    } catch (error) {
      communities.value = []
      showToast(error instanceof Error ? error.message : '小区加载失败', 'alert')
    } finally {
      loading.value = false
    }
  }

  async function open(): Promise<void> {
    resetSelections()
    visible.value = true
    await loadProvinces()
  }

  function close(): void {
    visible.value = false
  }

  function updateKeyword(event: any): void {
    keyword.value = String(event?.detail?.value ?? '')
  }

  async function runSearch(): Promise<void> {
    const text = keyword.value.trim()
    if (!text) {
      showToast('请输入小区名称或地址', 'alert')
      return
    }
    searchedKeyword.value = text
    searchMode.value = true
    searching.value = true
    try {
      const filter: CommunitySearchFilter = { keyword: text }
      if (street.value) filter.streetId = street.value.id
      else if (district.value) filter.regionId = district.value.id
      else if (city.value) filter.cityId = city.value.id
      searchResults.value = await communityService.search(filter)
    } catch (error) {
      searchResults.value = []
      showToast(error instanceof Error ? error.message : '小区搜索失败', 'alert')
    } finally {
      searching.value = false
    }
  }

  async function chooseRegion(node: RegionNode): Promise<void> {
    if (loading.value) return
    clearSearch()
    if (level.value === 'province') {
      province.value = node
      city.value = null
      district.value = null
      street.value = null
      await loadChildren(node, 'city')
      return
    }
    if (level.value === 'city') {
      city.value = node
      district.value = null
      street.value = null
      await loadChildren(node, 'district')
      return
    }
    if (level.value === 'district') {
      district.value = node
      street.value = null
      // 不强制选择街道：直接展示该区县下所有小区。
      await loadDistrictCommunities(node)
      return
    }
    if (level.value === 'street') {
      street.value = node
      await loadStreetCommunities(node)
    }
  }

  function chooseCommunity(community: CommunityBinding): void {
    onSelect(community)
    visible.value = false
  }

  async function showStreetOptions(): Promise<void> {
    if (loading.value || !district.value) return
    clearSearch()
    await loadChildren(district.value, 'street')
  }

  async function showAllDistrictCommunities(): Promise<void> {
    if (loading.value || !district.value) return
    street.value = null
    clearSearch()
    await loadDistrictCommunities(district.value)
  }

  async function jumpTo(index: number): Promise<void> {
    if (loading.value) return
    clearSearch()
    if (index === 0) {
      resetSelections()
      await loadProvinces()
      return
    }
    if (index === 1 && province.value) {
      city.value = null
      district.value = null
      street.value = null
      await loadChildren(province.value, 'city')
      return
    }
    if (index === 2 && city.value) {
      district.value = null
      street.value = null
      await loadChildren(city.value, 'district')
      return
    }
    if (index === 3 && district.value) {
      street.value = null
      await loadChildren(district.value, 'street')
    }
  }

  return {
    visible,
    loading,
    searching,
    level,
    options,
    communities: visibleCommunities,
    keyword,
    searchMode,
    selectedStreetName,
    crumbs,
    levelTitle,
    levelHint,
    emptyTitle,
    emptyDesc,
    open,
    close,
    updateKeyword,
    runSearch,
    clearSearch,
    chooseRegion,
    chooseCommunity,
    showStreetOptions,
    showAllDistrictCommunities,
    jumpTo,
  }
}
