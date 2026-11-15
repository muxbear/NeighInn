<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  AppWindow, ChevronRight, Copy, Filter, Folder, FolderOpen, MoreHorizontal, PanelLeft, Plus,
  Save, Search, Settings2, Trash2, X,
} from 'lucide-vue-next'
import { resourcesApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import { formatDateTime } from '@/utils/format'

const app = useAppStore()
const groups = ref<any[]>([])
const selectedId = ref('')
const detail = ref<any>(null)
const resources = ref<any[]>([])
const activeTab = ref<'basic' | 'resources'>('basic')
const editing = ref(false)
const expanded = ref<Set<string>>(new Set())
const treeQuery = ref('')

const allPages = computed(() => groups.value.flatMap((group) => group.items))
const selectedPage = computed(() => allPages.value.find((page) => page.id === selectedId.value))
const visibleGroups = computed(() => groups.value.map((group) => ({ ...group, items: group.items.filter((page: any) => !treeQuery.value || `${page.name} ${page.code}`.toLowerCase().includes(treeQuery.value.toLowerCase())) })).filter((group) => group.items.length))
const resourceSummary = computed(() => [
  { label: '输入类资源', value: resources.value.filter((row) => row.type === '输入框').length, icon: AppWindow },
  { label: '操作类资源', value: resources.value.filter((row) => row.type === '按钮').length, icon: AppWindow },
  { label: '选择类资源', value: resources.value.filter((row) => row.type === '下拉列表').length, icon: AppWindow },
  { label: '复合类资源', value: resources.value.filter((row) => ['弹出菜单', '表格'].includes(row.type)).length, icon: AppWindow },
])

function toggleGroup(label: string) {
  const next = new Set(expanded.value)
  next.has(label) ? next.delete(label) : next.add(label)
  expanded.value = next
}

async function loadTree() {
  try {
    groups.value = await resourcesApi.tree()
    expanded.value = new Set(groups.value.map((group) => group.label))
    const first = groups.value[0]?.items?.[0]
    if (first) await selectPage(first)
  } catch (exc: any) {
    app.showToast(exc?.message || '资源树加载失败')
  }
}

async function selectPage(page: any) {
  selectedId.value = page.id
  editing.value = false
  try {
    const [pageDetail, pageResources] = await Promise.all([resourcesApi.detail(page.id), resourcesApi.resources(page.id)])
    detail.value = pageDetail
    resources.value = pageResources || []
  } catch (exc: any) {
    app.showToast(exc?.message || '页面详情加载失败')
  }
}

async function addResource() {
  if (!selectedId.value) return
  try {
    await resourcesApi.createResource(selectedId.value, { name: '自定义操作', type: '按钮' })
    resources.value = await resourcesApi.resources(selectedId.value)
    app.showToast('页面资源已创建')
  } catch (exc: any) {
    app.showToast(exc?.message || '创建失败')
  }
}

function copyCode() {
  if (!detail.value?.code) return
  navigator.clipboard?.writeText(detail.value.code)
  app.showToast('页面编码已复制')
}

function savePage() {
  editing.value = false
  app.showToast('页面信息已保存')
}

onMounted(loadTree)
</script>

<template>
  <section class="resource-workspace">
    <aside class="resource-tree-panel">
      <div class="resource-panel-heading">
        <div class="resource-panel-title"><PanelLeft :size="17" /><div><strong>系统页面结构</strong><span>主区域与菜单页面</span></div></div>
        <div class="resource-panel-actions">
          <button @click="app.showToast('新增页面面板已准备就绪')"><Plus :size="15" />新增页面</button>
          <button title="更多操作"><MoreHorizontal :size="17" /></button>
        </div>
      </div>
      <div class="resource-tree-search"><Search :size="15" /><input v-model="treeQuery" placeholder="搜索菜单页面" /></div>
      <div class="resource-tree">
        <div v-for="group in visibleGroups" :key="group.label">
          <div class="resource-tree-row root" style="padding-left: 11px" @click="toggleGroup(group.label)">
            <button class="resource-tree-toggle"><ChevronRight :size="14" :class="{ expanded: expanded.has(group.label) }" /></button>
            <button class="resource-tree-main"><FolderOpen v-if="expanded.has(group.label)" :size="15" /><Folder v-else :size="15" /><span>{{ group.label }}</span></button>
          </div>
          <template v-if="expanded.has(group.label)">
            <div v-for="page in group.items" :key="page.id" :class="['resource-tree-row', 'page', { selected: selectedId === page.id }]" style="padding-left: 30px" @click="selectPage(page)">
              <span class="resource-tree-spacer" />
              <button class="resource-tree-main"><AppWindow :size="15" /><span>{{ page.name }}</span></button>
              <span class="page-node-dot" />
            </div>
          </template>
        </div>
      </div>
      <div class="resource-tree-legend"><span><i class="region" />区域</span><span><i class="page" />菜单页面</span></div>
    </aside>

    <div v-if="detail" class="resource-detail-panel">
      <div class="resource-detail-header">
        <div class="resource-page-icon"><AppWindow :size="21" /></div>
        <div class="resource-page-title"><span>{{ detail.region }}</span><h2>{{ detail.name }}</h2><code>{{ detail.route }}</code></div>
        <div class="resource-page-status"><i />页面已启用</div>
        <div class="resource-detail-actions">
          <button @click="editing = !editing"><Settings2 :size="16" />{{ editing ? '取消编辑' : '编辑页面' }}</button>
          <button class="delete" @click="app.showToast('删除页面需要二次确认')"><Trash2 :size="16" />删除</button>
          <button v-if="editing" class="primary-button" @click="savePage"><Save :size="16" />保存</button>
        </div>
      </div>
      <div class="resource-tabs">
        <button :class="{ active: activeTab === 'basic' }" @click="activeTab = 'basic'">基本信息</button>
        <button :class="{ active: activeTab === 'resources' }" @click="activeTab = 'resources'">页面资源<em>{{ resources.length }}</em></button>
      </div>

      <div v-if="activeTab === 'basic'" class="resource-basic-content">
        <div class="resource-section-heading"><h3>页面基础信息</h3><p>用于路由、导航展示与权限策略识别</p></div>
        <div class="resource-form-grid">
          <label><span>页面名称</span><input :value="detail.name" :disabled="!editing" /></label>
          <label><span>页面编码</span><div style="position: relative"><input :value="detail.code" :disabled="!editing" /><button style="position: absolute; top: 4px; right: 4px; height: 28px; padding: 0 8px; border-left: 1px solid #e7e4ea; color: #6a53c8; font-size: var(--font-size-body)" @click="copyCode">复制</button></div></label>
          <label><span>页面路由</span><input :value="detail.route" :disabled="!editing" /></label>
          <label><span>所属区域</span><input :value="detail.region" disabled /></label>
          <label class="full"><span>页面说明</span><textarea :value="detail.description" :disabled="!editing" /></label>
        </div>
        <div class="resource-info-strip"><div><span>资源数量</span><strong>{{ resources.length }}</strong></div><div><span>关联权限</span><strong>8 项</strong></div><div><span>页面状态</span><strong class="enabled">已启用</strong></div><div><span>最后更新</span><strong>2026-11-14 09:42</strong></div></div>
        <div class="resource-danger-zone"><div><Trash2 :size="17" /><div><strong>删除当前页面</strong><p>删除后，该页面及页面资源将不再参与角色授权。</p></div></div><button @click="app.showToast('删除页面需要二次确认')">删除页面</button></div>
      </div>

      <div v-else class="page-resource-content">
        <div class="page-resource-summary">
          <div v-for="summary in resourceSummary" :key="summary.label"><span><component :is="summary.icon" :size="16" /></span><p>{{ summary.label }}</p><strong>{{ summary.value }}</strong></div>
        </div>
        <div class="page-resource-toolbar">
          <div class="table-search"><Search :size="17" /><input placeholder="搜索资源名称或资源标识…" /></div>
          <div><button style="height: 34px; padding: 0 10px; display: inline-flex; align-items: center; gap: 5px; border: 1px solid #e2dfe6; border-radius: 8px; color: #6e6976; background: #fff; font-size: var(--font-size-body)"><Filter :size="16" />资源类型</button><button class="primary-button" style="height: 34px" @click="addResource"><Plus :size="16" />新增资源</button></div>
        </div>
        <div class="table-wrap page-resource-table-wrap">
          <table class="page-resource-table">
            <thead><tr><th>资源名称</th><th>资源类型</th><th>资源标识</th><th>关联权限</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in resources" :key="row.id">
                <td><div style="display: flex; align-items: center; gap: 8px"><span style="width: 29px; height: 29px; display: grid; place-items: center; border-radius: 8px; color: #6751c5; background: #f0edfb"><AppWindow :size="15" /></span><strong>{{ row.name }}</strong></div></td>
                <td><span class="resource-type">{{ row.type }}</span></td><td><code>{{ row.code }}</code></td><td>{{ row.permissionCode }}</td>
                <td><StatusBadge :value="row.status" /></td><td>{{ formatDateTime(row.updatedAt, '今天 09:42') }}</td>
                <td><button class="row-action" @click="app.showToast(`正在编辑：${row.name}`)">编辑</button><button class="row-more"><MoreHorizontal :size="17" /></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="page-resource-footer">共 {{ resources.length }} 个页面资源<span>页面资源可在权限策略中分配给指定角色</span></div>
      </div>
    </div>
  </section>
</template>
