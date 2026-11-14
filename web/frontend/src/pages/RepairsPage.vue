<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { MoreHorizontal, Search, Wrench } from 'lucide-vue-next'
import { repairApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'

const app = useAppStore()
const rows = ref<any[]>([])
const query = ref('')

async function load() {
  try {
    const data = await repairApi.list({ communityId: app.currentCommunityId, keyword: query.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '工单加载失败')
  }
}

async function assign(row: any) {
  const assignee = window.prompt('请输入处理人', '工程部 · 徐工')
  if (!assignee) return
  try {
    await repairApi.assign(row.id, assignee)
    app.showToast('工单已派发')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '派单失败')
  }
}

async function close(row: any) {
  try {
    await repairApi.close(row.id)
    app.showToast('工单已完成')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>运营管理 / 报事报修</p><h1>报事报修</h1><span>从上报、派单到回访的工单全生命周期管理</span></div>
    <button class="primary-button" @click="app.showToast('新建工单面板已准备就绪')"><Wrench :size="17" />新建工单</button>
  </section>
  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索工单编号、事项或位置…" @keyup.enter="load" /></div>
      <div class="toolbar-actions"><button>全部状态</button><button><MoreHorizontal :size="17" /></button></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>工单编号 / 事项</th><th>报修人</th><th>位置</th><th>处理人</th><th>状态</th><th>时效</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><div class="primary-cell"><span class="row-icon">修</span><div><strong>{{ row.orderNo }} · {{ row.title }}</strong><em>{{ row.priority }}</em></div></div></td><td>{{ row.reporter }}</td><td>{{ row.location }}</td><td>{{ row.assignee }}</td><td><StatusBadge :value="row.status" /></td><td>{{ row.sla }}</td><td><button class="row-action" @click="assign(row)">派单</button><button class="row-action" style="margin-left: 8px" @click="close(row)">完成</button></td></tr></tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无工单" />
    </div>
    <div class="pagination"><span>共 {{ rows.length }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>
</template>
