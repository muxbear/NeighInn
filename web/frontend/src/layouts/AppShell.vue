<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, ChevronDown, ChevronRight, Command, Home, Menu, Search, X } from 'lucide-vue-next'
import { figmaNavGroups, type NavItem } from '@/config/nav'
import { fmtRelative } from '@/api/compat'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useTodoStore } from '@/stores/todos'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const app = useAppStore()
const todos = useTodoStore()
const noticeOpen = ref(false)
const communityOpen = ref(false)
const commandOpen = ref(false)
const commandQuery = ref('')
const avatarOpen = ref(false)

const visibleTodos = computed(() =>
  todos.items.filter((item) => item.count > 0 && (!item.permission || auth.hasPermission(item.permission))),
)
const todoTotal = computed(() => visibleTodos.value.reduce((sum, item) => sum + item.count, 0))

const visibleGroups = computed(() =>
  figmaNavGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.permission || auth.hasPermission(item.permission)),
    }))
    .filter((group) => group.items.length > 0),
)

const allItems = computed<NavItem[]>(() => visibleGroups.value.flatMap((group) => group.items))
const currentTitle = computed(() => allItems.value.find((item) => item.route === route.path)?.label || (route.meta.title as string) || '工作台')
const filteredCommands = computed(() => {
  const query = commandQuery.value.trim().toLowerCase()
  return allItems.value
    .filter((item) => !query || item.label.toLowerCase().includes(query))
    .slice(0, 8)
})

function navigate(path: string) {
  commandOpen.value = false
  app.toggleSidebar(false)
  router.push(path)
}

function selectCommunity(id: number) {
  app.switchCommunity(id)
  communityOpen.value = false
}

function openCommand() {
  commandOpen.value = true
  commandQuery.value = ''
}

function openTodo(item: any) {
  noticeOpen.value = false
  if (item.key === 'certification') {
    router.push({
      path: item.route || '/governance/verification',
      query: {
        status: 'PENDING',
        ...(item.latestCertId ? { certId: item.latestCertId } : {}),
      },
    })
    return
  }
  router.push(item.route || '/dashboard')
}

function openDashboard() {
  noticeOpen.value = false
  router.push('/dashboard')
}

async function logout() {
  await auth.logout()
  router.push('/login')
}

onMounted(() => {
  app.loadCommunities().catch(() => undefined)
  todos.startPolling()
  window.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault()
      openCommand()
    }
    if (event.key === 'Escape') {
      commandOpen.value = false
      noticeOpen.value = false
      communityOpen.value = false
      avatarOpen.value = false
    }
  })
})

onUnmounted(() => {
  todos.stopPolling()
})

watch(() => route.path, () => {
  noticeOpen.value = false
})
</script>

<template>
  <div class="app-shell">
    <div v-if="app.sidebarOpen" class="mobile-backdrop" @click="app.toggleSidebar(false)" />
    <aside :class="['sidebar', { open: app.sidebarOpen }]">
      <div class="brand">
        <div class="brand-mark"><Home :size="18" :stroke-width="2.4" /></div>
        <div>
          <strong>邻里小栈</strong>
          <span>社区运营管理平台</span>
        </div>
        <button class="mobile-close" @click="app.toggleSidebar(false)"><X :size="20" /></button>
      </div>

      <div style="position: relative">
        <button class="community-switcher" style="width: calc(100% - 28px); text-align: left" @click="communityOpen = !communityOpen">
          <div class="community-icon">云</div>
          <div>
            <span>当前运营空间</span>
            <strong>{{ app.currentCommunity?.name || '云栖里社区' }}</strong>
          </div>
          <ChevronDown :size="15" />
        </button>
        <div v-if="communityOpen" class="notification-popover" style="top: 64px; left: 14px; right: 14px; width: auto; padding: 6px">
          <button
            v-for="community in app.communities"
            :key="community.id"
            style="width: 100%; padding: 9px 10px; text-align: left; border-radius: 8px; font-size: var(--font-size-body); display: flex; justify-content: space-between"
            :style="{ background: Number(community.id) === app.currentCommunityId ? '#f1edfc' : 'transparent' }"
            @click="selectCommunity(Number(community.id))"
          >
            <span>{{ community.name }}</span>
            <span style="color: #aaa6b1; font-size: var(--font-size-caption)">{{ community.code }}</span>
          </button>
        </div>
      </div>

      <nav>
        <div v-for="group in visibleGroups" :key="group.label" class="nav-group">
          <div class="nav-label">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.id"
            :class="['nav-item', { active: route.path === item.route }]"
            @click="navigate(item.route)"
          >
            <component :is="item.icon" :size="18" :stroke-width="2" />
            <span>{{ item.label }}</span>
            <em v-if="item.badge">{{ item.badge }}</em>
          </button>
        </div>
      </nav>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="topbar-left">
          <button class="menu-button" @click="app.toggleSidebar(true)"><Menu :size="21" /></button>
          <div class="breadcrumb">
            <span>邻里小栈</span>
            <ChevronRight :size="14" />
            <strong>{{ currentTitle }}</strong>
          </div>
        </div>
        <div class="topbar-actions">
          <button class="search-trigger" @click="openCommand">
            <Search :size="17" />
            <span>搜索功能或数据</span>
            <kbd>⌘ K</kbd>
          </button>
          <button class="icon-button" :aria-label="`待办提醒，共 ${todoTotal} 项`" @click="noticeOpen = !noticeOpen">
            <Bell :size="19" />
            <span v-if="todoTotal > 0" class="todo-count-badge">{{ todoTotal > 99 ? '99+' : todoTotal }}</span>
          </button>
          <button class="top-avatar" @click="avatarOpen = !avatarOpen">{{ auth.admin?.avatarText || '夏' }}</button>
        </div>
        <div v-if="noticeOpen" class="notification-popover">
          <div class="popover-title">
            <strong>待办提醒</strong>
            <button :disabled="todos.loading" @click="todos.refresh()">{{ todos.loading ? '刷新中' : '刷新' }}</button>
          </div>
          <div
            v-for="item in visibleTodos.slice(0, 5)"
            :key="item.key"
            class="notice-item notice-item--button"
            @click="openTodo(item)"
          >
            <span :class="['notice-dot', item.color || 'blue']" />
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.description || '待处理事项' }}</p>
            </div>
            <time>{{ item.oldestPendingAt ? fmtRelative(item.oldestPendingAt) : '' }}</time>
            <em>{{ item.count }}</em>
          </div>
          <div v-if="!visibleTodos.length" class="notice-empty">
            <span>暂无待办</span>
            <p>当前没有需要处理的认证或运营事项</p>
          </div>
          <button v-else class="notice-footer" @click="openDashboard">查看全部待办</button>
        </div>
        <div v-if="avatarOpen" class="notification-popover" style="right: 20px; width: 180px; padding: 6px">
          <div style="padding: 9px 10px; color: #777381; font-size: var(--font-size-body)">{{ auth.admin?.realName }} · {{ auth.admin?.roles?.[0]?.name }}</div>
          <button style="width: 100%; padding: 9px 10px; text-align: left; border-radius: 8px; font-size: var(--font-size-body); color: #c85660" @click="logout">退出登录</button>
        </div>
      </header>

      <div class="content">
        <RouterView />
      </div>
    </main>

    <div v-if="commandOpen" class="modal-backdrop" @mousedown.self="commandOpen = false">
      <div class="modal-card">
        <div class="command-input" style="height: 50px; padding: 0 12px; display: flex; align-items: center; gap: 9px; border-bottom: 1px solid #ece9f0; color: #817c8c">
          <Search :size="19" />
          <input v-model="commandQuery" autofocus placeholder="搜索用户、内容、工单或功能…" style="flex: 1; border: 0; font-size: var(--font-size-body)" />
          <kbd>ESC</kbd>
        </div>
        <div style="padding: 8px">
          <p style="padding: 8px 10px 6px; margin: 0; color: #aaa6b2; font-size: var(--font-size-caption); font-weight: 600; letter-spacing: .08em">快捷访问</p>
          <button
            v-for="item in filteredCommands"
            :key="item.id"
            style="width: 100%; padding: 10px; display: flex; align-items: center; gap: 10px; border-radius: 8px; color: #5a5663; font-size: var(--font-size-body)"
            @click="navigate(item.route)"
          >
            <component :is="item.icon" :size="18" />
            <span style="flex: 1; text-align: left">{{ item.label }}</span>
            <ChevronRight :size="16" />
          </button>
          <div v-if="!filteredCommands.length" class="empty-state" style="height: 120px">
            <Command :size="24" />
            <strong>未找到功能</strong>
          </div>
        </div>
      </div>
    </div>

    <div v-if="app.toastMessage" class="toast">
      <span>✓</span>{{ app.toastMessage }}
    </div>
  </div>
</template>
