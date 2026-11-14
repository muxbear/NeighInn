<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Building2, ChevronDown, ChevronRight, Filter, Folder, FolderOpen, Home, Map, MapPin, MoreHorizontal, Plus, Search } from 'lucide-vue-next'
import { communityApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import { formatDateTime } from '@/utils/format'

const app = useAppStore()
const regions = ref<any[]>([])
const communities = ref<any[]>([])
const expanded = ref<Set<string>>(new Set())
const selectedProvince = ref('')
const selectedCity = ref('')
const selectedDistrict = ref('')
const selectedStreet = ref('')
const query = ref('')
const page = ref(1)
const total = ref(0)
const loading = ref(false)

const provinceNodes = computed(() => regions.value.filter((region: any) => region.level === 'PROVINCE'))
const currentProvince = computed(() => provinceNodes.value.find((region: any) => region.name === selectedProvince.value))
const cityNodes = computed(() => currentProvince.value?.children || [])
const currentCity = computed(() => cityNodes.value.find((region: any) => region.name === selectedCity.value))
const districtNodes = computed(() => currentCity.value?.children || [])
const currentDistrict = computed(() => districtNodes.value.find((region: any) => region.name === selectedDistrict.value))
const streetNodes = computed(() => currentDistrict.value?.children || [])

const directory = computed(() => communities.value)

function toggleProvince(name: string) {
  const next = new Set(expanded.value)
  next.has(name) ? next.delete(name) : next.add(name)
  expanded.value = next
}

function selectCity(province: any, city: any) {
  selectedProvince.value = province.name
  selectedCity.value = city.name
  selectedDistrict.value = city.children?.[0]?.name || ''
  selectedStreet.value = ''
  page.value = 1
  loadCommunities()
}

function selectDistrict(name: string) {
  selectedDistrict.value = name
  selectedStreet.value = ''
}

function selectStreet(event: Event) {
  selectedStreet.value = (event.target as HTMLSelectElement).value
  page.value = 1
  loadCommunities()
}

async function loadRegions() {
  try {
    regions.value = await communityApi.regionTree()
    const firstProvince = regions.value[0]
    if (firstProvince) {
      expanded.value = new Set([firstProvince.name])
      const firstCity = firstProvince.children?.[0]
      if (firstCity) selectCity(firstProvince, firstCity)
    }
  } catch (exc: any) {
    app.showToast(exc?.message || '行政区划加载失败')
  }
}

async function loadCommunities() {
  loading.value = true
  try {
    const params: any = { keyword: query.value, page: page.value, pageSize: 10 }
    const street = streetNodes.value.find((item: any) => item.name === selectedStreet.value)
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

onMounted(loadRegions)
</script>

<template>
  <section class="page-heading list-heading community-maintenance-heading">
    <div><p>社区管理 / 社区运维</p><h1>社区运维</h1><span>按全国行政区划统一维护城市、街道及社区基础信息</span></div>
    <button class="primary-button" @click="app.showToast('新增社区面板已准备就绪')"><Plus :size="17" />新增社区</button>
  </section>

  <section class="community-maintenance-workspace">
    <aside class="geo-tree-panel">
      <div class="geo-panel-heading">
        <div><Map :size="17" /><div><strong>全国行政区划</strong><span>{{ provinceNodes.length }} 个省级行政区</span></div></div>
        <button title="定位当前城市" @click="app.showToast('已定位到杭州市')"><MapPin :size="16" /></button>
      </div>
      <div class="geo-tree-search"><Search :size="15" /><input placeholder="搜索省份或地市" /></div>
      <div class="geo-tree">
        <div v-for="province in provinceNodes" :key="province.id" class="geo-province">
          <button :class="['geo-province-row', { current: selectedProvince === province.name }]" @click="toggleProvince(province.name)">
            <ChevronRight :size="14" :class="{ expanded: expanded.has(province.name) }" />
            <FolderOpen v-if="expanded.has(province.name)" :size="16" /><Folder v-else :size="16" />
            <strong>{{ province.name }}</strong><em>{{ province.children?.length || 0 }}</em>
          </button>
          <div v-if="expanded.has(province.name)" class="geo-city-list">
            <button v-for="city in province.children" :key="city.id" :class="{ selected: selectedCity === city.name }" @click="selectCity(province, city)">
              <span /> <MapPin :size="13" />{{ city.name }}
            </button>
          </div>
        </div>
      </div>
      <div class="geo-tree-footer"><span><i class="province" />省级节点</span><span><i class="city" />地市叶子节点</span></div>
    </aside>

    <div class="community-directory-panel">
      <div class="community-directory-header">
        <div class="community-location-icon"><Building2 :size="21" /></div>
        <div><span>当前地市</span><h2>{{ selectedCity || '杭州市' }}</h2><p>{{ selectedProvince || '浙江省' }} · 社区基础信息目录</p></div>
        <div class="city-overview"><span><strong>{{ districtNodes.length }}</strong> 个区县</span><i /><span><strong>128</strong> 个街道</span><i /><span><strong>{{ total || 2486 }}</strong> 个社区</span></div>
      </div>
      <div class="community-location-filters">
        <div class="location-path"><MapPin :size="16" /><span>{{ selectedProvince }}</span><ChevronRight :size="13" /><strong>{{ selectedCity }}</strong></div>
        <label><span>所在区县</span><div style="position: relative"><select v-model="selectedDistrict" @change="selectDistrict(selectedDistrict)"><option v-for="district in districtNodes" :key="district.id">{{ district.name }}</option></select><ChevronDown :size="14" style="position: absolute; right: 9px; top: 10px; color: #96919d" /></div></label>
        <label><span>所在街道</span><div style="position: relative"><select :value="selectedStreet" @change="selectStreet"><option value="">全部街道</option><option v-for="street in streetNodes" :key="street.id">{{ street.name }}</option></select><ChevronDown :size="14" style="position: absolute; right: 9px; top: 10px; color: #96919d" /></div></label>
      </div>
      <div class="community-table-toolbar">
        <div><h3>{{ selectedStreet || '全部' }}社区列表</h3><span>共 {{ total }} 个社区</span></div>
        <div>
          <div class="table-search"><Search :size="16" /><input v-model="query" placeholder="搜索社区名称或编码…" @keyup.enter="loadCommunities" /></div>
          <button @click="loadCommunities"><Filter :size="15" />筛选</button>
          <button class="primary-button" @click="app.showToast('新增社区面板已准备就绪')"><Plus :size="15" />新增社区</button>
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
              <td><button class="row-action" @click="app.showToast(`正在查看：${row.name}`)">查看</button><button class="row-more"><MoreHorizontal :size="17" /></button></td>
            </tr>
          </tbody>
        </table>
        <EmptyState v-if="!directory.length" title="暂无社区" description="请选择区划或调整搜索条件" />
      </div>
      <div class="community-pagination"><span>第 {{ page }} / 1 页，共 {{ total }} 条记录</span><div><button :disabled="page <= 1" @click="page--; loadCommunities()">上一页</button><button class="current">1</button><button>下一页</button></div></div>
    </div>
  </section>
</template>
