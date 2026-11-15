<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { FileClock, MoreHorizontal, Search } from 'lucide-vue-next'
import { auditApi } from '@/api'
import { useAppStore } from '@/stores/app'
import EmptyState from '@/components/EmptyState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const rows = ref<any[]>([])
const query = ref('')
const selected = ref<any>(null)
const drawerOpen = ref(false)

async function load() {
  try {
    const data = await auditApi.list({ keyword: query.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '审计日志加载失败')
  }
}

async function open(row: any) {
  try {
    selected.value = await auditApi.detail(row.id)
    drawerOpen.value = true
  } catch (exc: any) {
    app.showToast(exc?.message || '详情加载失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索操作人、动作或追踪号…" @keyup.enter="load" /></div>
      <div class="toolbar-actions"><button>近 7 天</button><button><MoreHorizontal :size="17" /></button><button class="primary-button" @click="app.showToast('审计日志导出任务已创建')"><FileClock :size="16" />导出日志</button></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>结果</th><th>IP</th><th>追踪号</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>{{ row.createdLabel || row.createdAt }}</td><td>{{ row.actorName }}</td><td><span class="medium-cell">{{ row.action }}</span></td>
            <td>{{ row.resourceType }} / {{ row.resourceId }}</td><td><StatusBadge :value="row.result === 'SUCCESS' ? '成功' : row.result" /></td>
            <td>{{ row.ip }}</td><td><code>{{ row.traceId }}</code></td>
            <td><button class="row-action" @click="open(row)">详情</button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无审计记录" />
    </div>
    <div class="pagination"><span>共 {{ rows.length }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <NiDrawer :open="drawerOpen" title="审计详情" eyebrow="操作审计" @close="drawerOpen = false">
    <template v-if="selected">
      <div class="form-grid">
        <label><span>操作人</span><input :value="selected.actorName" disabled /></label>
        <label><span>动作</span><input :value="selected.action" disabled /></label>
        <label><span>对象</span><input :value="`${selected.resourceType} / ${selected.resourceId}`" disabled /></label>
        <label><span>追踪号</span><input :value="selected.traceId" disabled /></label>
        <label><span>IP</span><input :value="selected.ip" disabled /></label>
        <label><span>结果</span><input :value="selected.result" disabled /></label>
      </div>
      <h4 class="section-title" style="margin-top: 20px">前后快照</h4>
      <pre style="padding: 12px; border: 1px solid #e9e6ed; border-radius: 8px; background: #faf9fb; color: #5d5864; font-size: var(--font-size-caption); white-space: pre-wrap">{{ JSON.stringify({ before: selected.beforeSnapshot, after: selected.afterSnapshot }, null, 2) }}</pre>
    </template>
  </NiDrawer>
</template>
