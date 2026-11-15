<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, Filter, MoreHorizontal, Plus, Search, Settings2 } from 'lucide-vue-next'
import { usersApi } from '@/api'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const rows = ref<any[]>([])
const query = ref('')
const drawerOpen = ref(false)
const form = ref({ accountType: '社区居民', name: '', phone: '', identity: '', communityName: '云栖里社区', roleName: '社区居民', status: '正常' })
const total = computed(() => rows.value.length)

async function load() {
  try {
    const data = await usersApi.list({ keyword: query.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '用户加载失败')
  }
}

async function toggle(row: any) {
  try {
    await usersApi.toggle(row.id)
    app.showToast('用户状态已更新')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

async function save() {
  if (!form.value.name.trim()) {
    app.showToast('请填写用户姓名')
    return
  }
  try {
    await usersApi.create(form.value)
    drawerOpen.value = false
    app.showToast('用户已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>运营管理 / 用户管理</p><h1>用户管理</h1><span>检索与处置 C 端业主账号；注册与实名认证仅在移动端完成（W07 边界，保证审计链）</span></div>
  </section>
  <section class="summary-row">
    <div><span>全部用户</span><strong>{{ total + 47 }}</strong><em>总量</em></div>
    <div><span>今日新增</span><strong>6</strong><em class="up">较昨日 +12%</em></div>
    <div><span>待处理</span><strong>{{ rows.filter((row) => row.status !== '正常').length + 5 }}</strong><em class="warn">需要关注</em></div>
    <div><span>本月活跃率</span><strong>94.6%</strong><em class="up">稳步提升</em></div>
  </section>
  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索姓名、手机号或社区…" @keyup.enter="load" /></div>
      <div class="toolbar-actions"><button><Filter :size="16" />筛选<ChevronDown :size="14" /></button><button><Settings2 :size="16" />列设置</button><button><MoreHorizontal :size="17" /></button></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>用户</th><th>手机号</th><th>身份 / 社区</th><th>角色</th><th>状态</th><th>最近活跃</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td><div class="primary-cell"><span class="row-icon">{{ row.name.charAt(0) }}</span><strong>{{ row.name }}</strong></div></td>
            <td><span class="medium-cell">{{ row.phone }}</span></td><td>{{ row.identity }}</td><td>{{ row.roleName }}</td>
            <td><StatusBadge :value="row.status" /></td><td>{{ row.lastActive }}</td>
            <td><button class="row-action" @click="toggle(row)">{{ row.status === '正常' ? '停用' : '启用' }}</button><button class="row-more"><MoreHorizontal :size="17" /></button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无用户" />
    </div>
    <div class="pagination"><span>共 {{ total }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <NiDrawer :open="drawerOpen" title="新增用户" eyebrow="用户管理" @close="drawerOpen = false">
    <div class="form-grid">
      <label><span>用户类型</span><input v-model="form.accountType" /></label>
      <label><span>姓名 *</span><input v-model="form.name" /></label>
      <label><span>手机号</span><input v-model="form.phone" /></label>
      <label><span>身份</span><input v-model="form.identity" /></label>
      <label><span>社区</span><input v-model="form.communityName" /></label>
      <label><span>角色</span><input v-model="form.roleName" /></label>
    </div>
    <template #footer><button @click="drawerOpen = false">取消</button><button class="primary-button" @click="save">保存</button></template>
  </NiDrawer>
</template>
