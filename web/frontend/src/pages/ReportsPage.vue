<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Flag, Search, ShieldAlert } from 'lucide-vue-next'
import { reportsApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const auth = useAuthStore()
const rows = ref<any[]>([])
const query = ref('')
const statusFilter = ref('OPEN')
const selected = ref<any>(null)
const drawerOpen = ref(false)
const handleAction = ref('DISMISS')
const handleNote = ref('')

const actions = [
  { key: 'DISMISS', label: '驳回举报' },
  { key: 'OFFLINE_CONTENT', label: '下架内容' },
  { key: 'DELETE_COMMENT', label: '删除留言' },
  { key: 'MUTE_USER', label: '禁言用户' },
  { key: 'BAN_USER', label: '封禁账号' },
]

async function load() {
  try {
    const data = await reportsApi.list({ keyword: query.value, status: statusFilter.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '举报数据加载失败')
  }
}

function open(row: any) {
  selected.value = row
  handleAction.value = 'DISMISS'
  handleNote.value = ''
  drawerOpen.value = true
}

async function submit() {
  try {
    await reportsApi.handle(selected.value.id, { action: handleAction.value, note: handleNote.value })
    app.showToast('举报已处理并通知举报人')
    drawerOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '处理失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>资金与治理 / 举报处理</p><h1>举报处理</h1><span>分类处理物品/用户/会话/留言/私信举报（W05-03）；处置联动下架与账号处罚</span></div>
    <button class="primary-button" @click="load"><Flag :size="17" />刷新</button>
  </section>
  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索原因或详情…" @keyup.enter="load" /></div>
      <div class="toolbar-actions">
        <button @click="statusFilter = 'OPEN'; load()">待处理</button>
        <button @click="statusFilter = ''; load()">全部</button>
        <button><ShieldAlert :size="16" />高风险优先</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>举报对象</th><th>原因</th><th>举报人</th><th>证据</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td><div class="primary-cell"><span class="row-icon">举</span><div><strong>{{ row.targetTitle || row.targetId }}</strong><em>{{ row.targetType }}</em></div></div></td>
            <td>{{ row.reason }}</td>
            <td>{{ row.reporter }}</td>
            <td>{{ (row.evidence || []).length }} 份</td>
            <td><StatusBadge :value="row.status" /></td>
            <td>{{ row.createdAt }}</td>
            <td><button class="row-action" @click="open(row)">处理</button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无举报" description="当前没有待处理的举报" />
    </div>
  </section>

  <NiDrawer :open="drawerOpen" :title="selected ? `举报 · ${selected.targetTitle || selected.targetId}` : '举报处理'" eyebrow="举报处理" @close="drawerOpen = false">
    <template v-if="selected">
      <h4 class="section-title">举报信息</h4>
      <div class="form-grid">
        <label><span>对象类型</span><input :value="selected.targetType" disabled /></label>
        <label><span>举报人</span><input :value="selected.reporter" disabled /></label>
        <label class="full"><span>原因</span><input :value="selected.reason" disabled /></label>
        <label class="full"><span>详情</span><textarea :value="selected.detail || '—'" disabled /></label>
      </div>
      <h4 class="section-title" style="margin-top: 20px">处理方式</h4>
      <div class="form-grid">
        <label class="full"><span>处理动作</span>
          <select v-model="handleAction">
            <option v-for="action in actions" :key="action.key" :value="action.key">{{ action.label }}</option>
          </select>
        </label>
        <label class="full"><span>处理备注（将通知举报人）</span>
          <textarea v-model="handleNote" placeholder="例如：核实属实，已下架违规内容" />
        </label>
      </div>
    </template>
    <template #footer>
      <button @click="drawerOpen = false">取消</button>
      <button v-if="auth.hasPermission('governance:report:handle')" class="primary-button" @click="submit">提交处理</button>
    </template>
  </NiDrawer>
</template>
