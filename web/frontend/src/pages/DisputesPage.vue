<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Gavel, MoreHorizontal, Search, ShieldAlert } from 'lucide-vue-next'
import { disputesApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'

const app = useAppStore()
const auth = useAuthStore()
const rows = ref<any[]>([])
const query = ref('')
const selected = ref<any>(null)
const drawerOpen = ref(false)

async function load() {
  try {
    const data = await disputesApi.list({ keyword: query.value, page: 1, pageSize: 50 })
    rows.value = data.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '纠纷数据加载失败')
  }
}

function open(row: any) {
  selected.value = row
  drawerOpen.value = true
}

const mediateNote = ref('')
const resolveForm = ref({ conclusionType: 'CONTINUE', conclusion: '', amountYuan: '' })

const conclusionTypes = [
  { key: 'CONTINUE', label: '继续履约（解冻资金，订单恢复）' },
  { key: 'CANCEL_REFUND', label: '取消订单并全额退款' },
  { key: 'FORCE_RELEASE', label: '强制放款给卖家' },
  { key: 'PARTIAL_REFUND', label: '部分退款（需填金额）' },
  { key: 'CREDIT', label: '信用处理（记入违规）' },
  { key: 'ACCOUNT_FREEZE', label: '冻结被申请人账号' },
]

async function mediate() {
  if (!mediateNote.value.trim()) {
    app.showToast('请填写调解记录')
    return
  }
  try {
    await disputesApi.mediate(selected.value.id, mediateNote.value.trim())
    app.showToast('调解记录已保存')
    mediateNote.value = ''
    drawerOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function resolve() {
  const form = resolveForm.value
  if (form.conclusion.trim().length < 5) {
    app.showToast('处理结论必填（不少于 5 个字）')
    return
  }
  const payload: any = { conclusionType: form.conclusionType, conclusion: form.conclusion.trim() }
  if (form.conclusionType === 'PARTIAL_REFUND') {
    const cents = Math.round(Number.parseFloat(form.amountYuan || '0') * 100)
    if (!cents) {
      app.showToast('部分退款必须填写金额')
      return
    }
    payload.amountCents = cents
  }
  if (['CANCEL_REFUND', 'FORCE_RELEASE', 'PARTIAL_REFUND'].includes(form.conclusionType)
    && !window.confirm('资金类结论将进入双人复核（由另一位管理员执行），确认提交？')) return
  try {
    await disputesApi.resolve(selected.value.id, payload)
    app.showToast('处理结论已提交')
    drawerOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '处理失败')
  }
}

async function freeze() {
  const reason = window.prompt('请输入冻结资金原因')
  if (!reason) return
  try {
    await disputesApi.freeze(selected.value.id, reason)
    app.showToast('托管资金已冻结')
    drawerOpen.value = false
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="page-heading list-heading">
    <div><p>资金与治理 / 纠纷调解</p><h1>纠纷调解</h1><span>查看双方陈述与证据，出具处理结论，必要时冻结或划扣托管资金</span></div>
    <button class="primary-button" @click="app.showToast('调解指引已打开')"><Gavel :size="17" />调解指引</button>
  </section>
  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索纠纷号、订单号或用户…" @keyup.enter="load" /></div>
      <div class="toolbar-actions"><button><ShieldAlert :size="16" />高风险优先</button><button><MoreHorizontal :size="17" /></button></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>纠纷号 / 订单号</th><th>发起人</th><th>被申请人</th><th>涉及金额</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td><div class="primary-cell"><span class="row-icon">纠</span><div><strong>{{ row.disputeNo }}</strong><em>{{ row.orderNo }}</em></div></div></td>
            <td>{{ row.initiator }}</td><td>{{ row.respondent }}</td><td>{{ row.amount }}</td>
            <td><StatusBadge :value="row.status" /></td><td>{{ row.createdAt }}</td>
            <td><button class="row-action" @click="open(row)">调解</button><button class="row-more"><MoreHorizontal :size="17" /></button></td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无纠纷" description="当前没有需要处理的纠纷" />
    </div>
    <div class="pagination"><span>共 {{ rows.length }} 条记录</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <NiDrawer :open="drawerOpen" :title="selected?.disputeNo || '纠纷详情'" eyebrow="纠纷调解" @close="drawerOpen = false">
    <template v-if="selected">
      <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 16px">
        <Gavel :size="18" style="color: #6852c5" />
        <div style="flex: 1"><span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">关联订单</span><strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ selected.orderNo }}</strong></div>
        <StatusBadge :value="selected.status" />
      </div>
      <h4 class="section-title">双方信息</h4>
      <div class="form-grid">
        <label><span>发起人</span><input :value="selected.initiator" disabled /></label>
        <label><span>被申请人</span><input :value="selected.respondent" disabled /></label>
        <label><span>涉及金额</span><input :value="selected.amount" disabled /></label>
        <label><span>调解人</span><input :value="selected.mediator || '待分配'" disabled /></label>
      </div>
      <h4 class="section-title" style="margin-top: 20px">双方陈述</h4>
      <div style="padding: 12px; border: 1px solid #e9e6ed; border-radius: 8px; color: #716d79; font-size: var(--font-size-body); line-height: 1.7">{{ selected.statement || '暂无陈述' }}</div>
      <h4 class="section-title" style="margin-top: 20px">调解记录</h4>
      <label style="display: block"><span style="display: block; font-size: var(--font-size-body); color: #958b9f; margin-bottom: 4px">内部调解备注（不直接发给用户）</span>
        <textarea v-model="mediateNote" placeholder="记录沟通要点与建议方向" style="width: 100%; min-height: 56px" /></label>
      <h4 class="section-title" style="margin-top: 20px">处理结论</h4>
      <div style="padding: 12px; border: 1px solid #e9e6ed; border-radius: 8px; color: #716d79; font-size: var(--font-size-body); line-height: 1.7; margin-bottom: 10px">{{ selected.conclusion || '尚未出具结论' }}</div>
      <div class="form-grid">
        <label class="full"><span>结论类型</span>
          <select v-model="resolveForm.conclusionType">
            <option v-for="item in conclusionTypes" :key="item.key" :value="item.key">{{ item.label }}</option>
          </select>
        </label>
        <label v-if="resolveForm.conclusionType === 'PARTIAL_REFUND'" class="full"><span>部分退款金额（元）</span>
          <input v-model="resolveForm.amountYuan" placeholder="例如：64.00" />
        </label>
        <label class="full"><span>处理结论（≥5 字；资金类结论进入双人复核）</span>
          <textarea v-model="resolveForm.conclusion" placeholder="例如：核实物品确有问题，取消订单并全额退款" />
        </label>
      </div>
    </template>
    <template #footer>
      <button @click="freeze">冻结资金</button>
      <button @click="mediate">保存调解</button>
      <button v-if="auth.hasPermission('governance:dispute:resolve')" class="primary-button" @click="resolve">出具结论</button>
    </template>
  </NiDrawer>
</template>
