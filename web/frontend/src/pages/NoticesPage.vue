<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, Filter, MoreHorizontal, Plus, Search, Settings2 } from 'lucide-vue-next'
import { noticesApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const rows = ref<any[]>([])
const query = ref('')
const drawerOpen = ref(false)
const form = ref({ title: '', scope: '全部社区', publisher: '运营中心', content: '' })
const total = computed(() => rows.value.length)
const summary = computed(() => [
  { label: '全部记录', value: total.value + 47, note: '总量' },
  { label: '今日新增', value: 6, note: '较昨日 +12%', up: true },
  { label: '待处理', value: rows.value.filter((row) => row.status.includes('待')).length + 5, note: '需要关注', warn: true },
  { label: '本月完成率', value: '94.6%', note: '稳步提升', up: true },
])

async function load() {
  try {
    const data = await noticesApi.list({ keyword: query.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '公告加载失败')
  }
}

async function publish(row: any) {
  try {
    await noticesApi.publish(row.id)
    app.showToast('公告已发布')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '发布失败')
  }
}

async function save() {
  if (!form.value.title.trim()) {
    app.showToast('请填写公告标题')
    return
  }
  try {
    await noticesApi.create({ ...form.value, communityId: app.currentCommunityId })
    drawerOpen.value = false
    app.showToast('公告已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>运营管理 / 公告管理</p><h1>公告管理</h1><span>编辑、定时发布并置顶社区公告</span></div>
    <button class="primary-button" @click="drawerOpen = true"><Plus :size="17" />发布公告</button>
  </section>

  <section class="summary-row">
    <div v-for="item in summary" :key="item.label">
      <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
      <em :class="{ up: item.up, warn: item.warn }">{{ item.note }}</em>
    </div>
  </section>

  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索公告标题、范围或发布人…" @keyup.enter="load" /></div>
      <div class="toolbar-actions">
        <button><Filter :size="16" />筛选<ChevronDown :size="14" /></button>
        <button><Settings2 :size="16" />列设置</button>
        <button><MoreHorizontal :size="17" /></button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>公告标题</th><th>覆盖范围</th><th>发布人</th><th>阅读进度</th><th>状态</th><th>发布时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td><div class="primary-cell"><span class="row-icon">{{ row.title.charAt(0) }}</span><strong>{{ row.title }}</strong></div></td>
            <td><span class="medium-cell">{{ row.scope }}</span></td>
            <td>{{ row.publisher }}</td><td>{{ row.readProgress }}</td>
            <td><StatusBadge :value="row.status" /></td><td>{{ row.publishedAt }}</td>
            <td><button class="row-action" @click="publish(row)">发布</button><button class="row-more"><MoreHorizontal :size="17" /></button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无公告" description="点击发布公告开始运营" />
    </div>
    <div class="pagination"><span>共 {{ total }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <section class="insight-strip">
    <div class="insight-icon"><span>⌘</span></div>
    <div><strong>运营建议</strong><p>基于当前数据，建议优先处理临近超时项目，并关注近 7 日新增记录的转化与完成情况。</p></div>
    <button @click="app.showToast('已创建智能分析任务')">查看分析</button>
  </section>

  <NiDrawer :open="drawerOpen" title="发布公告" eyebrow="公告管理" @close="drawerOpen = false">
    <div class="form-grid">
      <label class="full"><span>公告标题 *</span><input v-model="form.title" placeholder="请输入公告标题" /></label>
      <label><span>覆盖范围</span><input v-model="form.scope" /></label>
      <label><span>发布人</span><input v-model="form.publisher" /></label>
      <label class="full"><span>公告正文</span><textarea v-model="form.content" placeholder="请输入公告正文" /></label>
    </div>
    <template #footer><button @click="drawerOpen = false">取消</button><button class="primary-button" @click="save">发布</button></template>
  </NiDrawer>
</template>
