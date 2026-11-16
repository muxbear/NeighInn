<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Building2, Camera, ChevronDown, Filter, Home, Pencil, Plus, Search, Settings2, ShieldCheck, Trash2, UserRound, Users, X } from 'lucide-vue-next'
import { certificationsApi, residentApi } from '@/api'
import { fmtDateTime, mapStatus } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import CommunityFilterBar from '@/components/CommunityFilterBar.vue'

const app = useAppStore()
const auth = useAuthStore()
const rows = ref<any[]>([])
const summary = ref<any>({ total: 0, owner: 0, family: 0, pending: 0 })
const activeTab = ref('全部人员')
const query = ref('')
const page = ref(1)
const total = ref(0)
const drawerOpen = ref(false)
const editing = ref<any>(null)
const form = ref<any>({})

// 认证材料查看：点击身份认证 / 业主认证状态徽标后加载签名 URL 照片。
const certViewerOpen = ref(false)
const certViewerLoading = ref(false)
const certViewerError = ref('')
const certViewerTitle = ref('')
const certViewerData = ref<any>(null)
const certPhotoErrors = ref<Record<string, boolean>>({})

const AVATAR_TONES = ['violet', 'blue', 'green', 'orange', 'plum', 'teal']

const tabs = ['全部人员', '业主', '家属', '租户', '商务人员']
const community = computed(() => app.currentCommunity)
const summaryCards = computed(() => [
  { label: '全部人员', value: summary.value.total, icon: Users, tone: 'violet' },
  { label: '业主', value: summary.value.owner, icon: Home, tone: 'blue' },
  { label: '家属与租户', value: summary.value.family, icon: UserRound, tone: 'green' },
  { label: '待完成认证', value: summary.value.pending, icon: ShieldCheck, tone: 'orange' },
])

async function load() {
  try {
    const params: any = { communityId: app.currentCommunityId, page: page.value, pageSize: 50, keyword: query.value }
    if (activeTab.value !== '全部人员') params.identity = activeTab.value
    const [data, summaryData] = await Promise.all([
      residentApi.list(params),
      residentApi.summary(app.currentCommunityId),
    ])
    rows.value = data.items || []
    total.value = data.total || 0
    summary.value = summaryData
  } catch (exc: any) {
    app.showToast(exc?.message || '业主档案加载失败')
  }
}

function openCreate() {
  editing.value = null
  form.value = {
    communityId: app.currentCommunityId, name: '', gender: '女', phone: '', identity: '业主',
    building: '', relationship: '房屋产权人', certification: '未认证', certificationNo: '',
    level: '普通用户', status: '正常',
  }
  drawerOpen.value = true
}

function openEdit(row: any) {
  editing.value = row
  form.value = { ...row, communityId: Number(row.communityId) }
  drawerOpen.value = true
}

async function save() {
  if (!form.value.name?.trim()) {
    app.showToast('请填写人员姓名')
    return
  }
  const payload: any = { ...form.value }
  // 列表返回的为脱敏手机号；未重新输入时不提交，避免覆盖真实号码。
  if (editing.value && String(payload.phone || '').includes('*')) delete payload.phone
  // 加入时间不在表单中维护，避免把列表展示值（含占位符）回写成业务数据。
  delete payload.joinedAt
  try {
    if (editing.value) await residentApi.update(editing.value.id, payload)
    else await residentApi.create(payload)
    drawerOpen.value = false
    app.showToast(editing.value ? '人员信息已更新' : '人员档案已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function remove(row: any) {
  if (!window.confirm(`确定删除“${row.name}”的社区人员档案吗？`)) return
  try {
    await residentApi.remove(row.id)
    app.showToast('人员档案已删除')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

function avatarTone(row: any) {
  const key = String(row.avatarKey || row.nickname || row.name || '')
  let hash = 0
  for (let index = 0; index < key.length; index += 1) {
    hash = (hash * 31 + key.charCodeAt(index)) >>> 0
  }
  return AVATAR_TONES[hash % AVATAR_TONES.length]
}

function avatarText(row: any) {
  return (row.nickname || row.name || '?').charAt(0)
}

function certOf(row: any, kind: 'realname' | 'owner') {
  return kind === 'realname' ? row.realnameCert : row.ownerCert
}

async function openCertViewer(row: any, kind: 'realname' | 'owner') {
  const cert = certOf(row, kind)
  if (!cert?.id) {
    app.showToast(kind === 'realname' ? '该人员暂无身份认证记录' : '该人员暂无业主认证记录')
    return
  }
  certViewerTitle.value = `${kind === 'realname' ? '身份认证' : '业主认证'} · ${row.name}`
  certViewerOpen.value = true
  certViewerLoading.value = true
  certViewerError.value = ''
  certViewerData.value = null
  certPhotoErrors.value = {}
  try {
    certViewerData.value = await certificationsApi.detail(cert.id)
  } catch (exc: any) {
    certViewerError.value = exc?.message || '认证材料加载失败'
  } finally {
    certViewerLoading.value = false
  }
}

function closeCertViewer() {
  certViewerOpen.value = false
  certViewerData.value = null
  certViewerError.value = ''
  certPhotoErrors.value = {}
}

function onCertPhotoError(objectKey: string) {
  certPhotoErrors.value = { ...certPhotoErrors.value, [objectKey]: true }
}

onMounted(load)
watch(() => app.currentCommunityId, () => {
  // 与社区运维一致：切换社区后重置身份页签与列表搜索。
  activeTab.value = '全部人员'
  query.value = ''
  page.value = 1
  load()
})
</script>

<template>
  <CommunityFilterBar owner-label="人员档案归属小区" scope-note="人员列表仅展示所选小区" />

  <section class="resident-summary-grid">
    <div v-for="card in summaryCards" :key="card.label">
      <span :class="card.tone"><component :is="card.icon" :size="18" /></span>
      <div><p>{{ card.label }}</p><strong>{{ card.value }}</strong></div>
    </div>
  </section>

  <section class="resident-directory-panel">
    <div class="resident-tabs">
      <button v-for="tab in tabs" :key="tab" :class="{ active: activeTab === tab }" @click="activeTab = tab; page = 1; load()">
        {{ tab }}<em>{{ tab === '全部人员' ? summary.total : rows.filter((row) => row.identity === tab).length }}</em>
      </button>
    </div>
    <div class="resident-toolbar">
      <div class="table-search"><Search :size="17" /><input v-model="query" placeholder="搜索姓名、昵称、房屋或认证编号…" @keyup.enter="load" /></div>
      <div>
        <button><Filter :size="16" />认证状态<ChevronDown :size="14" /></button>
        <button><Settings2 :size="16" />列设置</button>
        <button v-if="auth.hasPermission('community:resident:create')" class="primary-button" @click="openCreate"><Plus :size="16" />新增人员</button>
      </div>
    </div>
    <div class="table-wrap resident-table-wrap">
      <table class="resident-table">
        <thead>
          <tr>
            <th>头像</th><th>姓名</th><th>昵称</th><th>身份类型</th><th>房屋 / 商铺</th><th>信用</th>
            <th>身份认证</th><th>业主认证</th><th>手机号</th><th>邮箱</th><th>个人描述</th><th>账号状态</th><th>加入时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <span :class="['resident-avatar', avatarTone(row)]" :title="row.nickname || row.name">{{ avatarText(row) }}</span>
            </td>
            <td><span class="cell-ellipsis sm" :title="row.name">{{ row.name }}</span></td>
            <td><span class="cell-ellipsis sm" :title="row.nickname || '—'">{{ row.nickname || '—' }}</span></td>
            <td><span :class="['identity-tag', row.identity]">{{ row.identity }}</span></td>
            <td><div class="resident-house-cell" :title="row.building || '—'"><strong>{{ row.building || '—' }}</strong><span>{{ row.relationship || '' }}</span></div></td>
            <td><div class="resident-credit"><strong>{{ row.creditScore ?? '—' }}</strong><em v-if="row.creditLevel">{{ row.creditLevel }}</em></div></td>
            <td>
              <button
                class="cert-status-button"
                :class="{ clickable: !!row.realnameCert?.id }"
                :title="row.realnameCert?.id ? '查看身份认证照片' : '暂无身份认证材料'"
                @click="openCertViewer(row, 'realname')"
              >
                <StatusBadge :value="row.realnameStatusLabel || '未认证'" />
                <Camera v-if="row.realnameCert?.id" :size="12" />
              </button>
            </td>
            <td>
              <button
                class="cert-status-button"
                :class="{ clickable: !!row.ownerCert?.id }"
                :title="row.ownerCert?.id ? '查看业主认证照片' : '暂无业主认证材料'"
                @click="openCertViewer(row, 'owner')"
              >
                <StatusBadge :value="row.certification" />
                <Camera v-if="row.ownerCert?.id" :size="12" />
              </button>
            </td>
            <td>{{ row.phone || '—' }}</td>
            <td><span class="cell-ellipsis md" :title="row.email || '—'">{{ row.email || '—' }}</span></td>
            <td><span class="cell-ellipsis lg" :title="row.bio || '—'">{{ row.bio || '—' }}</span></td>
            <td><StatusBadge :value="row.status" /></td>
            <td>{{ row.joinedAt }}</td>
            <td>
              <div class="row-actions">
                <button
                  v-if="auth.hasPermission('community:resident:update')"
                  class="row-icon-button"
                  aria-label="编辑人员档案"
                  data-tip="编辑人员档案"
                  @click="openEdit(row)"
                ><Pencil :size="15" /></button>
                <button
                  v-if="auth.hasPermission('community:resident:update')"
                  class="row-icon-button danger"
                  aria-label="删除人员档案"
                  data-tip="删除人员档案"
                  @click="remove(row)"
                ><Trash2 :size="15" /></button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length" title="暂无匹配人员" description="请调整身份分类或搜索关键词" />
    </div>
    <div class="resident-table-footer"><span>共 {{ total }} 条人员档案</span><div><button disabled>上一页</button><button class="current">1</button><button>下一页</button></div></div>
  </section>

  <div v-if="certViewerOpen" class="modal-backdrop" @click.self="closeCertViewer">
    <div class="modal-card cert-photo-modal">
      <header class="cert-photo-head">
        <div>
          <strong>{{ certViewerTitle }}</strong>
          <span v-if="certViewerData">{{ mapStatus(certViewerData.status) }} · 提交于 {{ fmtDateTime(certViewerData.submittedAt) }}</span>
        </div>
        <button class="cert-photo-close" aria-label="关闭认证照片" @click="closeCertViewer"><X :size="17" /></button>
      </header>
      <div class="modal-body">
        <div v-if="certViewerLoading" class="cert-photo-hint">正在加载认证材料…</div>
        <div v-else-if="certViewerError" class="cert-photo-hint error">{{ certViewerError }}</div>
        <template v-else-if="certViewerData">
          <div v-if="(certViewerData.materials || []).length" class="cert-photo-grid">
            <a
              v-for="material in certViewerData.materials"
              :key="material.objectKey"
              class="cert-photo-card"
              :href="material.signedUrl || undefined"
              target="_blank"
              rel="noopener"
            >
              <img
                v-if="material.signedUrl && !certPhotoErrors[material.objectKey]"
                :src="material.signedUrl"
                :alt="material.label"
                @error="onCertPhotoError(material.objectKey)"
              />
              <div v-else class="cert-photo-missing">{{ material.signedUrl ? '图片加载失败，请检查 MinIO 地址' : '签名 URL 生成失败' }}</div>
              <span>{{ material.label }}</span>
            </a>
          </div>
          <EmptyState v-else title="暂无认证照片" description="该认证单未上传材料" />
        </template>
      </div>
      <footer><button @click="closeCertViewer">关闭</button></footer>
    </div>
  </div>

  <NiDrawer :open="drawerOpen" :title="editing ? form.name : '新增社区人员'" :eyebrow="editing ? '维护档案' : '新建档案'" @close="drawerOpen = false">
    <div class="community-selector-card" style="min-height: 56px; padding: 10px 12px; margin-bottom: 18px">
      <Building2 :size="17" style="color: #6852c5" />
      <div style="flex: 1"><span style="display: block; color: #958b9f; font-size: var(--font-size-caption)">所属社区</span><strong style="display: block; color: #554761; font-size: var(--font-size-body)">{{ community?.name }}</strong></div>
      <em style="color: #988da2; font-size: var(--font-size-caption)">{{ editing?.id || '新建' }}</em>
    </div>
    <h4 class="section-title">基本信息</h4>
    <div class="form-grid">
      <label><span>姓名 *</span><input v-model="form.name" placeholder="请输入姓名" /></label>
      <label><span>性别</span><select v-model="form.gender"><option>男</option><option>女</option></select></label>
      <label><span>手机号</span><input v-model="form.phone" placeholder="请输入手机号" /></label>
      <label><span>身份类型</span><select v-model="form.identity"><option>业主</option><option>家属</option><option>租户</option><option>商务人员</option></select></label>
      <label class="full"><span>房屋 / 商铺</span><input v-model="form.building" placeholder="例如：8 栋 1 单元 902" /></label>
      <label class="full"><span>与房屋关系</span><input v-model="form.relationship" /></label>
    </div>
    <h4 class="section-title" style="margin-top: 24px">认证与等级</h4>
    <div class="form-grid">
      <label><span>认证状态</span><select v-model="form.certification"><option>已认证</option><option>待审核</option><option>待补充</option><option>已驳回</option><option>未认证</option><option>已冻结</option><option>已撤销</option></select></label>
      <label><span>认证编号</span><input v-model="form.certificationNo" /></label>
      <label><span>用户级别</span><select v-model="form.level"><option>普通用户</option><option>活跃用户</option><option>社区达人</option><option>重点关怀</option></select></label>
      <label><span>账号状态</span><select v-model="form.status"><option>正常</option><option>已停用</option><option>已离开</option></select></label>
    </div>
    <template #footer><button @click="drawerOpen = false">取消</button><button class="primary-button" @click="save">保存档案</button></template>
  </NiDrawer>
</template>
