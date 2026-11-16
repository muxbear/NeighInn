import { http } from './client'
import {
  normalizeActivity,
  normalizeAudit,
  normalizeCertification,
  normalizeCommunity,
  normalizeDashboard,
  normalizeDispute,
  normalizeFeedback,
  normalizeFinanceOrder,
  normalizeNotice,
  normalizeOperationRow,
  normalizePlatformUser,
  normalizeReport,
  normalizeResident,
  normalizeTask,
  normalizeTodo,
  normalizeTrend,
  normalizeTxn,
  normalizeWithdrawal,
} from './compat'

type Dict = Record<string, any>

function mapItems(data: any, fn: (row: any) => any) {
  return { ...data, items: (data?.items || []).map(fn) }
}

export const authApi = {
  login: (payload: { username: string; password: string; otp?: string }) => http.post<any, any>('/auth/login', payload),
  me: () => http.get<any, any>('/auth/me'),
  logout: () => http.post<any, any>('/auth/logout'),
}

export const dashboardApi = {
  summary: async (communityId?: number) => normalizeDashboard(await http.get<any, any>('/dashboard/summary', { params: { communityId } })),
  trend: async (days = 7, communityId?: number) => normalizeTrend(await http.get<any, any>('/dashboard/trend', { params: { days, communityId } })),
  todos: async (communityId?: number) =>
    ((await http.get<any, any>('/dashboard/todos', { params: { communityId } })) as any[]).map(normalizeTodo),
  activities: async (communityId?: number, limit = 4) => (await http.get<any, any>('/dashboard/activities', { params: { communityId, limit } }) as any[]).map(normalizeActivity),
}

// 区划为低频变更数据：省级节点缓存到 sessionStorage，子级缓存在内存；
// 后端同时按父节点做 10 分钟进程内缓存，页面按需分级加载。
const REGION_ROOTS_CACHE_KEY = 'ni_admin_region_roots_v2'
const REGION_TREE_CACHE_KEY = 'ni_admin_region_tree_v2'
const REGION_CHILDREN_CACHE_PREFIX = 'ni_admin_region_children_v2_'
const REGION_CACHE_TTL_MS = 12 * 60 * 60 * 1000
let regionRootsMemory: any[] | null = null
let regionTreeMemory: any[] | null = null
const regionChildrenMemory = new Map<string, any[]>()

function readCachedRegionRoots(): any[] | null {
  try {
    const raw = sessionStorage.getItem(REGION_ROOTS_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.at || !Array.isArray(parsed.roots) || Date.now() - parsed.at > REGION_CACHE_TTL_MS) {
      sessionStorage.removeItem(REGION_ROOTS_CACHE_KEY)
      return null
    }
    return parsed.roots
  } catch {
    return null
  }
}

function writeCachedRegionRoots(roots: any[]): void {
  try {
    sessionStorage.setItem(REGION_ROOTS_CACHE_KEY, JSON.stringify({ at: Date.now(), roots }))
  } catch {
    // sessionStorage 不可用或超出配额时仅使用内存缓存
  }
}

function readCachedRegionTree(): any[] | null {
  try {
    const raw = sessionStorage.getItem(REGION_TREE_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.at || !Array.isArray(parsed.tree) || Date.now() - parsed.at > REGION_CACHE_TTL_MS) {
      sessionStorage.removeItem(REGION_TREE_CACHE_KEY)
      return null
    }
    return parsed.tree
  } catch {
    return null
  }
}

function writeCachedRegionTree(tree: any[]): void {
  try {
    sessionStorage.setItem(REGION_TREE_CACHE_KEY, JSON.stringify({ at: Date.now(), tree }))
  } catch {
    // sessionStorage 不可用或超出配额时仅使用内存缓存
  }
}

function readCachedRegionChildren(id: string): any[] | null {
  try {
    const raw = sessionStorage.getItem(`${REGION_CHILDREN_CACHE_PREFIX}${id}`)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.at || !Array.isArray(parsed.children) || Date.now() - parsed.at > REGION_CACHE_TTL_MS) {
      sessionStorage.removeItem(`${REGION_CHILDREN_CACHE_PREFIX}${id}`)
      return null
    }
    return parsed.children
  } catch {
    return null
  }
}

function writeCachedRegionChildren(id: string, children: any[]): void {
  try {
    sessionStorage.setItem(`${REGION_CHILDREN_CACHE_PREFIX}${id}`,
      JSON.stringify({ at: Date.now(), children }))
  } catch {
    // 配额不足时仅使用内存缓存
  }
}

export const communityApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/communities', { params }), normalizeCommunity),
  search: (q: string) => http.get<any, any>('/communities/search', { params: { q } }),
  detail: (id: number | string) => http.get<any, any>(`/communities/${id}`),
  create: (payload: Dict) => http.post<any, any>('/communities', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/communities/${id}`, payload),
  remove: (id: number | string) => http.delete<any, any>(`/communities/${id}`),
  importRows: (payload: Dict) => http.post<any, any>('/communities/import', payload),
  regionTree: async (): Promise<any[]> => {
    if (regionTreeMemory) return regionTreeMemory
    const cached = readCachedRegionTree()
    if (cached) {
      regionTreeMemory = cached
      return cached
    }
    const tree = await http.get<any, any>('/regions/tree')
    regionTreeMemory = tree
    writeCachedRegionTree(tree)
    return tree
  },
  regionRoots: async (): Promise<any[]> => {
    if (regionRootsMemory) return regionRootsMemory
    const cached = readCachedRegionRoots()
    if (cached) {
      regionRootsMemory = cached
      return cached
    }
    const roots = await http.get<any, any>('/regions/roots')
    regionRootsMemory = roots
    writeCachedRegionRoots(roots)
    return roots
  },
  regionChildren: async (id: number | string): Promise<any[]> => {
    const key = String(id)
    const cached = regionChildrenMemory.get(key)
    if (cached) return cached
    const stored = readCachedRegionChildren(key)
    if (stored) {
      regionChildrenMemory.set(key, stored)
      return stored
    }
    const children = await http.get<any, any>(`/regions/${id}/children`)
    regionChildrenMemory.set(key, children)
    writeCachedRegionChildren(key, children)
    return children
  },
  clearRegionCache: (): void => {
    regionRootsMemory = null
    regionTreeMemory = null
    regionChildrenMemory.clear()
    try {
      sessionStorage.removeItem(REGION_ROOTS_CACHE_KEY)
      sessionStorage.removeItem(REGION_TREE_CACHE_KEY)
      const keys: string[] = []
      for (let index = 0; index < sessionStorage.length; index += 1) {
        const key = sessionStorage.key(index)
        if (key?.startsWith(REGION_CHILDREN_CACHE_PREFIX)) keys.push(key)
      }
      keys.forEach((key) => sessionStorage.removeItem(key))
    } catch {
      // ignore
    }
  },
}

export const residentApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/residents', { params }), normalizeResident),
  summary: (communityId: number) => http.get<any, any>('/residents/summary', { params: { communityId } }),
  create: (payload: Dict) => http.post<any, any>('/residents', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/residents/${id}`, payload),
  remove: (id: number | string) => http.delete<any, any>(`/residents/${id}`),
}

export const operationsApi = {
  overview: (module: string) => http.get<any, any>('/operations/overview', { params: { module } }),
  list: async (module: string, params: Dict = {}) => mapItems(await http.get<any, any>(`/${module}`, { params }), (row) => normalizeOperationRow(module, row)),
  create: (module: string, payload: Dict) => http.post<any, any>(`/${module}`, payload),
  itemDetail: (id: number | string) => http.get<any, any>(`/items/${id}`),
  itemAudit: (id: number | string) => http.get<any, any>(`/items/${id}/ai-audit`),
  review: (module: string, id: number | string, payload: Dict = { decision: 'APPROVE' }) =>
    http.post<any, any>(`/${module}/${id}/review`, payload),
  offline: (module: string, id: number | string) => http.post<any, any>(`/${module}/${id}/offline`),
  recommend: (id: number | string, enabled = true) => http.post<any, any>(`/items/${id}/recommend`, { enabled }),
  matchHelp: (id: number | string, helper = '陈师傅') => http.post<any, any>(`/help-requests/${id}/match`, { helper }),
  closeHelp: (id: number | string) => http.post<any, any>(`/help-requests/${id}/close`),
}

export const noticesApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/notices', { params }), normalizeNotice),
  create: (payload: Dict) => http.post<any, any>('/notices', payload),
  publish: (id: number | string) => http.post<any, any>(`/notices/${id}/publish`),
  withdraw: (id: number | string) => http.post<any, any>(`/notices/${id}/withdraw`),
}

export const tasksApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/notification-tasks', { params }), normalizeTask),
  create: (payload: Dict) => http.post<any, any>('/notification-tasks', payload),
  send: (id: number | string) => http.post<any, any>(`/notification-tasks/${id}/send`),
  cancel: (id: number | string) => http.post<any, any>(`/notification-tasks/${id}/cancel`),
}

export const usersApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/users', { params }), normalizePlatformUser),
  create: (payload: Dict) => http.post<any, any>('/users', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/users/${id}`, payload),
  toggle: (id: number | string) => http.patch<any, any>(`/users/${id}/status`, {}),
}

export const repairApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/repair-orders', { params }), (row) => ({ ...row, status: row.status })),
  create: (payload: Dict) => http.post<any, any>('/repair-orders', payload),
  assign: (id: number | string, assignee: string) => http.post<any, any>(`/repair-orders/${id}/assign`, { assignee }),
  close: (id: number | string) => http.post<any, any>(`/repair-orders/${id}/close`),
}

export const feedbackApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/feedbacks', { params }), normalizeFeedback),
  reply: (id: number | string, reply: string) => http.post<any, any>(`/feedbacks/${id}/reply`, { reply }),
  close: (id: number | string) => http.post<any, any>(`/feedbacks/${id}/close`),
}

export const rolesApi = {
  list: () => http.get<any, any>('/roles'),
  create: (payload: Dict) => http.post<any, any>('/roles', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/roles/${id}`, payload),
  remove: (id: number | string) => http.delete<any, any>(`/roles/${id}`),
  permissions: (id: number | string) => http.get<any, any>(`/roles/${id}/permissions`),
  savePermissions: (id: number | string, permissions: string[]) =>
    http.put<any, any>(`/roles/${id}/permissions`, { permissions }),
  permissionTree: () => http.get<any, any>('/permissions/tree'),
}

export const resourcesApi = {
  tree: () => http.get<any, any>('/pages/tree'),
  detail: (id: number | string) => http.get<any, any>(`/pages/${id}`),
  resources: (id: number | string) => http.get<any, any>(`/pages/${id}/resources`),
  createResource: (id: number | string, payload: Dict) => http.post<any, any>(`/pages/${id}/resources`, payload),
}

export const parametersApi = {
  tree: () => http.get<any, any>('/parameter-nodes/tree'),
  items: (id: number | string) => http.get<any, any>(`/parameter-keys/${id}/items`),
  updateItem: (id: number | string, payload: Dict) => http.put<any, any>(`/parameter-items/${id}`, payload),
  toggleItem: (id: number | string) => http.patch<any, any>(`/parameter-items/${id}/status`, {}),
  publishItem: (id: number | string) => http.post<any, any>(`/parameter-items/${id}/publish`),
}

export const financeApi = {
  overview: () => http.get<any, any>('/finance/overview'),
  transactions: async (params: Dict = {}) => mapItems(await http.get<any, any>('/finance/transactions', { params }), normalizeTxn),
  withdrawals: async (params: Dict = {}) => mapItems(await http.get<any, any>('/finance/withdrawals', { params }), normalizeWithdrawal),
  reviewWithdrawal: (id: number | string, payload: Dict) => http.post<any, any>(`/finance/withdrawals/${id}/review`, payload),
  retryWithdrawal: (id: number | string) => http.post<any, any>(`/finance/withdrawals/${id}/retry`),
  reconciliations: () => http.get<any, any>('/finance/reconciliations'),
  recheck: (id: number | string) => http.post<any, any>(`/finance/reconciliations/${id}/recheck`),
  orders: async (params: Dict = {}) => mapItems(await http.get<any, any>('/finance/orders', { params }), normalizeFinanceOrder),
}

export const disputesApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/disputes', { params }), normalizeDispute),
  detail: (id: number | string) => http.get<any, any>(`/disputes/${id}`),
  mediate: (id: number | string, note: string) => http.post<any, any>(`/disputes/${id}/mediate`, { note }),
  resolve: (id: number | string, payload: Dict) => http.post<any, any>(`/disputes/${id}/resolve`, payload),
  freeze: (id: number | string, reason: string) => http.post<any, any>(`/disputes/${id}/freeze`, { reason }),
}

export const certificationsApi = {
  list: (params: Dict = {}) => http.get<any, any>('/certifications', { params })
    .then((data: any) => mapItems(data, normalizeCertification)),
  summary: (params: Dict = {}) => http.get<any, any>('/certifications/summary', { params }),
  detail: (id: number | string) => http.get<any, any>(`/certifications/${id}`),
  approve: (id: number | string) => http.post<any, any>(`/certifications/${id}/approve`, {}),
  reject: (id: number | string, reason: string) => http.post<any, any>(`/certifications/${id}/reject`, { reason }),
  requestMaterials: (id: number | string, note: string) => http.post<any, any>(`/certifications/${id}/request-materials`, { note }),
  freezeResident: (residentId: number | string) => http.post<any, any>(`/residents/${residentId}/freeze`, {}),
  unfreezeResident: (residentId: number | string) => http.post<any, any>(`/residents/${residentId}/unfreeze`, {}),
  materials: (residentId: number | string, type: 'REALNAME' | 'OWNER_PROOF') =>
    http.get<any, any>(`/residents/${residentId}/certifications/${type}/materials`),
  uploadMaterial: (residentId: number | string, type: 'REALNAME' | 'OWNER_PROOF', file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post<any, any>(`/residents/${residentId}/certifications/${type}/materials`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  removeMaterial: (residentId: number | string, type: 'REALNAME' | 'OWNER_PROOF', objectKey: string) =>
    http.delete<any, any>(`/residents/${residentId}/certifications/${type}/materials`, { params: { objectKey } }),
}

export const reportsApi = {
  list: (params: Dict = {}) => http.get<any, any>('/reports', { params })
    .then((data: any) => mapItems(data, normalizeReport)),
  handle: (id: number | string, payload: Dict) => http.post<any, any>(`/reports/${id}/handle`, payload),
}

export const auditApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/audit-logs', { params }), normalizeAudit),
  detail: (id: number | string) => http.get<any, any>(`/audit-logs/${id}`),
}

export const exportsApi = {
  list: () => http.get<any, any>('/exports'),
}
