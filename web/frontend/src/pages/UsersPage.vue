<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Ban,
  CircleCheck,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Lock,
  LockOpen,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-vue-next'
import { adminUsersApi, communityApi, rolesApi } from '@/api'
import { fmtDateTime } from '@/api/compat'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useConfirm } from '@/composables/useConfirm'
import StatusBadge from '@/components/StatusBadge.vue'
import EmptyState from '@/components/EmptyState.vue'
import NiDrawer from '@/components/NiDrawer.vue'
import NiActionMenu from '@/components/NiActionMenu.vue'

type ActionMenuItem = {
  key: string
  label: string
  icon?: any
  danger?: boolean
  disabled?: boolean
}

type AccountForm = {
  username: string
  password: string
  realName: string
  phone: string
  email: string
  status: string
  roleIds: number[]
  communityIds: number[]
  residentId: number | null
}

const app = useAppStore()
const auth = useAuthStore()
const { confirm } = useConfirm()

const rows = ref<any[]>([])
const roles = ref<any[]>([])
const communities = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const query = ref('')
const statusFilter = ref('')
const sourceFilter = ref('')
const residentOptions = ref<any[]>([])
const loading = ref(false)
const selected = ref<Set<string>>(new Set())
const stats = ref({ total: 0, active: 0, disabled: 0, locked: 0 })

const drawerOpen = ref(false)
const editing = ref<any>(null)
const form = ref<AccountForm>(emptyForm())

const resetOpen = ref(false)
const resetTarget = ref<any>(null)
const newPassword = ref('')
const showPassword = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const selectedCount = computed(() => selected.value.size)
const selectableRows = computed(() => rows.value.filter((row) => canSelect(row)))
const allSelected = computed(() =>
  selectableRows.value.length > 0 && selectableRows.value.every((row) => selected.value.has(row.id)))
const passwordValid = computed(() => newPassword.value.length > 0 && !passwordError(newPassword.value))

function emptyForm(): AccountForm {
  return {
    username: '', password: '', realName: '', phone: '', email: '',
    status: 'ACTIVE', roleIds: [], communityIds: [], residentId: null,
  }
}

function isSelf(row: any): boolean {
  return Boolean(auth.admin?.id) && String(auth.admin?.id) === String(row.id)
}

function avatarText(row: any): string {
  return (row.realName || row.username || '?').charAt(0)
}

function communityLabel(row: any): string {
  const names = (row.communities || []).map((item: any) => item.name).filter(Boolean)
  return names.length ? names.join('、') : '—'
}

async function load() {
  loading.value = true
  try {
    const data = await adminUsersApi.list({
      keyword: query.value.trim() || undefined,
      status: statusFilter.value || undefined,
      source: sourceFilter.value || undefined,
      page: page.value,
      pageSize,
    })
    rows.value = data.items || []
    total.value = Number(data.total || 0)
    stats.value = data.stats || { total: total.value, active: 0, disabled: 0, locked: 0 }
    selected.value = new Set()
  } catch (exc: any) {
    rows.value = []
    total.value = 0
    app.showToast(exc?.message || '账号加载失败')
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const [roleRows, communityData] = await Promise.all([
      rolesApi.list(),
      communityApi.list({ page: 1, pageSize: 50 }),
    ])
    roles.value = roleRows || []
    communities.value = communityData.items || []
  } catch (exc: any) {
    app.showToast(exc?.message || '角色或社区加载失败')
  }
}

function search() {
  page.value = 1
  load()
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  load()
}

function toggleRow(row: any) {
  if (!canSelect(row)) return
  const next = new Set(selected.value)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  selected.value = next
}

function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(selectableRows.value.map((row) => row.id))
}

function clearSelection() {
  selected.value = new Set()
}

async function loadResidentOptions() {
  try {
    const rows = await adminUsersApi.residentOptions({
      communityId: app.currentCommunityId, limit: 50,
    })
    residentOptions.value = rows || []
  } catch {
    residentOptions.value = []
  }
}

function openCreate() {
  editing.value = null
  form.value = emptyForm()
  drawerOpen.value = true
  loadResidentOptions()
}

function openEdit(row: any) {
  editing.value = row
  form.value = {
    username: row.username || '',
    password: '',
    realName: row.realName || '',
    phone: row.phone && !row.phone.includes('*') ? row.phone : '',
    email: row.email || '',
    status: row.status === 'DISABLED' ? 'DISABLED' : 'ACTIVE',
    roleIds: (row.roleIds || []).map((id: string) => Number(id)),
    communityIds: (row.communityIds || []).map((id: string) => Number(id)),
    residentId: row.residentId ? Number(row.residentId) : null,
  }
  drawerOpen.value = true
  loadResidentOptions()
}

function isResidentAccount(row: any): boolean {
  return row?.source === 'RESIDENT'
}

function sourceLabel(row: any): string {
  return row.source === 'RESIDENT' ? '住户授权' : '后台创建'
}

function mobileLabel(row: any): string {
  if (!row.mobileBound) return '未绑定'
  return row.mobileStatus === 'ACTIVE' ? '已绑定' : '账号异常'
}

function passwordError(value: string): string {
  if (value.length < 12) return '密码最短 12 位'
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((rule) => rule.test(value)).length
  if (kinds < 3) return '需包含大小写字母、数字、符号中的至少三类'
  return ''
}

async function save() {
  if (!editing.value && form.value.username.trim().length < 3) {
    app.showToast('用户名至少 3 位')
    return
  }
  if (!form.value.realName.trim()) {
    app.showToast('请填写姓名')
    return
  }
  if (!editing.value) {
    const error = passwordError(form.value.password)
    if (error) {
      app.showToast(error)
      return
    }
  }
  const payload: Record<string, any> = {
    username: form.value.username.trim(),
    realName: form.value.realName.trim(),
    phone: form.value.phone.trim(),
    email: form.value.email.trim(),
    status: form.value.status,
  }
  // 住户授权账号的绑定与角色由「社区业主」页统一管理，编辑时只提交基础资料。
  if (!isResidentAccount(editing.value)) {
    payload.roleIds = form.value.roleIds.map(Number)
    payload.communityIds = form.value.communityIds.map(Number)
    payload.residentId = form.value.residentId ? Number(form.value.residentId) : null
  }
  if (!editing.value) payload.password = form.value.password
  try {
    if (editing.value) await adminUsersApi.update(editing.value.id, payload)
    else await adminUsersApi.create(payload)
    drawerOpen.value = false
    app.showToast(editing.value ? '账号已更新' : '账号已创建')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function toggleStatus(row: any) {
  const disabling = row.status === 'ACTIVE'
  if (disabling) {
    const ok = await confirm({
      title: '停用账号',
      message: `确定停用“${row.realName || row.username}”吗？停用后该账号将无法登录后台。`,
      confirmText: '确认停用',
      danger: true,
    })
    if (!ok) return
  }
  try {
    await adminUsersApi.toggleStatus(row.id, disabling ? 'DISABLED' : 'ACTIVE')
    app.showToast(disabling ? '账号已停用' : '账号已启用')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '操作失败')
  }
}

async function unlock(row: any) {
  try {
    await adminUsersApi.unlock(row.id)
    app.showToast('账号已解锁')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '解锁失败')
  }
}

async function remove(row: any) {
  const ok = await confirm({
    title: '删除账号',
    message: `确定删除“${row.realName || row.username}”吗？删除后不可恢复。`,
    confirmText: '确认删除',
    danger: true,
  })
  if (!ok) return
  try {
    await adminUsersApi.remove(row.id)
    app.showToast('账号已删除')
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

async function batchRemove() {
  const ids = Array.from(selected.value)
  if (!ids.length) return
  const ok = await confirm({
    title: '批量删除账号',
    message: `确定删除已选择的 ${ids.length} 个账号吗？删除后不可恢复。`,
    confirmText: '确认删除',
    danger: true,
  })
  if (!ok) return
  try {
    await adminUsersApi.batchRemove(ids)
    app.showToast(`已删除 ${ids.length} 个账号`)
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '批量删除失败')
  }
}

function openReset(row: any) {
  resetTarget.value = row
  newPassword.value = ''
  showPassword.value = false
  resetOpen.value = true
}

function closeReset() {
  resetOpen.value = false
  resetTarget.value = null
  newPassword.value = ''
  showPassword.value = false
}

function randomInt(max: number): number {
  const buffer = new Uint32Array(1)
  crypto.getRandomValues(buffer)
  return buffer[0] % max
}

function generatePassword() {
  const sets = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '@#$%&*!?']
  const chars = sets.map((set) => set[randomInt(set.length)])
  const pool = sets.join('')
  while (chars.length < 16) chars.push(pool[randomInt(pool.length)])
  for (let index = chars.length - 1; index > 0; index -= 1) {
    const target = randomInt(index + 1)
    const current = chars[index]
    chars[index] = chars[target]
    chars[target] = current
  }
  newPassword.value = chars.join('')
  showPassword.value = true
}

async function copyPassword() {
  try {
    await navigator.clipboard.writeText(newPassword.value)
    app.showToast('新密码已复制')
  } catch {
    app.showToast('复制失败，请手动选择密码')
  }
}

async function submitReset() {
  if (!resetTarget.value) return
  const error = passwordError(newPassword.value)
  if (error) {
    app.showToast(error)
    return
  }
  try {
    await adminUsersApi.resetPassword(resetTarget.value.id, newPassword.value)
    app.showToast('密码已重置')
    closeReset()
    await load()
  } catch (exc: any) {
    app.showToast(exc?.message || '密码重置失败')
  }
}

function rowActions(row: any): ActionMenuItem[] {
  const active = row.status === 'ACTIVE'
  return [
    { key: 'edit', label: '编辑', icon: Pencil, disabled: row.isSuperAdmin },
    { key: 'reset', label: '重置密码', icon: KeyRound },
    {
      key: 'toggle',
      label: active ? '禁用' : '启用',
      icon: active ? Ban : CircleCheck,
      danger: active,
      disabled: row.isSuperAdmin || (active && isSelf(row)),
    },
    { key: 'unlock', label: '解锁', icon: LockOpen, disabled: !row.locked },
    {
      key: 'delete',
      label: '删除',
      icon: Trash2,
      danger: true,
      disabled: row.isSuperAdmin || isSelf(row) || isResidentAccount(row),
    },
  ]
}

function canSelect(row: any): boolean {
  return !row.isSuperAdmin && !isSelf(row) && !isResidentAccount(row)
}

function onAction(key: string, row: any) {
  if (key === 'edit') openEdit(row)
  else if (key === 'reset') openReset(row)
  else if (key === 'toggle') toggleStatus(row)
  else if (key === 'unlock') unlock(row)
  else if (key === 'delete') remove(row)
}

onMounted(async () => {
  await Promise.all([load(), loadOptions()])
})
</script>

<template>
  <section class="summary-row">
    <div><span>全部账号</span><strong>{{ stats.total }}</strong><em>后台管理员</em></div>
    <div><span>启用中</span><strong>{{ stats.active }}</strong><em class="up">可正常登录</em></div>
    <div><span>已停用</span><strong>{{ stats.disabled }}</strong><em class="warn">禁止登录</em></div>
    <div><span>登录锁定</span><strong>{{ stats.locked }}</strong><em class="warn">连续失败锁定</em></div>
  </section>

  <section class="table-panel">
    <div class="table-toolbar">
      <div class="table-search">
        <Search :size="17" />
        <input v-model="query" placeholder="搜索用户名或姓名…" @keyup.enter="search" />
      </div>
      <div class="toolbar-actions">
        <select v-model="statusFilter" class="status-filter" aria-label="账号状态筛选" @change="search">
          <option value="">全部状态</option>
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">停用</option>
        </select>
        <select v-model="sourceFilter" class="status-filter" aria-label="账号来源筛选" @change="search">
          <option value="">全部来源</option>
          <option value="MANUAL">后台创建</option>
          <option value="RESIDENT">住户授权</option>
        </select>
        <button class="primary-button" @click="openCreate"><Plus :size="16" />新增用户</button>
      </div>
    </div>

    <div v-if="selectedCount" class="batch-bar">
      <span>已选择 {{ selectedCount }} 个账号</span>
      <button @click="clearSelection">取消选择</button>
      <button class="danger" @click="batchRemove"><Trash2 :size="14" />批量删除</button>
    </div>

    <div class="table-wrap">
      <table class="user-table">
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                aria-label="全选当前页"
                :checked="allSelected"
                :disabled="!selectableRows.length"
                @change="toggleAll"
              />
            </th>
            <th>用户</th>
            <th>用户名</th>
            <th>来源</th>
            <th>关联住户 / 小区</th>
            <th>移动端账号</th>
            <th>手机号</th>
            <th>角色</th>
            <th>可访问社区</th>
            <th>状态</th>
            <th>最近登录</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td>
              <input
                type="checkbox"
                :aria-label="`选择 ${row.realName || row.username}`"
                :checked="selected.has(row.id)"
                :disabled="!canSelect(row)"
                :title="canSelect(row) ? '' : '超级管理员或当前登录账号不可删除'"
                @change="toggleRow(row)"
              />
            </td>
            <td>
              <div class="primary-cell">
                <span class="row-icon">{{ avatarText(row) }}</span>
                <div class="user-cell">
                  <strong>{{ row.realName || row.username }}</strong>
                  <em v-if="row.isSuperAdmin">超级管理员</em>
                  <em v-else-if="isSelf(row)">当前账号</em>
                </div>
              </div>
            </td>
            <td><span class="medium-cell">{{ row.username }}</span></td>
            <td>
              <span :class="['source-tag', { resident: row.source === 'RESIDENT' }]">{{ sourceLabel(row) }}</span>
            </td>
            <td>
              <div v-if="row.residentId" class="resident-link-cell">
                <strong>{{ row.residentName || '住户' }}</strong>
                <span>{{ row.communityName || '—' }}</span>
              </div>
              <span v-else class="muted-text">未关联</span>
            </td>
            <td>
              <span :class="['mobile-tag', { bound: row.mobileBound && row.mobileStatus === 'ACTIVE', warn: row.mobileBound && row.mobileStatus !== 'ACTIVE' }]">
                {{ mobileLabel(row) }}
              </span>
            </td>
            <td>{{ row.phone || '—' }}</td>
            <td>
              <div class="tag-row">
                <span v-for="role in row.roles" :key="role.id || role.code" class="mini-tag">{{ role.name }}</span>
                <span v-if="!row.roles?.length" class="muted-text">未分配</span>
              </div>
            </td>
            <td>
              <span class="cell-ellipsis md" :title="communityLabel(row)">{{ communityLabel(row) }}</span>
            </td>
            <td>
              <div class="status-cell">
                <StatusBadge :value="row.status === 'ACTIVE' ? '正常' : '已停用'" />
                <span v-if="row.locked" class="lock-tag" :title="`锁定至 ${fmtDateTime(row.lockedUntil)}`">
                  <Lock :size="12" />锁定
                </span>
              </div>
            </td>
            <td>{{ row.lastLoginAt ? fmtDateTime(row.lastLoginAt) : '从未登录' }}</td>
            <td>
              <div class="row-actions">
                <NiActionMenu :items="rowActions(row)" @select="(key) => onAction(key, row)" />
              </div>
            </td>
          </tr>
          <tr v-if="loading">
            <td colspan="12" class="table-loading">正在加载账号…</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!rows.length && !loading" title="暂无账号" description="点击右上角“新增用户”创建后台账号" />
    </div>

    <div class="pagination">
      <span>共 {{ total }} 个账号</span>
      <div>
        <button :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button class="current">{{ page }}</button>
        <button :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>
  </section>

  <NiDrawer
    :open="drawerOpen"
    :title="editing ? `编辑账号 · ${editing.realName || editing.username}` : '新增用户'"
    :eyebrow="editing ? '维护管理员账号' : '新建管理员账号'"
    @close="drawerOpen = false"
  >
    <div class="form-grid">
      <label>
        <span>用户名 *</span>
        <input v-model="form.username" :disabled="!!editing" maxlength="64" placeholder="登录用户名，创建后不可修改" />
      </label>
      <label>
        <span>姓名 *</span>
        <input v-model="form.realName" maxlength="64" placeholder="真实姓名" />
      </label>
      <label v-if="!editing">
        <span>初始密码 *</span>
        <input v-model="form.password" type="password" placeholder="至少 12 位，三类字符" />
      </label>
      <label>
        <span>手机号</span>
        <input v-model="form.phone" maxlength="11" :placeholder="editing ? '留空不修改' : '选填'" />
      </label>
      <label>
        <span>邮箱</span>
        <input v-model="form.email" maxlength="128" placeholder="选填" />
      </label>
      <label>
        <span>账号状态</span>
        <select v-model="form.status">
          <option value="ACTIVE">启用</option>
          <option value="DISABLED">停用</option>
        </select>
      </label>
    </div>
    <p v-if="!editing" class="form-hint">密码需至少 12 位，且包含大小写字母、数字、符号中的至少三类；创建后可通过“重置密码”修改。</p>

    <h4 class="section-title" style="margin-top: 22px">关联社区住户<em class="optional-tag">选填</em></h4>
    <div v-if="isResidentAccount(editing)" class="resident-binding-readonly">
      <span>住户授权账号</span>
      <strong>{{ editing?.residentName || '—' }} · {{ editing?.communityName || '—' }}</strong>
      <em>绑定关系与角色请到「社区业主」页调整</em>
    </div>
    <template v-else>
      <label class="resident-select-field">
        <span>选择住户</span>
        <select v-model="form.residentId">
          <option :value="null">不关联住户（纯后台账号）</option>
          <option v-for="item in residentOptions" :key="item.id" :value="Number(item.id)">
            {{ item.name }} · {{ item.communityName }} · {{ item.phone || '无手机号' }}{{ item.adminUserId && String(item.adminUserId) !== String(editing?.id) ? '（已绑其他账号）' : '' }}
          </option>
        </select>
      </label>
      <p class="form-hint">关联住户后，系统会确保该住户拥有移动端账号，可用手机号登录 App；不关联时账号仅用于后台。</p>
    </template>

    <h4 class="section-title" style="margin-top: 22px">角色</h4>
    <div v-if="isResidentAccount(editing)" class="muted-text">住户授权账号的角色由「社区业主」页统一配置。</div>
    <template v-else>
      <div class="choice-grid">
        <label v-for="role in roles" :key="role.id" class="choice-item">
          <input v-model="form.roleIds" type="checkbox" :value="Number(role.id)" />
          <div><strong>{{ role.name }}</strong><em>{{ role.code }}</em></div>
        </label>
        <p v-if="!roles.length" class="muted-text">暂无可分配角色</p>
      </div>
      <p class="form-hint">多角色权限取并集；未分配角色时账号仅能登录，无业务权限。</p>

      <h4 class="section-title" style="margin-top: 22px">可访问社区<em class="optional-tag">选填</em></h4>
      <div class="choice-grid community-choices">
        <label v-for="community in communities" :key="community.id" class="choice-item">
          <input v-model="form.communityIds" type="checkbox" :value="Number(community.id)" />
          <div><strong>{{ community.name }}</strong><em>{{ community.code }}</em></div>
        </label>
        <p v-if="!communities.length" class="muted-text">暂无社区数据</p>
      </div>
      <p class="form-hint">创建用户时可不选择可访问社区；角色数据范围为“全部数据”时不受社区限制，其他角色可在创建后编辑补充。</p>
    </template>

    <template #footer>
      <button @click="drawerOpen = false">取消</button>
      <button class="primary-button" @click="save">保存</button>
    </template>
  </NiDrawer>

  <div v-if="resetOpen" class="modal-backdrop" @click.self="closeReset">
    <div class="modal-card reset-card">
      <header>重置密码 · {{ resetTarget?.realName || resetTarget?.username }}</header>
      <div class="modal-body">
        <label class="reset-field">
          <span>新密码</span>
          <div class="password-field">
            <input
              v-model="newPassword"
              :type="showPassword ? 'text' : 'password'"
              placeholder="至少 12 位，三类字符"
              autocomplete="new-password"
            />
            <button type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
              <EyeOff v-if="showPassword" :size="16" />
              <Eye v-else :size="16" />
            </button>
          </div>
        </label>
        <p class="form-hint">重置后该账号的登录失败锁定会一并清除，需使用新密码重新登录。</p>
        <div class="password-actions">
          <button type="button" @click="generatePassword"><RefreshCw :size="14" />生成随机密码</button>
          <button type="button" :disabled="!newPassword" @click="copyPassword"><Copy :size="14" />复制</button>
        </div>
      </div>
      <footer>
        <button @click="closeReset">取消</button>
        <button class="primary-button" :disabled="!passwordValid" @click="submitReset">确认重置</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.user-table { min-width: 1080px; }
.status-filter {
  height: 34px;
  padding: 0 10px;
  border: 1px solid #e6e3e9;
  border-radius: 8px;
  color: #6f6a78;
  background: #fff;
  font-size: var(--font-size-body);
}
.user-cell strong { display: block; color: #3f3b46; font-size: var(--font-size-body); font-weight: 600; }
.user-cell em {
  display: block;
  margin-top: 2px;
  color: #8f7ea8;
  font-size: var(--font-size-caption);
  font-style: normal;
}
.tag-row { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.mini-tag {
  padding: 3px 7px;
  border-radius: 6px;
  color: #5f4abd;
  background: #f0edfb;
  font-size: var(--font-size-caption);
}
.muted-text { color: #aaa6b1; font-size: var(--font-size-caption); }
.optional-tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 6px;
  color: #8f8a97;
  background: #f2f0f6;
  font-size: var(--font-size-caption);
  font-style: normal;
  font-weight: 400;
}
.status-cell { display: flex; align-items: center; gap: 6px; }
.lock-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 6px;
  border-radius: 8px;
  color: #b9772e;
  background: #fdf1e0;
  font-size: var(--font-size-caption);
  white-space: nowrap;
}
.table-loading { padding: 38px 0; color: #9a95a1; font-size: var(--font-size-body); text-align: center; }
.choice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.community-choices { max-height: 190px; overflow-y: auto; padding-right: 2px; }
.choice-item {
  min-height: 44px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid #e7e3ee;
  border-radius: 9px;
  cursor: pointer;
}
.choice-item:hover { border-color: #cfc3f2; background: #faf8ff; }
.choice-item input { flex: 0 0 auto; }
.choice-item strong { display: block; color: #4d4856; font-size: var(--font-size-body); font-weight: 500; }
.choice-item em { display: block; margin-top: 1px; color: #9c97a3; font-size: var(--font-size-caption); font-style: normal; }
.reset-card { width: min(460px, 100%); }
.reset-field { display: block; }
.reset-field > span { display: block; margin-bottom: 6px; color: #65616d; font-size: var(--font-size-body); font-weight: 500; }
.password-field {
  height: 38px;
  padding: 0 8px 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #e1dee5;
  border-radius: 8px;
  background: #fff;
}
.password-field:focus-within { border-color: #b9a9ec; box-shadow: 0 0 0 3px #f1ecfd; }
.password-field input { width: 100%; border: 0; outline: none; color: #514d58; background: transparent; font-size: var(--font-size-body); }
.password-field button { flex: 0 0 auto; color: #8f8a97; }
.password-actions { margin-top: 12px; display: flex; gap: 8px; }
.password-actions button {
  height: 32px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #e1dee5;
  border-radius: 8px;
  color: #6750c4;
  background: #fff;
  font-size: var(--font-size-caption);
}
.password-actions button:disabled { color: #b1adb8; cursor: not-allowed; }
.modal-card footer .primary-button:disabled { opacity: .5; cursor: not-allowed; }
.source-tag { display: inline-block; padding: 2px 7px; border-radius: 6px; color: #7d7790; background: #f3f2f6; font-size: var(--font-size-caption); white-space: nowrap; }
.source-tag.resident { color: #5f4bb5; background: #f1edfc; }
.resident-link-cell { display: flex; flex-direction: column; line-height: 1.35; }
.resident-link-cell strong { color: #4a4552; font-size: var(--font-size-body); font-weight: 500; }
.resident-link-cell span { color: #9a95a1; font-size: var(--font-size-caption); }
.mobile-tag { color: #9a95a1; font-size: var(--font-size-caption); white-space: nowrap; }
.mobile-tag.bound { color: #4f8a68; }
.mobile-tag.warn { color: #b06a6a; }
.resident-binding-readonly { display: flex; flex-direction: column; gap: 3px; padding: 11px 13px; border: 1px solid #e6e1ef; border-radius: 9px; background: #faf8ff; }
.resident-binding-readonly > span { color: #8f8799; font-size: var(--font-size-caption); }
.resident-binding-readonly > strong { color: #4a4552; font-size: var(--font-size-body); font-weight: 500; }
.resident-binding-readonly > em { color: #9a95a1; font-size: var(--font-size-caption); font-style: normal; }
.resident-select-field { display: block; }
.resident-select-field > span { display: block; margin-bottom: 5px; color: #65616d; font-size: var(--font-size-body); font-weight: 500; }
.resident-select-field select { width: 100%; height: 36px; padding: 0 9px; border: 1px solid #e1dee5; border-radius: 8px; color: #514d58; background: #fff; font-size: var(--font-size-body); }
</style>
