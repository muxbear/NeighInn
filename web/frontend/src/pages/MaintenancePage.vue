<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Building2, ChevronRight, Download, Filter, Folder, FolderOpen, Home, Map, MapPin, Pencil, Plus, Search, Trash2, Upload } from 'lucide-vue-next'
import { communityApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useConfirm } from '@/composables/useConfirm'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import { formatDateTime } from '@/utils/format'
import { groupProvinces } from '@/utils/region'

const app = useAppStore()
const { confirm } = useConfirm()
const regionRoots = ref<any[]>([])
const childrenByParent = reactive<Record<string, any[]>>({})
const cityLoading = reactive<Record<string, boolean>>({})
const regionsLoading = ref(false)
const districtLoading = ref(false)
const streetLoading = ref(false)
const communities = ref<any[]>([])
const expanded = ref<Set<string>>(new Set())
const selectedProvinceName = ref('')
const selectedCityName = ref('')
const selectedDistrictName = ref('')
const selectedStreetName = ref('')
const query = ref('')
const page = ref(1)
const total = ref(0)
const loading = ref(false)
let cityRequestId = 0

const COMMUNITY_TYPES = ['商品房社区', '经济适用房社区', '综合型社区', '老旧小区', '村改居社区']
const STATUS_OPTIONS = [
  { value: 'OPERATING', label: '正常运营' },
  { value: 'PREPARING', label: '筹备中' },
  { value: 'SUSPENDED', label: '已停用' },
]

const formOpen = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editingId = ref('')
const formSaving = ref(false)
const formDistricts = ref<any[]>([])
const formStreets = ref<any[]>([])
const formDistrictsLoading = ref(false)
const formStreetsLoading = ref(false)
const form = reactive({
  name: '',
  code: '',
  type: '商品房社区',
  address: '',
  districtId: '',
  streetId: '',
  longitude: '',
  latitude: '',
  households: 0,
  population: 0,
  propertyContact: '',
  managerName: '',
  status: 'OPERATING',
})

const importOpen = ref(false)
const importing = ref(false)
const importFileName = ref('')
const importRows = ref<any[]>([])
const importPreview = ref<any[]>([])
const importErrors = ref<string[]>([])
const importResult = ref<any | null>(null)

const currentCityLabel = computed(() =>
  [selectedProvinceName.value, selectedCityName.value].filter(Boolean).join(' / ') || '未选择地市',
)

function statusLabel(status: string): string {
  return STATUS_OPTIONS.find((option) => option.value === status)?.label || status
}

function cachedChildren(parent: any): any[] {
  if (!parent?.id) return []
  return childrenByParent[String(parent.id)] || []
}

function regionChildCount(node: any): number {
  if (typeof node?.childCount === 'number') return node.childCount
  return cachedChildren(node).length
}

function provinceCities(province: any): any[] {
  return cachedChildren(province)
}

async function ensureChildren(parent: any): Promise<any[]> {
  const key = String(parent.id)
  if (childrenByParent[key]) return childrenByParent[key]
  const children = await communityApi.regionChildren(parent.id)
  childrenByParent[key] = children
  return children
}

const provinceNodes = computed(() => regionRoots.value)
const provinceGroups = computed(() => groupProvinces(regionRoots.value))
const sortedProvinces = computed(() => provinceGroups.value.flatMap((group) => group.provinces))
const currentProvince = computed(() =>
  provinceNodes.value.find((region: any) => region.name === selectedProvinceName.value),
)
const cityNodes = computed(() => cachedChildren(currentProvince.value))
const currentCity = computed(() => cityNodes.value.find((region: any) => region.name === selectedCityName.value))
const districtNodes = computed(() => cachedChildren(currentCity.value))
const currentDistrict = computed(() =>
  districtNodes.value.find((region: any) => region.name === selectedDistrictName.value),
)
const streetNodes = computed(() => cachedChildren(currentDistrict.value))
const cityStreetCount = computed(() =>
  districtNodes.value.reduce((sum: number, district: any) => sum + regionChildCount(district), 0),
)

const directory = computed(() => communities.value)

async function toggleProvince(province: any): Promise<void> {
  const key = String(province.id)
  const next = new Set(expanded.value)
  if (next.has(key)) {
    next.delete(key)
    expanded.value = next
    return
  }
  next.add(key)
  expanded.value = next
  if (childrenByParent[key] || cityLoading[key]) return
  cityLoading[key] = true
  try {
    await ensureChildren(province)
  } catch (exc: any) {
    app.showToast(exc?.message || '地市加载失败')
    const rollback = new Set(expanded.value)
    rollback.delete(key)
    expanded.value = rollback
  } finally {
    cityLoading[key] = false
  }
}

async function selectCity(province: any, city: any): Promise<void> {
  const requestId = ++cityRequestId
  selectedProvinceName.value = province.name
  selectedCityName.value = city.name
  selectedDistrictName.value = ''
  selectedStreetName.value = ''
  page.value = 1
  loadCommunities()

  districtLoading.value = true
  try {
    const districts = await ensureChildren(city)
    if (requestId !== cityRequestId) return
    const firstDistrict = districts[0]
    if (firstDistrict) {
      selectedDistrictName.value = firstDistrict.name
      await loadStreets(firstDistrict)
    }
  } catch (exc: any) {
    if (requestId === cityRequestId) app.showToast(exc?.message || '区县加载失败')
  } finally {
    if (requestId === cityRequestId) districtLoading.value = false
  }
}

async function loadStreets(district: any): Promise<void> {
  streetLoading.value = true
  try {
    await ensureChildren(district)
  } catch (exc: any) {
    app.showToast(exc?.message || '街道加载失败')
  } finally {
    streetLoading.value = false
  }
}

async function selectDistrict(name: string): Promise<void> {
  selectedDistrictName.value = name
  selectedStreetName.value = ''
  const district = districtNodes.value.find((item: any) => item.name === name)
  if (district) await loadStreets(district)
}

function selectStreet(event: Event): void {
  selectedStreetName.value = (event.target as HTMLSelectElement).value
  page.value = 1
  loadCommunities()
}

async function loadRegions(): Promise<void> {
  regionsLoading.value = true
  try {
    regionRoots.value = await communityApi.regionRoots()
    const firstProvince = sortedProvinces.value[0]
    if (firstProvince) {
      const key = String(firstProvince.id)
      expanded.value = new Set([key])
      let cities: any[] = []
      cityLoading[key] = true
      try {
        cities = await ensureChildren(firstProvince)
      } finally {
        cityLoading[key] = false
      }
      const firstCity = cities[0]
      if (firstCity) await selectCity(firstProvince, firstCity)
    }
  } catch (exc: any) {
    app.showToast(exc?.message || '行政区划加载失败')
  } finally {
    regionsLoading.value = false
  }
}

async function loadCommunities(): Promise<void> {
  loading.value = true
  try {
    const params: any = { keyword: query.value, page: page.value, pageSize: 10 }
    if (currentCity.value?.id) params.cityId = currentCity.value.id
    const street = streetNodes.value.find((item: any) => item.name === selectedStreetName.value)
    if (street) params.streetId = street.id
    const data = await communityApi.list(params)
    communities.value = data.items || []
    total.value = data.total || 0
  } catch (exc: any) {
    app.showToast(exc?.message || '社区目录加载失败')
  } finally {
    loading.value = false
  }
}

/** 社区档案变更后刷新共享运营空间列表，保证侧边栏、筛选栏与人员抽屉同步。 */
async function refreshSharedCommunities(saved?: any): Promise<void> {
  try {
    await app.loadCommunities()
  } catch {
    // 共享列表刷新失败不阻塞页面本地结果
  }
  if (saved?.id !== undefined) app.upsertCommunity(saved)
}

async function openCreate(): Promise<void> {
  if (!currentCity.value) {
    app.showToast('请先在左侧选择地市')
    return
  }
  formMode.value = 'create'
  editingId.value = ''
  Object.assign(form, {
    name: '', code: '', type: '商品房社区', address: '',
    districtId: '', streetId: '', longitude: '', latitude: '',
    households: 0, population: 0, propertyContact: '', managerName: '', status: 'OPERATING',
  })
  formOpen.value = true
  formDistrictsLoading.value = true
  try {
    formDistricts.value = await ensureChildren(currentCity.value)
    const district = currentDistrict.value || formDistricts.value[0]
    form.districtId = district ? String(district.id) : ''
    form.streetId = ''
    await loadFormStreets()
  } catch (exc: any) {
    app.showToast(exc?.message || '区县加载失败')
  } finally {
    formDistrictsLoading.value = false
  }
}

async function openEdit(row: any): Promise<void> {
  if (!currentCity.value) {
    app.showToast('请先在左侧选择地市')
    return
  }
  formMode.value = 'edit'
  editingId.value = String(row.id)
  Object.assign(form, {
    name: row.name || '', code: row.code || '', type: row.type || '商品房社区',
    address: row.address || '', districtId: row.regionId ? String(row.regionId) : '',
    streetId: row.streetId ? String(row.streetId) : '',
    longitude: row.longitude ?? '', latitude: row.latitude ?? '',
    households: row.households || 0, population: row.population || 0,
    propertyContact: '', managerName: row.managerName || '',
    status: row.statusCode || 'OPERATING',
  })
  formOpen.value = true
  formDistrictsLoading.value = true
  try {
    formDistricts.value = await ensureChildren(currentCity.value)
    if (!form.districtId) form.districtId = String(formDistricts.value[0]?.id || '')
    await loadFormStreets()
  } catch (exc: any) {
    app.showToast(exc?.message || '区县加载失败')
  } finally {
    formDistrictsLoading.value = false
  }
}

async function loadFormStreets(): Promise<void> {
  const district = formDistricts.value.find((item: any) => String(item.id) === String(form.districtId))
  if (!district) {
    formStreets.value = []
    form.streetId = ''
    return
  }
  formStreetsLoading.value = true
  try {
    formStreets.value = await communityApi.regionChildren(district.id)
  } catch (exc: any) {
    formStreets.value = []
    app.showToast(exc?.message || '街道加载失败')
  } finally {
    formStreetsLoading.value = false
  }
}

function onFormDistrictChange(): void {
  form.streetId = ''
  loadFormStreets()
}

async function saveCommunity(): Promise<void> {
  if (formSaving.value) return
  const name = form.name.trim()
  if (!name) {
    app.showToast('请填写社区名称')
    return
  }
  if (!form.districtId) {
    app.showToast('请选择所在区县')
    return
  }
  const longitudeText = String(form.longitude ?? '').trim()
  const latitudeText = String(form.latitude ?? '').trim()
  let longitude: number | null = null
  let latitude: number | null = null
  if (longitudeText || latitudeText) {
    if (!longitudeText || !latitudeText) {
      app.showToast('经度与纬度需同时填写或同时留空')
      return
    }
    longitude = Number(longitudeText)
    latitude = Number(latitudeText)
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
      app.showToast('请填写有效的经纬度')
      return
    }
    if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
      app.showToast('经度需在 -180~180，纬度需在 -90~90')
      return
    }
  }
  const payload = {
    name,
    code: form.code.trim() || undefined,
    type: form.type,
    address: form.address.trim(),
    regionId: Number(form.districtId),
    streetId: form.streetId ? Number(form.streetId) : null,
    longitude,
    latitude,
    propertyContact: form.propertyContact.trim(),
    households: Number(form.households) || 0,
    population: Number(form.population) || 0,
    managerName: form.managerName.trim(),
    status: form.status,
  }
  formSaving.value = true
  try {
    let saved: any = null
    if (formMode.value === 'create') {
      saved = await communityApi.create(payload)
      app.showToast('社区已创建')
    } else {
      saved = await communityApi.update(editingId.value, payload)
      app.showToast('社区已更新')
    }
    formOpen.value = false
    selectedStreetName.value = ''
    await loadCommunities()
    await refreshSharedCommunities(saved)
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  } finally {
    formSaving.value = false
  }
}

async function removeCommunity(row: any): Promise<void> {
  if (!(await confirm({ title: '删除社区', message: `确定删除社区“${row.name}”吗？删除后不可恢复。`, confirmText: '确认删除', danger: true }))) return
  try {
    await communityApi.remove(row.id)
    app.showToast('社区已删除')
    await loadCommunities()
    await refreshSharedCommunities()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

async function removeFromForm(): Promise<void> {
  if (!editingId.value) return
  if (!(await confirm({ title: '删除社区', message: '确定删除当前社区吗？删除后不可恢复。', confirmText: '确认删除', danger: true }))) return
  try {
    await communityApi.remove(editingId.value)
    app.showToast('社区已删除')
    formOpen.value = false
    await loadCommunities()
    await refreshSharedCommunities()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

function openImport(): void {
  if (!currentCity.value) {
    app.showToast('请先在左侧选择地市')
    return
  }
  importOpen.value = true
  importing.value = false
  importFileName.value = ''
  importRows.value = []
  importPreview.value = []
  importErrors.value = []
  importResult.value = null
  // 提前加载区县，便于生成带示例区县的 CSV 模板
  ensureChildren(currentCity.value).then((children) => {
    formDistricts.value = children
  }).catch(() => undefined)
}

async function downloadTemplate(): Promise<void> {
  const XLSX = await import('xlsx')
  const district = formDistricts.value[0] || districtNodes.value[0]
  const header = ['社区名称', '社区编码', '社区类型', '所在区县', '所在街道', '小区地址',
    '经度', '纬度', '户数', '人口', '物业联系人', '负责人', '状态']
  const sample = ['示例花园小区', '', '商品房社区', district?.name || '东城区', '',
    '示例路 1 号', '116.4074000', '39.9042000', '1000', '2500', '', '', '正常运营']
  const columnWidths = [18, 16, 14, 14, 16, 24, 14, 14, 10, 10, 16, 14, 12]
    .map((width) => ({ wch: width }))
  // 主表仅保留表头，避免示例小区被误导入；示例放在独立工作表。
  const sheet = XLSX.utils.aoa_to_sheet([header])
  sheet['!cols'] = columnWidths
  const sampleSheet = XLSX.utils.aoa_to_sheet([header, sample])
  sampleSheet['!cols'] = columnWidths

  const instructions = XLSX.utils.aoa_to_sheet([
    ['字段', '填写说明'],
    ['提示', '“社区导入”工作表仅保留表头，请直接在表头下方填写；示例见“示例数据”工作表'],
    ['社区名称', '必填，最多 64 字；同一区县内不可重名'],
    ['社区编码', '可选；留空自动生成；不可与已有编码重复'],
    ['社区类型', '可选；如商品房社区、经济适用房社区、综合型社区、老旧小区、村改居社区'],
    ['所在区县', '必填；必须是当前地市下的区县名称'],
    ['所在街道', '可选；填写时必须属于所在区县'],
    ['经度 / 纬度', '可选；建议同时填写，例如 116.4074000 / 39.9042000'],
    ['户数 / 人口', '可选；非负整数'],
    ['运营状态', '可选；正常运营 / 筹备中 / 已停用'],
  ])
  instructions['!cols'] = [{ wch: 16 }, { wch: 60 }]

  const districtSheet = XLSX.utils.aoa_to_sheet([
    ['当前地市', currentCityLabel.value],
    ['可选区县', formDistricts.value.map((item: any) => item.name).join('、')
      || '请先在左侧选择地市'],
  ])
  districtSheet['!cols'] = [{ wch: 16 }, { wch: 80 }]

  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, sheet, '社区导入')
  XLSX.utils.book_append_sheet(workbook, sampleSheet, '示例数据')
  XLSX.utils.book_append_sheet(workbook, instructions, '填写说明')
  XLSX.utils.book_append_sheet(workbook, districtSheet, '区县参考')
  XLSX.writeFile(workbook, '社区批量导入模板.xlsx')
}

function normalizeImportStatus(value: string): string | null {
  const text = value.trim()
  if (!text) return 'OPERATING'
  const aliases: Record<string, string> = {
    正常运营: 'OPERATING', 运营中: 'OPERATING', OPERATING: 'OPERATING',
    筹备中: 'PREPARING', PREPARING: 'PREPARING',
    已停用: 'SUSPENDED', 停用: 'SUSPENDED', SUSPENDED: 'SUSPENDED',
  }
  return aliases[text] || aliases[text.toUpperCase()] || null
}

function parseImportRows(rows: string[][]): void {
  importRows.value = []
  importPreview.value = []
  importErrors.value = []
  const headerIndex = rows.findIndex((row) => row.some((cell) => cell === '社区名称'))
  if (headerIndex < 0) {
    importErrors.value = ['未找到表头：请确认首行包含“社区名称”“所在区县”等列']
    return
  }
  const header = rows[headerIndex].map((cell) => cell.trim())
  const indexOf = (name: string) => header.indexOf(name)
  const required = ['社区名称', '所在区县']
  const missing = required.filter((name) => indexOf(name) < 0)
  if (missing.length) {
    importErrors.value = [`缺少必填列：${missing.join('、')}`]
    return
  }
  const dataRows = rows.slice(headerIndex + 1)
  if (!dataRows.length) {
    importErrors.value = ['文件只有表头，没有可导入的数据']
    return
  }
  if (dataRows.length > 500) {
    importErrors.value = ['单次最多导入 500 行，请拆分文件后重试']
    return
  }
  const errors: string[] = []
  const items: any[] = []
  dataRows.forEach((cells, offset) => {
    const rowNumber = headerIndex + offset + 2
    const cell = (name: string) => {
      const index = indexOf(name)
      return index >= 0 ? String(cells[index] ?? '').trim() : ''
    }
    const name = cell('社区名称')
    const districtName = cell('所在区县')
    const longitudeText = cell('经度')
    const latitudeText = cell('纬度')
    const hasLongitude = longitudeText !== ''
    const hasLatitude = latitudeText !== ''
    const longitude = Number(longitudeText)
    const latitude = Number(latitudeText)
    const status = normalizeImportStatus(cell('状态'))
    const problems: string[] = []
    if (!name) problems.push('社区名称必填')
    if (!districtName) problems.push('所在区县必填')
    if (hasLongitude !== hasLatitude) problems.push('经纬度需同时填写或同时留空')
    if (hasLongitude && !Number.isFinite(longitude)) problems.push('经度无效')
    if (hasLatitude && !Number.isFinite(latitude)) problems.push('纬度无效')
    if (!status) problems.push('状态需为正常运营/筹备中/已停用')
    if (problems.length) {
      errors.push(`第 ${rowNumber} 行：${problems.join('；')}`)
      return
    }
    const households = Number(cell('户数') || 0)
    const population = Number(cell('人口') || 0)
    if (!Number.isFinite(households) || households < 0
      || !Number.isFinite(population) || population < 0) {
      errors.push(`第 ${rowNumber} 行：户数/人口需为非负数字`)
      return
    }
    items.push({
      name,
      code: cell('社区编码'),
      type: cell('社区类型') || '商品房社区',
      districtName,
      streetName: cell('所在街道'),
      address: cell('小区地址'),
      longitude: hasLongitude ? longitude : null,
      latitude: hasLatitude ? latitude : null,
      households,
      population,
      propertyContact: cell('物业联系人'),
      managerName: cell('负责人'),
      status,
    })
  })
  importRows.value = items
  importPreview.value = items.slice(0, 5)
  importErrors.value = errors
}

async function onImportFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importFileName.value = file.name
  importResult.value = null
  importErrors.value = []
  if (file.size > 5 * 1024 * 1024) {
    importErrors.value = ['文件不能超过 5MB']
    return
  }
  try {
    const XLSX = await import('xlsx')
    const isCsv = file.name.toLowerCase().endsWith('.csv')
    const workbook = isCsv
      ? XLSX.read(await file.text(), { type: 'string' })
      : XLSX.read(await file.arrayBuffer(), { type: 'array' })
    const firstSheet = workbook.Sheets[workbook.SheetNames[0]]
    if (!firstSheet) {
      importErrors.value = ['文件中没有可读取的工作表']
      return
    }
    const rawRows = XLSX.utils.sheet_to_json<unknown[]>(firstSheet, {
      header: 1, defval: '', raw: false,
    })
    const rows = rawRows
      .map((row) => (Array.isArray(row) ? row : []).map((cell) => String(cell ?? '').trim()))
      .filter((row) => row.some((cell) => cell !== ''))
    parseImportRows(rows)
  } catch {
    importErrors.value = ['文件解析失败，请确认是有效的 Excel（.xlsx/.xls）或 CSV 文件']
  }
}

async function runImport(): Promise<void> {
  if (importing.value || !importRows.value.length || !currentCity.value) return
  importing.value = true
  importResult.value = null
  try {
    const result = await communityApi.importRows({
      cityId: Number(currentCity.value.id),
      items: importRows.value,
    })
    importResult.value = result
    app.showToast(`成功导入 ${result.created} 个社区${result.failed ? `，${result.failed} 行失败` : ''}`)
    if (result.created) {
      importRows.value = []
      importPreview.value = []
      await loadCommunities()
      await refreshSharedCommunities()
    }
  } catch (exc: any) {
    app.showToast(exc?.message || '导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(loadRegions)
</script>

<template>
  <section class="community-maintenance-workspace">
    <aside class="geo-tree-panel">
      <div class="geo-panel-heading">
        <div><Map :size="17" /><div><strong>全国行政区划</strong><span>{{ provinceNodes.length }} 个省级行政区</span></div></div>
        <button title="定位当前城市" @click="app.showToast('已定位到杭州市')"><MapPin :size="16" /></button>
      </div>
      <div class="geo-tree-search"><Search :size="15" /><input placeholder="搜索省份或地市" /></div>
      <div class="geo-tree">
        <div v-if="regionsLoading && !provinceNodes.length" class="geo-tree-loading">
          正在加载全国行政区划…
        </div>
        <div v-for="group in provinceGroups" :key="group.label" class="geo-group">
          <div class="geo-group-title">
            <span>{{ group.label }}</span>
            <em>{{ group.provinces.length }}</em>
          </div>
          <div v-for="province in group.provinces" :key="province.id" class="geo-province">
            <button :class="['geo-province-row', { current: selectedProvinceName === province.name }]" @click="toggleProvince(province)">
              <ChevronRight :size="14" :class="{ expanded: expanded.has(String(province.id)) }" />
              <FolderOpen v-if="expanded.has(String(province.id))" :size="16" /><Folder v-else :size="16" />
              <strong>{{ province.name }}</strong><em>{{ regionChildCount(province) }}</em>
            </button>
            <div v-if="expanded.has(String(province.id))" class="geo-city-list">
              <div v-if="cityLoading[String(province.id)]" class="geo-city-empty">正在加载地市…</div>
              <template v-else>
                <button v-for="city in provinceCities(province)" :key="city.id" :class="{ selected: selectedCityName === city.name }" @click="selectCity(province, city)">
                  <span /> <MapPin :size="13" />{{ city.name }}
                </button>
                <div v-if="!provinceCities(province).length" class="geo-city-empty">暂无地市数据</div>
              </template>
            </div>
          </div>
        </div>
      </div>
      <div class="geo-tree-footer"><span><i class="province" />省级节点</span><span><i class="city" />地市叶子节点</span></div>
    </aside>

    <div class="community-directory-panel">
      <div class="community-directory-header">
        <div class="community-location-icon"><Building2 :size="21" /></div>
        <div><span>当前地市</span><h2>{{ selectedCityName || '杭州市' }}</h2><p>{{ selectedProvinceName || '浙江省' }} · 社区基础信息目录</p></div>
        <div class="city-overview"><span><strong>{{ districtNodes.length }}</strong> 个区县</span><i /><span><strong>{{ cityStreetCount }}</strong> 个街道</span><i /><span><strong>{{ total }}</strong> 个社区</span></div>
        <button class="community-import-button" @click="openImport"><Upload :size="16" />批量导入</button>
      </div>
      <div class="community-location-filters">
        <div class="location-path"><MapPin :size="16" /><span>{{ selectedProvinceName }}</span><ChevronRight :size="13" /><strong>{{ selectedCityName }}</strong></div>
        <label><select v-model="selectedDistrictName" aria-label="所在区县" :disabled="districtLoading || !districtNodes.length" @change="selectDistrict(selectedDistrictName)"><option v-if="districtLoading" value="">加载中…</option><option v-for="district in districtNodes" :key="district.id">{{ district.name }}</option></select></label>
        <label><select :value="selectedStreetName" aria-label="所在街道" :disabled="streetLoading || !streetNodes.length" @change="selectStreet"><option value="">全部街道</option><option v-if="streetLoading" value="__loading" disabled>加载中…</option><option v-for="street in streetNodes" :key="street.id">{{ street.name }}</option></select></label>
      </div>
      <div class="community-table-toolbar">
        <div><h3>{{ selectedStreetName || '全部' }}社区列表</h3><span>共 {{ total }} 个社区</span></div>
        <div>
          <div class="table-search"><Search :size="16" /><input v-model="query" placeholder="搜索社区名称或编码…" @keyup.enter="loadCommunities" /></div>
          <button @click="loadCommunities"><Filter :size="15" />筛选</button>
          <button @click="openImport"><Upload :size="15" />批量导入</button>
          <button class="primary-button" @click="openCreate"><Plus :size="15" />新增社区</button>
        </div>
      </div>
      <div class="table-wrap community-directory-table-wrap">
        <table class="community-directory-table">
          <thead><tr><th>社区名称</th><th>社区编码</th><th>社区类型</th><th>户数 / 人口</th><th>负责人</th><th>运营状态</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in directory" :key="row.id">
              <td><div class="community-name-cell"><span><Home :size="15" /></span><div><strong>{{ row.name }}</strong><em>{{ row.address }}</em></div></div></td>
              <td><code>{{ row.code }}</code></td><td><span class="community-type">{{ row.type }}</span></td>
              <td><strong class="community-number">{{ Number(row.households || 0).toLocaleString() }}</strong> 户 · {{ Number(row.population || 0).toLocaleString() }} 人</td>
              <td>{{ row.managerName }}</td><td><StatusBadge :value="row.status" /></td><td>{{ formatDateTime(row.updatedAt) }}</td>
              <td>
                <div class="row-actions">
                  <button class="row-icon-button" aria-label="编辑社区" data-tip="编辑社区" @click="openEdit(row)"><Pencil :size="15" /></button>
                  <button class="row-icon-button danger" aria-label="删除社区" data-tip="删除社区" @click="removeCommunity(row)"><Trash2 :size="15" /></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <EmptyState v-if="!directory.length" title="暂无社区" description="请选择区划或调整搜索条件" />
      </div>
      <div class="community-pagination"><span>第 {{ page }} / 1 页，共 {{ total }} 条记录</span><div><button :disabled="page <= 1" @click="page--; loadCommunities()">上一页</button><button class="current">1</button><button>下一页</button></div></div>
    </div>
  </section>

  <NiDrawer :open="formOpen" :title="formMode === 'create' ? '新增社区' : '编辑社区'" eyebrow="社区运维" @close="formOpen = false">
    <div class="community-form-hint">
      <strong>{{ currentCityLabel }}</strong>
      <span>所在街道、经纬度均为可选项；填写经纬度后可参与距离计算与邻近排序。</span>
    </div>
    <div class="form-grid">
      <label class="full"><span>社区名称 *</span><input v-model="form.name" maxlength="64" placeholder="请输入社区名称" /></label>
      <label><span>社区编码</span><input v-model="form.code" :disabled="formMode === 'edit'" maxlength="32" placeholder="留空自动生成" /></label>
      <label><span>社区类型</span><select v-model="form.type"><option v-for="type in COMMUNITY_TYPES" :key="type">{{ type }}</option></select></label>
      <label><span>所在区/县 *</span><select v-model="form.districtId" :disabled="formDistrictsLoading" @change="onFormDistrictChange"><option v-if="formDistrictsLoading" value="">加载中…</option><option v-for="district in formDistricts" :key="district.id" :value="String(district.id)">{{ district.name }}</option></select></label>
      <label><span>所在街道（可选）</span><select v-model="form.streetId" :disabled="formStreetsLoading"><option value="">不指定街道</option><option v-if="formStreetsLoading" value="__loading" disabled>加载中…</option><option v-for="street in formStreets" :key="street.id" :value="String(street.id)">{{ street.name }}</option></select></label>
      <label class="full"><span>小区地址</span><input v-model="form.address" maxlength="255" placeholder="例如：东华门街道示例花园" /></label>
      <label><span>经度</span><input v-model="form.longitude" type="number" step="0.0000001" placeholder="选填，例如 116.4074000" /></label>
      <label><span>纬度</span><input v-model="form.latitude" type="number" step="0.0000001" placeholder="选填，例如 39.9042000" /></label>
      <label><span>户数</span><input v-model.number="form.households" type="number" min="0" /></label>
      <label><span>人口</span><input v-model.number="form.population" type="number" min="0" /></label>
      <label><span>物业联系人</span><input v-model="form.propertyContact" :placeholder="formMode === 'edit' ? '留空则不修改' : '选填'" /></label>
      <label><span>负责人</span><input v-model="form.managerName" maxlength="64" /></label>
      <label><span>运营状态</span><select v-model="form.status"><option v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
    </div>
    <template #footer>
      <button @click="formOpen = false">取消</button>
      <button v-if="formMode === 'edit'" class="danger-button" @click="removeFromForm">删除</button>
      <button class="primary-button" :disabled="formSaving" @click="saveCommunity">{{ formSaving ? '保存中…' : '保存' }}</button>
    </template>
  </NiDrawer>

  <NiDrawer :open="importOpen" title="批量导入社区" eyebrow="社区运维" @close="importOpen = false">
    <div class="import-block">
      <div class="import-current">
        <strong>{{ currentCityLabel }}</strong>
        <span>导入的区县必须属于当前地市；所在街道、经纬度可留空。</span>
      </div>
      <div class="import-actions">
        <button class="secondary-button" @click="downloadTemplate"><Download :size="16" />下载 Excel 模板</button>
        <label class="import-file">
          <Upload :size="16" />选择 Excel 文件
          <input type="file" accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv" @change="onImportFile" />
        </label>
      </div>
      <div v-if="importFileName" class="import-file-name">已选择：{{ importFileName }}</div>
      <p class="import-tips">支持 Excel（.xlsx/.xls），兼容 CSV；必填列：社区名称、所在区县；社区编码、所在街道、经纬度、地址等可选。</p>
      <div v-if="importErrors.length" class="import-errors">
        <strong>需要修正的行</strong>
        <p v-for="(error, index) in importErrors" :key="index">{{ error }}</p>
      </div>
      <div v-if="importPreview.length" class="import-preview">
        <div class="import-preview-head"><strong>待导入 {{ importRows.length }} 行</strong><span>预览前 {{ importPreview.length }} 行</span></div>
        <table>
          <thead><tr><th>社区名称</th><th>所在区县</th><th>所在街道</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="(row, index) in importPreview" :key="index">
              <td>{{ row.name }}</td><td>{{ row.districtName }}</td>
              <td>{{ row.streetName || '不指定' }}</td><td>{{ statusLabel(row.status) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="importResult" class="import-result">
        <strong>导入结果：成功 {{ importResult.created }} 个，失败 {{ importResult.failed }} 行</strong>
        <p v-for="(error, index) in importResult.errors || []" :key="index">
          第 {{ error.row }} 行 {{ error.name || '' }}：{{ error.message }}
        </p>
      </div>
    </div>
    <template #footer>
      <button @click="importOpen = false">关闭</button>
      <button class="primary-button" :disabled="importing || !importRows.length" @click="runImport">{{ importing ? '导入中…' : `开始导入（${importRows.length}）` }}</button>
    </template>
  </NiDrawer>
</template>
