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

export const communityApi = {
  list: async (params: Dict = {}) => mapItems(await http.get<any, any>('/communities', { params }), normalizeCommunity),
  search: (q: string) => http.get<any, any>('/communities/search', { params: { q } }),
  detail: (id: number) => http.get<any, any>(`/communities/${id}`),
  regionTree: () => http.get<any, any>('/regions/tree'),
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
