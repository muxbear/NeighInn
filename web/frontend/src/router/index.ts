import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/pages/LoginPage.vue'), meta: { public: true, title: '登录' } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('@/pages/DashboardPage.vue'), meta: { title: '工作台', permission: 'dashboard:view' } },
  {
    path: '/community-operations/:module(broadcast|items|help|life)',
    name: 'operations',
    component: () => import('@/pages/OperationsPage.vue'),
    meta: { title: '社区运营', permission: 'community:broadcast:view' },
  },
  { path: '/communication/notices', name: 'notices', component: () => import('@/pages/NoticesPage.vue'), meta: { title: '公告管理', permission: 'communication:notice:view' } },
  { path: '/communication/notification-tasks', name: 'tasks', component: () => import('@/pages/NotificationTasksPage.vue'), meta: { title: '通知任务', permission: 'communication:task:view' } },
  { path: '/community-management/maintenance', name: 'maintenance', component: () => import('@/pages/MaintenancePage.vue'), meta: { title: '社区运维', permission: 'community:maintenance:view' } },
  { path: '/community-management/residents', name: 'residents', component: () => import('@/pages/ResidentsPage.vue'), meta: { title: '社区业主', permission: 'community:resident:view' } },
  { path: '/system/users', name: 'users', component: () => import('@/pages/UsersPage.vue'), meta: { title: '用户管理', permission: 'system:admin-user:view' } },
  { path: '/system/roles', name: 'roles', component: () => import('@/pages/RolesPage.vue'), meta: { title: '角色权限', permission: 'system:role:view' } },
  { path: '/system/resources', name: 'resources', component: () => import('@/pages/ResourcesPage.vue'), meta: { title: '资源管理', permission: 'system:resource:view' } },
  { path: '/system/parameters', name: 'parameters', component: () => import('@/pages/ParametersPage.vue'), meta: { title: '参数配置', permission: 'system:parameter:view' } },
  { path: '/system/audit-logs', name: 'audit-logs', component: () => import('@/pages/AuditLogsPage.vue'), meta: { title: '审计日志', permission: 'system:audit:view' } },
  { path: '/finance/:tab(overview|transactions|withdrawals|reconciliations|orders)', name: 'finance', component: () => import('@/pages/FinancePage.vue'), meta: { title: '资金管理', permission: 'finance:overview:view' } },
  { path: '/governance/disputes', name: 'disputes', component: () => import('@/pages/DisputesPage.vue'), meta: { title: '纠纷调解', permission: 'governance:dispute:view' } },
  { path: '/governance/verification', name: 'verification', component: () => import('@/pages/CertificationsPage.vue'), meta: { title: '住户认证', permission: 'community:resident:audit' } },
  { path: '/governance/reports', name: 'reports', component: () => import('@/pages/ReportsPage.vue'), meta: { title: '举报处理', permission: 'governance:report:view' } },
  { path: '/governance/repair-orders', name: 'repairs', component: () => import('@/pages/RepairsPage.vue'), meta: { title: '报事报修', permission: 'governance:repair:view' } },
  { path: '/governance/feedback', name: 'feedback', component: () => import('@/pages/FeedbackPage.vue'), meta: { title: '投诉建议', permission: 'governance:feedback:view' } },
  { path: '/analytics/exports', name: 'exports', component: () => import('@/pages/PlaceholderPage.vue'), meta: { title: '报表导出', permission: 'reporting:export:view' } },
  { path: '/community/content', name: 'content', component: () => import('@/pages/PlaceholderPage.vue'), meta: { title: '邻里动态', permission: 'community:broadcast:view' } },
  { path: '/community/activities', name: 'activities', component: () => import('@/pages/PlaceholderPage.vue'), meta: { title: '社区活动', permission: 'community:life:view' } },
  { path: '/market/items', name: 'market-items', component: () => import('@/pages/PlaceholderPage.vue'), meta: { title: '闲置市集', permission: 'community:item:view' } },
  { path: '/market/services', name: 'market-services', component: () => import('@/pages/PlaceholderPage.vue'), meta: { title: '便民服务', permission: 'community:life:view' } },
  { path: '/forbidden', name: 'forbidden', component: () => import('@/pages/PlaceholderPage.vue'), meta: { title: '无权限', public: true } },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/pages/PlaceholderPage.vue'), meta: { title: '页面不存在', public: true } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0, behavior: 'smooth' }
  },
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuthStore()
  if (!auth.loaded) {
    try {
      await auth.fetchMe()
    } catch {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  if (!auth.isAuthenticated) return { name: 'login', query: { redirect: to.fullPath } }
  const permission = to.meta.permission as string | undefined
  if (permission && !auth.hasPermission(permission)) return { name: 'forbidden' }
  return true
})
