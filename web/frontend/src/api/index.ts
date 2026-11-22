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
  changePassword: (oldPassword: string, newPassword: string) =>
    http.post<any, any>('/auth/password/change', { oldPassword, newPassword }),
}

export const dashboardApi = {
  summary: async (communityId?: number) => normalizeDashboard(await http.get<any, any>('/dashboard/summary', { params: { communityId } })),
  trend: async (days = 7, communityId?: number) => normalizeTrend(await http.get<any, any>('/dashboard/trend', { params: { days, communityId } })),
  todos: async (communityId?: number) =>
    ((await http.get<any, any>('/dashboard/todos', { params: { communityId } })) as any[]).map(normalizeTodo),
  activities: async (communityId?: number, limit = 6) => (await http.get<any, any>('/dashboard/activities', { params: { communityId, limit } }) as any[]).map(normalizeActivity),
}

// 区划为低频变更数据：省级节点缓存到 sessionStorage，子级缓存在内存；
// 后端同时按父节点做 10 分钟进程内缓存，页面按需分级加载。
// 注意：区划种子重新导入后必须递增下面的 vN 版本号，否则已打开过页面的浏览器
// 会在 12 小时内继续使用旧树（典型症状：选择某些省份后地市下拉框为空/禁用）。
const REGION_ROOTS_CACHE_KEY = 'ni_admin_region_roots_v3'
const REGION_TREE_CACHE_KEY = 'ni_admin_region_tree_v3'
const REGION_CHILDREN_CACHE_PREFIX = 'ni_admin_region_children_v3_'
const REGION_CACHE_TTL_MS = 12 * 60 * 60 * 1000
let regionRootsMemory: any[] | null = null
let regionTreeMemory: any[] | null = null
const regionChildrenMemory = new Map<string, any[]>()

// 升级时清理旧版区划缓存：旧树可能缺少下级区划，且大对象会挤占 sessionStorage 配额。
try {
  for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
    const key = sessionStorage.key(index)
    if (key?.startsWith('ni_admin_region_roots_v2')
        || key?.startsWith('ni_admin_region_tree_v2')
        || key?.startsWith('ni_admin_region_children_v2_')) {
      sessionStorage.removeItem(key)
    }
  }
} catch {
  // sessionStorage 不可用时忽略
}

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
  remove: (id: number | string, cancelAccount = false) =>
    http.delete<any, any>(`/residents/${id}`, {
      params: cancelAccount ? { cancelAccount: true } : undefined,
    }),
  batchRemove: (ids: Array<number | string>, cancelAccounts = false) =>
    http.post<any, any>('/residents/batch-delete', { ids, cancelAccounts }),
}

export const operationsApi = {
  overview: (module: string, params: Dict = {}) => http.get<any, any>('/operations/overview', { params: { module, ...params } }),
  list: async (module: string, params: Dict = {}) => mapItems(await http.get<any, any>(`/${module}`, { params }), (row) => normalizeOperationRow(module, row)),
  create: (module: string, payload: Dict) => http.post<any, any>(`/${module}`, payload),
  broadcastDetail: (id: number | string) => http.get<any, any>(`/broadcasts/${id}`),
  updateBroadcast: (id: number | string, payload: Dict) => http.put<any, any>(`/broadcasts/${id}`, payload),
  deleteBroadcast: (id: number | string) => http.delete<any, any>(`/broadcasts/${id}`),
  batchDeleteBroadcasts: (ids: Array<string | number>) =>
    http.post<any, any>('/broadcasts/batch-delete', { ids: ids.map((id) => Number(id)) }),
  itemDetail: (id: number | string) => http.get<any, any>(`/items/${id}`),
  lifeDetail: (id: number | string) => http.get<any, any>(`/life-posts/${id}`),
  helpDetail: (id: number | string) => http.get<any, any>(`/help-requests/${id}`),
  itemAudit: (id: number | string) => http.get<any, any>(`/items/${id}/ai-audit`),
  itemCategories: () => http.get<any, any>('/item-categories'),
  updateItem: (id: number | string, payload: Dict) => http.put<any, any>(`/items/${id}`, payload),
  deleteItem: (id: number | string) => http.delete<any, any>(`/items/${id}`),
  updateLife: (id: number | string, payload: Dict) => http.put<any, any>(`/life-posts/${id}`, payload),
  deleteLife: (id: number | string) => http.delete<any, any>(`/life-posts/${id}`),
  updateHelp: (id: number | string, payload: Dict) => http.put<any, any>(`/help-requests/${id}`, payload),
  deleteHelp: (id: number | string) => http.delete<any, any>(`/help-requests/${id}`),
  batchDeleteHelp: (ids: Array<string | number>) =>
    http.post<any, any>('/help-requests/batch-delete', { ids: ids.map((id) => Number(id)) }),
  reviewHelp: (id: number | string, decision: 'APPROVE' | 'REJECT', reason = '') =>
    http.post<any, any>(`/help-requests/${id}/review`, { decision, reason }),
  helpResponses: (id: number | string) => http.get<any, any>(`/help-requests/${id}/responses`),
  review: (module: string, id: number | string, payload: Dict = { decision: 'APPROVE' }) =>
    http.post<any, any>(`/${module}/${id}/review`, payload),
  // 物品下架接口强制要求 reason（FastAPI 请求体缺失会返回 422 参数校验失败）
  offline: (module: string, id: number | string, reason = '') =>
    http.post<any, any>(`/${module}/${id}/offline`, { reason }),
  recommend: (id: number | string, enabled = true) => http.post<any, any>(`/items/${id}/recommend`, { enabled }),
  matchHelp: (id: number | string, responderId?: number | string) =>
    http.post<any, any>(`/help-requests/${id}/match`, { responderId: Number(responderId) }),
  closeHelp: (id: number | string, reason = '') => http.post<any, any>(`/help-requests/${id}/close`, { reason }),
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

/** 社区住户后台身份授权（社区业主页）。 */
export const residentAdminApi = {
  roles: () => http.get<any, any>('/resident-admin-roles'),
  account: (residentId: number | string) =>
    http.get<any, any>(`/residents/${residentId}/admin-account`),
  grant: (residentId: number | string,
          payload: { roleIds: number[]; username?: string; reason?: string }) =>
    http.post<any, any>(`/residents/${residentId}/admin-account`, payload),
  revoke: (residentId: number | string) =>
    http.post<any, any>(`/residents/${residentId}/admin-account/revoke`, {}),
  resetPassword: (residentId: number | string) =>
    http.post<any, any>(`/residents/${residentId}/admin-account/reset-password`, {}),
}

export const usersApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/users', { params }), normalizePlatformUser),
  create: (payload: Dict) => http.post<any, any>('/users', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/users/${id}`, payload),
  toggle: (id: number | string) => http.patch<any, any>(`/users/${id}/status`, {}),
}

/** 后台管理员账号（系统管理 / 用户管理页）。 */
export const adminUsersApi = {
  list: (params: Dict = {}) => http.get<any, any>('/admin-users', { params }),
  create: (payload: Dict) => http.post<any, any>('/admin-users', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/admin-users/${id}`, payload),
  remove: (id: number | string) => http.delete<any, any>(`/admin-users/${id}`),
  batchRemove: (ids: Array<string | number>) =>
    http.post<any, any>('/admin-users/batch-delete', { ids: ids.map((id) => Number(id)) }),
  toggleStatus: (id: number | string, status: 'ACTIVE' | 'DISABLED') =>
    http.patch<any, any>(`/admin-users/${id}/status`, { status }),
  resetPassword: (id: number | string, password: string) =>
    http.post<any, any>(`/admin-users/${id}/reset-password`, { password }),
  unlock: (id: number | string) => http.post<any, any>(`/admin-users/${id}/unlock`),
  residentOptions: (params: Dict = {}) => http.get<any, any>('/resident-options', { params }),
  /** 关联 / 解除关联住户（residentId 传 null 表示解除）。 */
  linkResident: (id: number | string, residentId: number | null) =>
    http.put<any, any>(`/admin-users/${id}/resident`, { residentId }),
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
  /** 人工认证候选住户：认证未通过且可发起审核的住户。 */
  candidates: (params: Dict = {}) => http.get<any, any>('/certifications/candidates', { params }),
  /** 后台人工认证（住户认证 / 身份认证），支持未提交、待补充、已驳回等状态。 */
  verifyResident: (residentId: number | string, type: 'REALNAME' | 'OWNER_PROOF',
                   payload: { identity?: string; note?: string }) =>
    http.post<any, any>(`/residents/${residentId}/certifications/${type}/verify`, payload),
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

export const filesApi = {
  /** 管理端公开媒体上传（生活内容配图/短视频），返回 objectKey 与可访问 URL。 */
  uploadMedia: (file: File, scene: 'LIFE_IMAGE' | 'LIFE_VIDEO' | 'PUBLIC_IMAGE' = 'LIFE_IMAGE') => {
    const form = new FormData()
    form.append('file', file)
    form.append('scene', scene)
    return http.post<any, any>('/files/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
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
