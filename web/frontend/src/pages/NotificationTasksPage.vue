<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, Filter, MoreHorizontal, Plus, Search, Settings2 } from 'lucide-vue-next'
import { tasksApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const rows = ref<any[]>([])
const query = ref('')
const drawerOpen = ref(false)
const form = ref({ name: '', channels: '站内信 · Push', target: '全部用户', template: '' })
const total = computed(() => rows.value.length)

async function load() {
  try {
    const data = await tasksApi.list({ keyword: query.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '通知任务加载失败')
  }
}

async function send(row: any) {
  try {
    await tasksApi.send(row.id)
    app.showToast('通知任务已提交发送')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '发送失败')
  }
}

async function save() {
  if (!form.value.name.trim()) {
    app.showToast('请填写任务名称')
    return
  }
  try {
    await tasksApi.create(form.value)
    drawerOpen.value = false
    app.showToast('通知任务已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>运营管理 / 通知任务</p><h1>通知任务</h1><span>统一管理站内信、短信、Push 和服务通知</span></div>
    <button class="primary-button" @click="drawerOpen = true"><Plus :size="17" />新建通知</button>
  </section>
  <section class="summary-row">
    <div><span>全部任务</span><strong>{{ total + 47 }}</strong><em>总量</em></div>
    <div><span>今日发送</span><strong>6</strong><em class="up">较昨日 +12%</em></div>
    <div><span>发送中</span><strong>{{ rows.filter((row) => row.status.includes('发送')).length + 5 }}</strong><em class="warn">需要关注</em></div>
    <div><span>本月完成率</span><strong>94.6%</strong><em class="up">稳步提升</em></div>
  </section>
  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索任务名称、渠道…" @keyup.enter="load" /></div>
      <div class="toolbar-actions"><button><Filter :size="16" />筛选<ChevronDown :size="14" /></button><button><Settings2 :size="16" />列设置</button><button><MoreHorizontal :size="17" /></button></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>任务名称</th><th>渠道</th><th>目标用户</th><th>送达 / 阅读</th><th>状态</th><th>发送时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td><div class="primary-cell"><span class="row-icon">{{ row.name.charAt(0) }}</span><strong>{{ row.name }}</strong></div></td>
            <td><span class="medium-cell">{{ row.channels }}</span></td><td>{{ row.target }}</td><td>{{ row.delivery }}</td>
            <td><StatusBadge :value="row.status" /></td><td>{{ row.sentAt }}</td>
            <td><button class="row-action" @click="send(row)">发送</button><button class="row-more"><MoreHorizontal :size="17" /></button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无通知任务" />
    </div>
    <div class="pagination"><span>共 {{ total }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <NiDrawer :open="drawerOpen" title="新建通知任务" eyebrow="触达中心" @close="drawerOpen = false">
    <div class="form-grid">
      <label class="full"><span>任务名称 *</span><input v-model="form.name" /></label>
      <label><span>通知渠道</span><input v-model="form.channels" /></label>
      <label><span>目标用户</span><input v-model="form.target" /></label>
      <label class="full"><span>通知内容</span><textarea v-model="form.template" /></label>
    </div>
    <template #footer><button @click="drawerOpen = false">取消</button><button class="primary-button" @click="save">创建</button></template>
  </NiDrawer>
</template>
