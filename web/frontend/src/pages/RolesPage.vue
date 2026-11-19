<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Box, Check, ChevronRight, Coffee, HandHeart, LayoutDashboard, LockKeyhole, Map as MapIcon, Megaphone,
  MoreHorizontal, Pencil, Plus, Save, Search, ShieldCheck, ShoppingBag, SlidersHorizontal, Trash2, UserRound,
  Users, X,
} from 'lucide-vue-next'
import { rolesApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useConfirm } from '@/composables/useConfirm'

const app = useAppStore()
const { confirm } = useConfirm()
const roles = ref<any[]>([])
const selectedId = ref('')
const checked = ref<Set<string>>(new Set())
const roleQuery = ref('')
const permissionQuery = ref('')
const expanded = ref<Set<string>>(new Set())

const roleModalOpen = ref(false)
const editingId = ref('')
const savingRole = ref(false)
const roleForm = ref({
  name: '', code: '', description: '', dataScope: 'OWN_COMMUNITY',
  assignableToResident: false,
})
const roleNameInput = ref<HTMLInputElement | null>(null)
const roleListEl = ref<HTMLElement | null>(null)
const draggingId = ref('')

const ROLE_ORDER_KEY = 'neighinn.admin.roleOrder'
const LONG_PRESS_MS = 280
let pressTimer: ReturnType<typeof setTimeout> | null = null
let pressOrigin = { x: 0, y: 0 }
let pressPointerId: number | null = null
let orderChanged = false
let suppressClickUntil = 0

const dataScopeOptions = [
  { value: 'ALL', label: '全部数据' },
  { value: 'COMMUNITY_SET', label: '指定社区集合' },
  { value: 'OWN_COMMUNITY', label: '本社区' },
  { value: 'SELF', label: '仅本人' },
]

type Resource = { code: string; label: string; type: string }
type Menu = { label: string; code: string; icon: any; resources: Resource[] }
type Group = { label: string; items: Menu[] }

const groups: Group[] = [
  { label: '总览', items: [{ label: '工作台', code: 'dashboard', icon: LayoutDashboard, resources: [{ code: 'dashboard:view', label: '查看工作台', type: '页面' }, { code: 'dashboard:export', label: '生成运营简报', type: '按钮' }] }] },
  { label: '社区运营', items: [
    { label: '社区喇叭', code: 'community:broadcast', icon: Megaphone, resources: [{ code: 'community:broadcast:view', label: '查看喇叭', type: '页面' }, { code: 'community:broadcast:create', label: '发布喇叭', type: '按钮' }, { code: 'community:broadcast:update', label: '编辑喇叭', type: '按钮' }, { code: 'community:broadcast:delete', label: '删除喇叭', type: '按钮' }, { code: 'community:broadcast:review', label: '审核内容', type: '按钮' }, { code: 'community:broadcast:offline', label: '下架内容', type: '弹出菜单' }] },
    { label: '社区物品', code: 'community:item', icon: ShoppingBag, resources: [{ code: 'community:item:view', label: '查看物品', type: '页面' }, { code: 'community:item:review', label: '审核物品', type: '按钮' }, { code: 'community:item:recommend', label: '设置推荐', type: '开关' }, { code: 'community:item:offline', label: '下架物品', type: '弹出菜单' }] },
    { label: '邻里互助', code: 'community:help', icon: HandHeart, resources: [{ code: 'community:help:view', label: '查看互助', type: '页面' }, { code: 'community:help:create', label: '代发互助', type: '按钮' }, { code: 'community:help:match', label: '人工撮合', type: '按钮' }, { code: 'community:help:close', label: '关闭互助', type: '弹出菜单' }] },
    { label: '社区生活', code: 'community:life', icon: Coffee, resources: [{ code: 'community:life:view', label: '查看生活', type: '页面' }, { code: 'community:life:create', label: '新建内容', type: '按钮' }, { code: 'community:life:update', label: '编辑内容', type: '按钮' }, { code: 'community:life:delete', label: '删除内容', type: '按钮' }, { code: 'community:life:review', label: '审核内容', type: '按钮' }, { code: 'community:life:offline', label: '下线内容', type: '弹出菜单' }] },
  ] },
  { label: '触达中心', items: [
    { label: '公告管理', code: 'communication:notice', icon: LayoutDashboard, resources: [{ code: 'communication:notice:view', label: '查看公告', type: '页面' }, { code: 'communication:notice:create', label: '发布公告', type: '按钮' }, { code: 'communication:notice:publish', label: '发布/撤回', type: '按钮' }] },
    { label: '通知任务', code: 'communication:task', icon: LayoutDashboard, resources: [{ code: 'communication:task:view', label: '查看任务', type: '页面' }, { code: 'communication:task:create', label: '新建通知', type: '按钮' }, { code: 'communication:task:send', label: '发送通知', type: '按钮' }] },
  ] },
  { label: '社区管理', items: [
    { label: '社区运维', code: 'community:maintenance', icon: MapIcon, resources: [{ code: 'community:maintenance:view', label: '查看社区', type: '页面' }, { code: 'community:maintenance:create', label: '新增社区', type: '按钮' }, { code: 'community:maintenance:update', label: '编辑社区', type: '按钮' }] },
    { label: '社区业主', code: 'community:resident', icon: UserRound, resources: [{ code: 'community:resident:view', label: '查看人员', type: '页面' }, { code: 'community:resident:create', label: '新增人员', type: '按钮' }, { code: 'community:resident:update', label: '编辑人员', type: '按钮' }, { code: 'community:resident:audit', label: '认证审核', type: '按钮' }] },
  ] },
  { label: '资金与治理', items: [
    { label: '资金管理', code: 'finance', icon: LayoutDashboard, resources: [{ code: 'finance:overview:view', label: '资金看板', type: '页面' }, { code: 'finance:transaction:view', label: '资金流水', type: '页面' }, { code: 'finance:withdrawal:review', label: '提现复核', type: '按钮' }, { code: 'finance:adjustment:create', label: '资金处置', type: '按钮' }] },
    { label: '纠纷调解', code: 'governance:dispute', icon: ShieldCheck, resources: [{ code: 'governance:dispute:view', label: '查看纠纷', type: '页面' }, { code: 'governance:dispute:mediate', label: '调解记录', type: '按钮' }, { code: 'governance:dispute:resolve', label: '出具结论', type: '按钮' }] },
  ] },
  { label: '系统管理', items: [
    { label: '用户管理', code: 'system:admin-user', icon: Users, resources: [{ code: 'system:admin-user:view', label: '查看账号', type: '页面' }, { code: 'system:admin-user:create', label: '新增账号', type: '按钮' }, { code: 'system:admin-user:update', label: '编辑/禁用/解锁/重置密码/删除', type: '弹出菜单' }] },
    { label: '角色权限', code: 'system:role', icon: ShieldCheck, resources: [{ code: 'system:role:view', label: '查看角色', type: '页面' }, { code: 'system:role:create', label: '新建角色', type: '按钮' }, { code: 'system:role:grant', label: '配置权限', type: '按钮' }] },
    { label: '资源管理', code: 'system:resource', icon: Box, resources: [{ code: 'system:resource:view', label: '查看资源', type: '页面' }, { code: 'system:resource:create', label: '新增资源', type: '按钮' }, { code: 'system:resource:update', label: '编辑资源', type: '按钮' }] },
    { label: '参数配置', code: 'system:parameter', icon: SlidersHorizontal, resources: [{ code: 'system:parameter:view', label: '查看参数', type: '页面' }, { code: 'system:parameter:update', label: '修改参数', type: '按钮' }, { code: 'system:parameter:publish', label: '发布参数', type: '按钮' }] },
  ] },
]

const allCodes = groups.flatMap((group) => group.items.flatMap((item) => item.resources.map((resource) => resource.code)))
const selectedRole = computed(() => roles.value.find((role) => role.id === selectedId.value) || roles.value[0])
const isSuper = computed(() => selectedRole.value?.code === 'super_admin')
const filteredRoles = computed(() => roles.value.filter((role) => `${role.name} ${role.code}`.toLowerCase().includes(roleQuery.value.toLowerCase())))
const filteredGroups = computed(() => groups.map((group) => ({ ...group, items: group.items.filter((item) => `${item.label} ${item.resources.map((r) => r.label).join(' ')}`.toLowerCase().includes(permissionQuery.value.toLowerCase())) })).filter((group) => group.items.length))
const editingSuper = computed(() => roles.value.find((role) => role.id === editingId.value)?.code === 'super_admin')
const canSort = computed(() => !roleQuery.value.trim() && filteredRoles.value.length > 1)
const sortHint = computed(() => (roleQuery.value.trim() ? '搜索中不可排序' : '长按拖拽排序'))

function roleChecked(role: any) {
  return isSuper.value || checked.value.size === allCodes.length
}

function menuChecked(menu: Menu) {
  return isSuper.value || menu.resources.every((resource) => checked.value.has(resource.code))
}

function menuPartial(menu: Menu) {
  return !menuChecked(menu) && menu.resources.some((resource) => checked.value.has(resource.code))
}

function groupChecked(group: Group) {
  return isSuper.value || group.items.every((item) => menuChecked(item))
}

function groupPartial(group: Group) {
  return !groupChecked(group) && group.items.some((item) => menuPartial(item))
}

function toggleCodes(codes: string[]) {
  if (isSuper.value) return
  const next = new Set(checked.value)
  const all = codes.every((code) => next.has(code))
  codes.forEach((code) => (all ? next.delete(code) : next.add(code)))
  checked.value = next
}

function toggleMenu(menu: Menu, event?: Event) {
  event?.stopPropagation()
  toggleCodes(menu.resources.map((resource) => resource.code))
}

function toggleGroup(group: Group) {
  toggleCodes(group.items.flatMap((item) => item.resources.map((resource) => resource.code)))
}

async function selectRole(role: any) {
  if (Date.now() < suppressClickUntil) return
  selectedId.value = role.id
  await loadPermissions(role.id)
}

async function loadPermissions(id: string) {
  try {
    const data = await rolesApi.permissions(id)
    checked.value = new Set(data.permissions || [])
  } catch (exc: any) {
    app.showToast(exc?.message || '权限加载失败')
  }
}

function applySavedOrder(list: any[]) {
  let saved: string[] = []
  try {
    const raw = JSON.parse(localStorage.getItem(ROLE_ORDER_KEY) || '[]')
    if (Array.isArray(raw)) saved = raw.map((id) => String(id))
  } catch {
    saved = []
  }
  if (!saved.length) return list
  const index = new Map<string, number>(saved.map((id, position) => [id, position] as [string, number]))
  return list
    .map((role, position) => ({ role, position }))
    .sort((a, b) => {
      const ai = index.get(String(a.role.id)) ?? Number.MAX_SAFE_INTEGER
      const bi = index.get(String(b.role.id)) ?? Number.MAX_SAFE_INTEGER
      return ai - bi || a.position - b.position
    })
    .map((entry) => entry.role)
}

function persistRoleOrder() {
  try {
    localStorage.setItem(ROLE_ORDER_KEY, JSON.stringify(roles.value.map((role) => role.id)))
  } catch {
    // 本地存储不可用时仅保留本次会话内的排序
  }
}

async function loadRoles() {
  try {
    roles.value = applySavedOrder(await rolesApi.list())
    if (!selectedId.value && roles.value[0]) {
      selectedId.value = roles.value[0].id
      await loadPermissions(selectedId.value)
    }
  } catch (exc: any) {
    app.showToast(exc?.message || '角色加载失败')
  }
}

function openCreateRole() {
  editingId.value = ''
  roleForm.value = {
    name: '', code: '', description: '', dataScope: 'OWN_COMMUNITY',
    assignableToResident: false,
  }
  roleModalOpen.value = true
}

function openEditRole(role: any) {
  editingId.value = role.id
  roleForm.value = {
    name: role.name || '',
    code: role.code || '',
    description: role.description || '',
    dataScope: role.dataScope || 'OWN_COMMUNITY',
    assignableToResident: Boolean(role.assignableToResident),
  }
  roleModalOpen.value = true
}

function closeRoleModal() {
  if (savingRole.value) return
  roleModalOpen.value = false
}

async function submitRole() {
  const name = roleForm.value.name.trim()
  if (!name || savingRole.value) return
  savingRole.value = true
  try {
    const payload: Record<string, any> = {
      name,
      description: roleForm.value.description.trim(),
      dataScope: roleForm.value.dataScope,
      assignableToResident: roleForm.value.assignableToResident
        && roleForm.value.dataScope === 'OWN_COMMUNITY',
    }
    if (editingId.value) {
      await rolesApi.update(editingId.value, payload)
      await loadRoles()
      app.showToast(`角色“${name}”已更新`)
    } else {
      const code = roleForm.value.code.trim()
      const role = await rolesApi.create(code ? { ...payload, code } : payload)
      await loadRoles()
      await selectRole(role)
      app.showToast('角色已创建')
    }
    roleModalOpen.value = false
  } catch (exc: any) {
    app.showToast(exc?.message || (editingId.value ? '更新失败' : '创建失败'))
  } finally {
    savingRole.value = false
  }
}

async function savePermissions() {
  if (!selectedRole.value || isSuper.value) return
  try {
    await rolesApi.savePermissions(selectedRole.value.id, Array.from(checked.value))
    app.showToast(`${selectedRole.value.name}的权限配置已保存`)
    await loadRoles()
  } catch (exc: any) {
    app.showToast(exc?.message || '保存失败')
  }
}

async function deleteRole(role: any, event: Event) {
  event.stopPropagation()
  if (draggingId.value) return
  if (role.builtin) {
    app.showToast('内置角色不可删除')
    return
  }
  if (!(await confirm({ title: '删除角色', message: `确定删除角色“${role.name}”吗？`, details: ['删除后该角色的权限配置将一并清除，且不可恢复。'], confirmText: '确认删除', danger: true }))) return
  try {
    await rolesApi.remove(role.id)
    if (selectedId.value === role.id) selectedId.value = ''
    await loadRoles()
    app.showToast('角色已删除')
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

function clearPressTimer() {
  if (pressTimer) {
    clearTimeout(pressTimer)
    pressTimer = null
  }
}

function onRolePointerDown(role: any, event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  if (!canSort.value) return
  if ((event.target as HTMLElement).closest('.role-card-actions')) return
  clearPressTimer()
  pressOrigin = { x: event.clientX, y: event.clientY }
  pressPointerId = event.pointerId
  pressTimer = setTimeout(() => {
    pressTimer = null
    if (pressPointerId === null) return
    draggingId.value = role.id
    orderChanged = false
    suppressClickUntil = Date.now() + 400
    try {
      roleListEl.value?.setPointerCapture(pressPointerId)
    } catch {
      // 指针捕获不可用时仍可通过列表上的移动事件完成排序
    }
  }, LONG_PRESS_MS)
}

function onRolePointerMove(event: PointerEvent) {
  if (!draggingId.value) {
    if (pressTimer) {
      const distance = Math.hypot(event.clientX - pressOrigin.x, event.clientY - pressOrigin.y)
      if (distance > 6) clearPressTimer()
    }
    return
  }
  event.preventDefault()
  const hovered = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-role-id]') as HTMLElement | null
  const targetId = hovered?.dataset.roleId
  if (!targetId || targetId === draggingId.value) return
  const from = roles.value.findIndex((role) => role.id === draggingId.value)
  const to = roles.value.findIndex((role) => role.id === targetId)
  if (from < 0 || to < 0 || from === to) return
  const next = roles.value.slice()
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  roles.value = next
  orderChanged = true
}

function endRoleDrag(event?: PointerEvent) {
  clearPressTimer()
  if (!draggingId.value) return
  draggingId.value = ''
  pressPointerId = null
  if (orderChanged) {
    persistRoleOrder()
    app.showToast('角色顺序已保存')
    orderChanged = false
  }
  if (event && roleListEl.value?.hasPointerCapture(event.pointerId)) {
    roleListEl.value.releasePointerCapture(event.pointerId)
  }
}

function onRoleListLeave() {
  if (!draggingId.value) clearPressTimer()
}

function blockTouchScroll(event: TouchEvent) {
  if (draggingId.value) event.preventDefault()
}

watch(roleModalOpen, async (open) => {
  if (!open) return
  await nextTick()
  roleNameInput.value?.focus()
})

onMounted(async () => {
  expanded.value = new Set(groups.flatMap((group) => group.items.map((item) => item.code)))
  window.addEventListener('pointerup', endRoleDrag)
  document.addEventListener('touchmove', blockTouchScroll, { passive: false })
  await loadRoles()
})

onUnmounted(() => {
  clearPressTimer()
  window.removeEventListener('pointerup', endRoleDrag)
  document.removeEventListener('touchmove', blockTouchScroll)
})
</script>

<template>
  <section class="role-permission-workspace">
    <aside class="role-list-panel">
      <div class="role-list-heading">
        <div><strong>角色列表</strong><span>{{ roles.length }} 个角色</span></div>
        <button title="新建角色" aria-label="新建角色" @click="openCreateRole"><Plus :size="16" /></button>
      </div>
      <div class="role-search"><Search :size="15" /><input v-model="roleQuery" placeholder="搜索角色名称或编码" /></div>
      <div
        ref="roleListEl"
        :class="['role-list', { 'is-dragging': Boolean(draggingId) }]"
        @pointermove="onRolePointerMove"
        @pointerup="endRoleDrag"
        @pointercancel="endRoleDrag"
        @pointerleave="onRoleListLeave"
      >
        <div
          v-for="role in filteredRoles"
          :key="role.id"
          :data-role-id="role.id"
          :class="['role-card', { selected: selectedId === role.id, dragging: draggingId === role.id }]"
          @click="selectRole(role)"
          @pointerdown="onRolePointerDown(role, $event)"
        >
          <div :class="['role-card-icon', { super: role.builtin }]"><ShieldCheck :size="17" /></div>
          <div class="role-card-content">
            <div class="role-card-title">
              <strong>{{ role.name }}</strong>
              <em v-if="role.builtin">内置</em>
              <em v-if="role.assignableToResident" class="role-assignable-tag">可授予住户</em>
            </div>
            <p>{{ role.description }}</p><span>{{ role.members }} 名成员 · {{ role.code }}</span>
          </div>
          <div class="role-card-actions">
            <button title="编辑角色" aria-label="编辑角色" @click.stop="openEditRole(role)"><Pencil :size="14" /></button>
            <button
              :class="['danger']"
              :title="role.builtin ? '内置角色不可删除' : '删除角色'"
              :aria-label="role.builtin ? '内置角色不可删除' : '删除角色'"
              :disabled="role.builtin"
              @click.stop="deleteRole(role, $event)"
            ><Trash2 :size="14" /></button>
          </div>
        </div>
      </div>
      <div class="role-list-footer">
        <Users :size="14" />共 {{ roles.reduce((sum, role) => sum + role.members, 0) }} 名成员已分配角色
        <span class="role-sort-hint">{{ sortHint }}</span>
      </div>
    </aside>

    <div class="permission-config-panel">
      <div class="permission-config-header">
        <div :class="['permission-role-icon', { super: isSuper }]"><ShieldCheck :size="20" /></div>
        <div><span>正在配置</span><h2>{{ selectedRole?.name }}</h2><code>{{ selectedRole?.code }}</code></div>
        <div v-if="isSuper" class="all-permission-badge"><Check :size="13" />全部权限</div>
        <div v-else class="permission-progress"><span>已授权 {{ checked.size }} / {{ allCodes.length }}</span><i><b :style="{ width: `${(checked.size / allCodes.length) * 100}%` }" /></i></div>
        <button class="primary-button" :disabled="isSuper" @click="savePermissions"><Save :size="16" />保存权限</button>
      </div>
      <div v-if="isSuper" class="super-admin-notice"><LockKeyhole :size="16" /><div><strong>超级管理员默认拥有系统全部权限</strong><p>为保障系统可管理性，该角色的权限不可取消或修改。</p></div></div>
      <div class="permission-toolbar">
        <div class="table-search"><Search :size="17" /><input v-model="permissionQuery" placeholder="搜索菜单或页面资源…" /></div>
        <div><span>菜单权限</span><i /><span>页面资源权限</span></div>
      </div>
      <div class="permission-tree">
        <div v-for="group in filteredGroups" :key="group.label" class="permission-group">
          <div class="permission-group-heading">
            <label><input type="checkbox" :checked="groupChecked(group)" :disabled="isSuper" @change="toggleGroup(group)" /><strong>{{ group.label }}</strong></label>
            <span>{{ group.items.length }} 个菜单页面</span>
          </div>
          <div v-for="menu in group.items" :key="menu.code" class="permission-menu">
            <div class="permission-menu-row">
              <button class="permission-expand" @click="expanded.has(menu.code) ? expanded.delete(menu.code) : expanded.add(menu.code)"><ChevronRight :size="14" :class="{ expanded: expanded.has(menu.code) }" /></button>
              <label><input type="checkbox" :checked="menuChecked(menu)" :disabled="isSuper" @change="toggleMenu(menu)" /><span class="permission-menu-icon"><component :is="menu.icon" :size="15" /></span><strong>{{ menu.label }}</strong></label>
              <span class="menu-permission-tag">菜单访问</span><em>{{ menu.resources.length }} 项资源</em>
            </div>
            <div v-if="expanded.has(menu.code)" class="permission-resources">
              <label v-for="resource in menu.resources" :key="resource.code"><input type="checkbox" :checked="isSuper || checked.has(resource.code)" :disabled="isSuper" @change="toggleCodes([resource.code])" /><span><MoreHorizontal :size="13" /></span><div><strong>{{ resource.label }}</strong><em>{{ resource.type }}</em></div></label>
            </div>
          </div>
        </div>
      </div>
      <div class="permission-footer"><div><span class="legend checked"><Check :size="11" /></span>已授权<span class="legend" />未授权</div><p>权限变更将在角色成员下次刷新页面后生效</p></div>
    </div>

    <div v-if="roleModalOpen" class="modal-backdrop" @mousedown.self="closeRoleModal" @keydown.esc="closeRoleModal">
      <section class="modal-card role-dialog" role="dialog" aria-modal="true" :aria-label="editingId ? '编辑角色' : '新建角色'" @mousedown.stop>
        <header>
          {{ editingId ? `编辑角色 · ${roleForm.name || '未命名'}` : '新建角色' }}
        </header>
        <div class="modal-body">
          <div class="form-grid">
            <label class="full">
              <span>角色名称 <em>*</em></span>
              <input ref="roleNameInput" v-model="roleForm.name" maxlength="64" placeholder="例如：社区志愿者" @keyup.enter="submitRole" />
            </label>
            <label class="full">
              <span>角色编码{{ editingId ? '' : '（选填，留空自动生成）' }}</span>
              <input v-model="roleForm.code" :disabled="Boolean(editingId)" maxlength="64" placeholder="例如：community_volunteer" />
            </label>
            <label class="full">
              <span>角色描述</span>
              <textarea v-model="roleForm.description" maxlength="200" placeholder="说明该角色的职责与使用范围" />
            </label>
            <label class="full">
              <span>数据范围</span>
              <select v-model="roleForm.dataScope" :disabled="editingSuper">
                <option v-for="option in dataScopeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <div class="full role-assignable-row">
              <span>可授予社区住户</span>
              <label class="role-assignable-toggle">
                <input
                  v-model="roleForm.assignableToResident"
                  type="checkbox"
                  :disabled="roleForm.dataScope !== 'OWN_COMMUNITY'"
                />
                <span>允许在「社区业主」页将该角色授予本社区住户，使其登录后台</span>
              </label>
            </div>
          </div>
          <p v-if="editingSuper" class="form-hint">超级管理员的数据范围固定为“全部数据”，不可修改。</p>
          <p v-else-if="roleForm.dataScope !== 'OWN_COMMUNITY'" class="form-hint">仅“本社区”数据范围的角色可授予社区住户。</p>
          <p v-else class="form-hint">数据范围决定该角色成员可查看的业务数据边界，保存角色后可继续在右侧配置菜单与资源权限。</p>
        </div>
        <footer>
          <button @click="closeRoleModal">取消</button>
          <button class="primary-button" :disabled="!roleForm.name.trim() || savingRole" @click="submitRole">
            {{ savingRole ? '保存中…' : '保存' }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.role-dialog { width: min(560px, 100%); }
.role-dialog header { color: #3d3945; }
.role-dialog .form-grid label > span em { color: #d05a64; font-style: normal; }
.role-assignable-row > span { display: block; margin-bottom: 5px; color: #65616d; font-size: var(--font-size-body); font-weight: 500; }
.role-assignable-toggle { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border: 1px solid #e6e1ef; border-radius: 10px; background: #faf8ff; color: #5b5366; font-size: var(--font-size-body); line-height: 1.5; }
.role-assignable-toggle input { width: auto; height: auto; margin-top: 2px; }
.role-assignable-tag { margin-left: 6px; padding: 1px 6px; border-radius: 6px; background: #efeaff; color: #6f59d4; font-size: var(--font-size-caption); font-style: normal; }
.role-sort-hint { margin-left: auto; overflow: hidden; color: #b0abb8; font-size: var(--font-size-caption); white-space: nowrap; text-overflow: ellipsis; }
.role-card.dragging { z-index: 2; cursor: grabbing; border-color: #b3a0e8; background: #f6f2ff; box-shadow: 0 10px 24px rgba(82, 61, 153, .2); }
.role-list.is-dragging,
.role-list.is-dragging .role-card { cursor: grabbing; }
</style>
