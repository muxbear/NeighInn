<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { MessageCircleMore, MoreHorizontal, Search } from 'lucide-vue-next'
import { feedbackApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'

const app = useAppStore()
const rows = ref<any[]>([])
const query = ref('')

async function load() {
  try {
    const data = await feedbackApi.list({ keyword: query.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '反馈加载失败')
  }
}

async function reply(row: any) {
  const reply = window.prompt(`回复「${row.content}」`, '感谢您的建议，我们已安排跟进。')
  if (!reply) return
  try {
    await feedbackApi.reply(row.id, reply)
    app.showToast('反馈已回复')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '回复失败')
  }
}

async function close(row: any) {
  try {
    await feedbackApi.close(row.id)
    app.showToast('反馈已关闭')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>运营管理 / 投诉建议</p><h1>投诉建议</h1><span>受理居民意见，分级流转并跟踪处理满意度</span></div>
    <button class="primary-button" @click="app.showToast('登记反馈面板已准备就绪')"><MessageCircleMore :size="17" />登记反馈</button>
  </section>
  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索反馈内容或提交人…" @keyup.enter="load" /></div>
      <div class="toolbar-actions"><button>全部状态</button><button><MoreHorizontal :size="17" /></button></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>反馈内容</th><th>提交人</th><th>分类</th><th>跟进人</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id"><td><div class="primary-cell"><span class="row-icon">建</span><strong>{{ row.content }}</strong></div></td><td>{{ row.submitter }}</td><td>{{ row.category }}</td><td>{{ row.assignee }}</td><td><StatusBadge :value="row.status" /></td><td>{{ row.createdAt }}</td><td><button class="row-action" @click="reply(row)">回复</button><button class="row-more" @click="close(row)"><MoreHorizontal :size="17" /></button></td></tr></tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无反馈" />
    </div>
    <div class="pagination"><span>共 {{ rows.length }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>
</template>
