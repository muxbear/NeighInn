<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Box, Check, ChevronRight, Coffee, HandHeart, LayoutDashboard, LockKeyhole, Map, Megaphone,
  MoreHorizontal, Plus, Save, Search, ShieldCheck, ShoppingBag, SlidersHorizontal, Trash2, UserRound,
  Users, X,
} from 'lucide-vue-next'
import { rolesApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const app = useAppStore()
const auth = useAuthStore()
const roles = ref<any[]>([])
const selectedId = ref('')
const checked = ref<Set<string>>(new Set())
const roleQuery = ref('')
const permissionQuery = ref('')
const creating = ref(false)
const newRoleName = ref('')
const expanded = ref<Set<string>>(new Set())

type Resource = { code: string; label: string; type: string }
type Menu = { label: string; code: string; icon: any; resources: Resource[] }
type Group = { label: string; items: Menu[] }

const groups: Group[] = [
  { label: '总览', items: [{ label: '工作台', code: 'dashboard', icon: LayoutDashboard, resources: [{ code: 'dashboard:view', label: '查看工作台', type: '页面' }, { code: 'dashboard:export', label: '生成运营简报', type: '按钮' }] }] },
  { label: '社区运营', items: [
    { label: '社区喇叭', code: 'community:broadcast', icon: Megaphone, resources: [{ code: 'community:broadcast:view', label: '查看喇叭', type: '页面' }, { code: 'community:broadcast:create', label: '发布喇叭', type: '按钮' }, { code: 'community:broadcast:review', label: '审核内容', type: '按钮' }, { code: 'community:broadcast:offline', label: '下架内容', type: '弹出菜单' }] },
    { label: '社区物品', code: 'community:item', icon: ShoppingBag, resources: [{ code: 'community:item:view', label: '查看物品', type: '页面' }, { code: 'community:item:review', label: '审核物品', type: '按钮' }, { code: 'community:item:recommend', label: '设置推荐', type: '开关' }, { code: 'community:item:offline', label: '下架物品', type: '弹出菜单' }] },
    { label: '邻里互助', code: 'community:help', icon: HandHeart, resources: [{ code: 'community:help:view', label: '查看互助', type: '页面' }, { code: 'community:help:create', label: '代发互助', type: '按钮' }, { code: 'community:help:match', label: '人工撮合', type: '按钮' }, { code: 'community:help:close', label: '关闭互助', type: '弹出菜单' }] },
    { label: '社区生活', code: 'community:life', icon: Coffee, resources: [{ code: 'community:life:view', label: '查看生活', type: '页面' }, { code: 'community:life:create', label: '新建内容', type: '按钮' }, { code: 'community:life:review', label: '审核内容', type: '按钮' }, { code: 'community:life:offline', label: '下线内容', type: '弹出菜单' }] },
  ] },
  { label: '触达中心', items: [
    { label: '公告管理', code: 'communication:notice', icon: LayoutDashboard, resources: [{ code: 'communication:notice:view', label: '查看公告', type: '页面' }, { code: 'communication:notice:create', label: '发布公告', type: '按钮' }, { code: 'communication:notice:publish', label: '发布/撤回', type: '按钮' }] },
    { label: '通知任务', code: 'communication:task', icon: LayoutDashboard, resources: [{ code: 'communication:task:view', label: '查看任务', type: '页面' }, { code: 'communication:task:create', label: '新建通知', type: '按钮' }, { code: 'communication:task:send', label: '发送通知', type: '按钮' }] },
  ] },
  { label: '社区管理', items: [
    { label: '社区运维', code: 'community:maintenance', icon: Map, resources: [{ code: 'community:maintenance:view', label: '查看社区', type: '页面' }, { code: 'community:maintenance:create', label: '新增社区', type: '按钮' }, { code: 'community:maintenance:update', label: '编辑社区', type: '按钮' }] },
    { label: '社区业主', code: 'community:resident', icon: UserRound, resources: [{ code: 'community:resident:view', label: '查看人员', type: '页面' }, { code: 'community:resident:create', label: '新增人员', type: '按钮' }, { code: 'community:resident:update', label: '编辑人员', type: '按钮' }, { code: 'community:resident:audit', label: '认证审核', type: '按钮' }] },
  ] },
  { label: '资金与治理', items: [
    { label: '资金管理', code: 'finance', icon: LayoutDashboard, resources: [{ code: 'finance:overview:view', label: '资金看板', type: '页面' }, { code: 'finance:transaction:view', label: '资金流水', type: '页面' }, { code: 'finance:withdrawal:review', label: '提现复核', type: '按钮' }, { code: 'finance:adjustment:create', label: '资金处置', type: '按钮' }] },
    { label: '纠纷调解', code: 'governance:dispute', icon: ShieldCheck, resources: [{ code: 'governance:dispute:view', label: '查看纠纷', type: '页面' }, { code: 'governance:dispute:mediate', label: '调解记录', type: '按钮' }, { code: 'governance:dispute:resolve', label: '出具结论', type: '按钮' }] },
  ] },
  { label: '系统管理', items: [
    { label: '用户管理', code: 'system:user', icon: Users, resources: [{ code: 'system:user:view', label: '查看用户', type: '页面' }, { code: 'system:user:create', label: '新增用户', type: '按钮' }, { code: 'system:user:update', label: '编辑用户', type: '按钮' }] },
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

async function loadRoles() {
  try {
    roles.value = await rolesApi.list()
    if (!selectedId.value && roles.value[0]) {
      selectedId.value = roles.value[0].id
      await loadPermissions(selectedId.value)
    }
  } catch (exc: any) {
    app.showToast(exc?.message || '角色加载失败')
  }
}

async function createRole() {
  if (!newRoleName.value.trim()) return
  try {
    const role = await rolesApi.create({ name: newRoleName.value.trim(), description: '自定义角色，尚未配置权限', dataScope: 'OWN_COMMUNITY' })
    newRoleName.value = ''
    creating.value = false
    await loadRoles()
    await selectRole(role)
    app.showToast('角色已创建')
  } catch (exc: any) {
    app.showToast(exc?.message || '创建失败')
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
  if (role.builtin || !window.confirm(`确定删除角色“${role.name}”吗？`)) return
  try {
    await rolesApi.remove(role.id)
    await loadRoles()
    app.showToast('角色已删除')
  } catch (exc: any) {
    app.showToast(exc?.message || '删除失败')
  }
}

onMounted(async () => {
  expanded.value = new Set(groups.flatMap((group) => group.items.map((item) => item.code)))
  await loadRoles()
})
</script>

<template>
  <section class="page-heading list-heading role-page-heading">
    <div><p>系统管理 / 角色权限</p><h1>角色权限</h1><span>管理角色成员，并按菜单页面和页面资源精细配置访问权限</span></div>
    <button class="primary-button" @click="creating = true"><Plus :size="17" />新建角色</button>
  </section>

  <section class="role-permission-workspace">
    <aside class="role-list-panel">
      <div class="role-list-heading"><div><strong>角色列表</strong><span>{{ roles.length }} 个角色</span></div><button @click="creating = true"><Plus :size="16" /></button></div>
      <div class="role-search"><Search :size="15" /><input v-model="roleQuery" placeholder="搜索角色名称或编码" /></div>
      <div v-if="creating" class="create-role-form" style="margin: 0 12px 8px; padding: 5px; display: flex; align-items: center; gap: 4px; border: 1px solid #cfc6ec; border-radius: 9px">
        <input v-model="newRoleName" autofocus placeholder="输入角色名称" style="flex: 1; border: 0; font-size: 10px" @keyup.enter="createRole" />
        <button style="width: 25px; height: 25px; color: #fff; background: #7059d2; border-radius: 6px" @click="createRole"><Check :size="14" /></button>
        <button style="width: 25px; height: 25px" @click="creating = false"><X :size="14" /></button>
      </div>
      <div class="role-list">
        <div v-for="role in filteredRoles" :key="role.id" :class="['role-card', { selected: selectedId === role.id }]" @click="selectRole(role)">
          <div :class="['role-card-icon', { super: role.builtin }]"><ShieldCheck :size="17" /></div>
          <div class="role-card-content">
            <div class="role-card-title"><strong>{{ role.name }}</strong><em v-if="role.builtin">内置</em></div>
            <p>{{ role.description }}</p><span>{{ role.members }} 名成员 · {{ role.code }}</span>
          </div>
          <div v-if="!role.builtin" class="role-card-actions"><button title="删除角色" @click="deleteRole(role, $event)"><Trash2 :size="14" /></button></div>
        </div>
      </div>
      <div class="role-list-footer"><Users :size="14" />共 {{ roles.reduce((sum, role) => sum + role.members, 0) }} 名成员已分配角色</div>
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
  </section>
</template>
