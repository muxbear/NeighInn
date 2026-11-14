<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Check, ChevronDown, ChevronRight, Copy, Filter, Folder, FolderOpen, KeyRound, MoreHorizontal, Plus, Search, Settings2, X } from 'lucide-vue-next'
import { parametersApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'

const app = useAppStore()
const tree = ref<any[]>([])
const selectedKey = ref<any>(null)
const items = ref<any[]>([])
const expanded = ref<Set<string>>(new Set())
const treeQuery = ref('')
const itemQuery = ref('')
const creatingRoot = ref(false)
const rootName = ref('')

type FlatNode = { node: any; depth: number }

function flatten(nodes: any[], depth = 0): FlatNode[] {
  return nodes.flatMap((node) => [{ node, depth }, ...(node.children?.length && expanded.value.has(node.id) ? flatten(node.children, depth + 1) : [])])
}

const flatNodes = computed(() => flatten(tree.value))
const visibleNodes = computed(() => flatNodes.value.filter(({ node }) => !treeQuery.value || `${node.label} ${node.code}`.toLowerCase().includes(treeQuery.value.toLowerCase())))
const visibleItems = computed(() => items.value.filter((item) => !itemQuery.value || `${item.name} ${item.value}`.toLowerCase().includes(itemQuery.value.toLowerCase())))
function collectGroupIds(nodes: any[]): string[] {
  return nodes.flatMap((node) => [
    ...(node.kind === 'GROUP' ? [node.id] : []),
    ...collectGroupIds(node.children || []),
  ])
}

const firstLeaf = () => {
  const walk = (nodes: any[]): any => {
    for (const node of nodes) {
      if (node.kind === 'KEY') return node
      const child = walk(node.children || [])
      if (child) return child
    }
    return null
  }
  return walk(tree.value)
}

function toggleNode(node: any) {
  if (node.kind === 'GROUP') {
    const next = new Set(expanded.value)
    next.has(node.id) ? next.delete(node.id) : next.add(node.id)
    expanded.value = next
  } else {
    selectKey(node)
  }
}

async function selectKey(node: any) {
  selectedKey.value = node
  try {
    const data = await parametersApi.items(node.id)
    items.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '参数项加载失败')
  }
}

async function load() {
  try {
    tree.value = await parametersApi.tree()
    expanded.value = new Set(collectGroupIds(tree.value))
    const leaf = firstLeaf()
    if (leaf) await selectKey(leaf)
  } catch (exc: any) {
    app.showToast(exc?.message || '参数树加载失败')
  }
}

async function toggleItem(item: any) {
  try {
    await parametersApi.toggleItem(item.id)
    await selectKey(selectedKey.value)
    app.showToast(`${item.name}已${item.status === '启用' ? '停用' : '启用'}`)
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

async function editItem(item: any) {
  const value = window.prompt(`修改「${item.name}」的参数值`, item.value)
  if (value === null) return
  try {
    await parametersApi.updateItem(item.id, { value })
    await selectKey(selectedKey.value)
    app.showToast('参数项已保存')
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

function copyKey() {
  if (!selectedKey.value) return
  navigator.clipboard?.writeText(selectedKey.value.code)
  app.showToast('参数键标识已复制')
}

function addRoot() {
  if (!rootName.value.trim()) return
  tree.value = [...tree.value, { id: `local-${Date.now()}`, label: rootName.value, code: `custom.${Date.now()}`, kind: 'GROUP', children: [] }]
  expanded.value = new Set([...expanded.value, tree.value[tree.value.length - 1].id])
  rootName.value = ''
  creatingRoot.value = false
  app.showToast('根节点已创建')
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading parameter-page-heading">
    <div><p>系统管理 / 参数配置</p><h1>参数配置</h1><span>以参数键组织多环境业务配置，统一管理参数项及生效状态</span></div>
    <button class="primary-button" @click="creatingRoot = true"><Plus :size="17" />新建根节点</button>
  </section>

  <section class="parameter-workspace">
    <aside class="parameter-tree-panel">
      <div class="parameter-panel-heading"><div><strong>参数键</strong><span>{{ tree.length }} 个根节点</span></div><button @click="creatingRoot = true"><Plus :size="16" /></button></div>
      <div class="parameter-tree-search"><Search :size="15" /><input v-model="treeQuery" placeholder="搜索参数键" /></div>
      <div v-if="creatingRoot" class="create-root-form" style="margin: 0 12px 8px; padding: 5px; display: flex; align-items: center; gap: 4px; border: 1px solid #cfc6ec; border-radius: 8px">
        <input v-model="rootName" placeholder="输入根节点名称" style="flex: 1; height: 25px; border: 0; font-size: 10px" @keyup.enter="addRoot" />
        <button style="width: 25px; height: 25px; color: #fff; background: #7059d2; border-radius: 6px" @click="addRoot"><Check :size="14" /></button>
        <button style="width: 25px; height: 25px" @click="creatingRoot = false"><X :size="14" /></button>
      </div>
      <div class="parameter-tree">
        <div v-for="{ node, depth } in visibleNodes" :key="node.id" :class="['parameter-tree-row', { selected: selectedKey?.id === node.id }]" :style="{ paddingLeft: `${12 + depth * 18}px` }" @click="toggleNode(node)">
          <button v-if="node.kind === 'GROUP'" class="tree-toggle"><ChevronRight :size="14" :class="{ expanded: expanded.has(node.id) }" /></button>
          <span v-else class="tree-spacer" />
          <button class="tree-node-main">
            <FolderOpen v-if="node.kind === 'GROUP' && expanded.has(node.id)" :size="16" />
            <Folder v-else-if="node.kind === 'GROUP'" :size="16" />
            <KeyRound v-else :size="15" />
            <span>{{ node.label }}</span>
          </button>
        </div>
      </div>
      <div class="parameter-tree-footer"><KeyRound :size="13" />叶子节点代表可配置的参数键</div>
    </aside>

    <div class="parameter-detail-panel">
      <div class="parameter-detail-header">
        <div class="parameter-title-icon"><KeyRound :size="19" /></div>
        <div><span>当前参数键</span><h2>{{ selectedKey?.label || '请选择参数键' }}</h2><code>{{ selectedKey?.code || '—' }}</code></div>
        <div class="parameter-header-actions"><button @click="copyKey">复制键名</button><button class="primary-button" @click="app.showToast('新增参数项面板已准备就绪')"><Plus :size="16" />新增参数项</button></div>
      </div>
      <div class="parameter-detail-meta"><div><span>参数项</span><strong>{{ items.length }}</strong></div><div><span>启用项</span><strong>{{ items.filter((item) => item.status === '启用').length }}</strong></div><div><span>最后更新</span><strong>{{ items[0]?.updatedAt || '—' }}</strong></div></div>
      <div class="parameter-table-toolbar">
        <div class="table-search"><Search :size="17" /><input v-model="itemQuery" placeholder="搜索参数项名称或值…" /></div>
        <div style="display: flex; gap: 7px"><button style="height: 34px; padding: 0 10px; border: 1px solid #e2dfe6; border-radius: 8px; color: #6e6976; background: #fff; font-size: 10px"><Filter :size="16" />状态筛选</button><button style="height: 34px; padding: 0 10px; border: 1px solid #e2dfe6; border-radius: 8px; color: #6e6976; background: #fff; font-size: 10px"><Settings2 :size="16" />列设置</button></div>
      </div>
      <div class="table-wrap parameter-table-wrap">
        <table class="parameter-items-table">
          <thead><tr><th>参数项名称</th><th>参数值</th><th>说明</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="item in visibleItems" :key="item.id">
              <td><div class="parameter-item-name"><span>{{ item.name.charAt(0) }}</span><strong>{{ item.name }}</strong></div></td>
              <td><code class="parameter-value">{{ item.value }}</code></td><td><span class="parameter-description">{{ item.description }}</span></td>
              <td><button :class="['parameter-switch', { on: item.status === '启用' }]" @click="toggleItem(item)"><i />{{ item.status }}</button></td>
              <td>{{ item.updatedAt }}</td>
              <td><button class="row-action" @click="editItem(item)">编辑</button><button class="row-more"><MoreHorizontal :size="17" /></button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="parameter-table-footer">共 {{ items.length }} 个参数项<span>修改参数后，将在保存并发布后生效</span></div>
    </div>
  </section>
</template>
