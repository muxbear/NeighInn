import { http } from './client'

type Dict = Record<string, any>

export const authApi = {
  login: (payload: { username: string; password: string; otp?: string }) => http.post<any, any>('/auth/login', payload),
  me: () => http.get<any, any>('/auth/me'),
  logout: () => http.post<any, any>('/auth/logout'),
}

export const dashboardApi = {
  summary: (communityId?: number) => http.get<any, any>('/dashboard/summary', { params: { communityId } }),
  trend: (days = 7, communityId?: number) => http.get<any, any>('/dashboard/trend', { params: { days, communityId } }),
  todos: (communityId?: number) => http.get<any, any>('/dashboard/todos', { params: { communityId } }),
  activities: (communityId?: number, limit = 4) => http.get<any, any>('/dashboard/activities', { params: { communityId, limit } }),
}

export const communityApi = {
  list: (params: Dict = {}) => http.get<any, any>('/communities', { params }),
  search: (q: string) => http.get<any, any>('/communities/search', { params: { q } }),
  detail: (id: number) => http.get<any, any>(`/communities/${id}`),
  regionTree: () => http.get<any, any>('/regions/tree'),
}

export const residentApi = {
  list: (params: Dict = {}) => http.get<any, any>('/residents', { params }),
  summary: (communityId: number) => http.get<any, any>('/residents/summary', { params: { communityId } }),
  create: (payload: Dict) => http.post<any, any>('/residents', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/residents/${id}`, payload),
  remove: (id: number | string) => http.delete<any, any>(`/residents/${id}`),
}

export const operationsApi = {
  overview: (module: string) => http.get<any, any>('/operations/overview', { params: { module } }),
  list: (module: string, params: Dict = {}) => http.get<any, any>(`/${module}`, { params }),
  create: (module: string, payload: Dict) => http.post<any, any>(`/${module}`, payload),
  review: (module: string, id: number | string, payload: Dict = { decision: 'APPROVE' }) =>
    http.post<any, any>(`/${module}/${id}/review`, payload),
  offline: (module: string, id: number | string) => http.post<any, any>(`/${module}/${id}/offline`),
  recommend: (id: number | string, enabled = true) => http.post<any, any>(`/items/${id}/recommend`, { enabled }),
  matchHelp: (id: number | string, helper = '陈师傅') => http.post<any, any>(`/help-requests/${id}/match`, { helper }),
  closeHelp: (id: number | string) => http.post<any, any>(`/help-requests/${id}/close`),
}

export const noticesApi = {
  list: (params: Dict = {}) => http.get<any, any>('/notices', { params }),
  create: (payload: Dict) => http.post<any, any>('/notices', payload),
  publish: (id: number | string) => http.post<any, any>(`/notices/${id}/publish`),
  withdraw: (id: number | string) => http.post<any, any>(`/notices/${id}/withdraw`),
}

export const tasksApi = {
  list: (params: Dict = {}) => http.get<any, any>('/notification-tasks', { params }),
  create: (payload: Dict) => http.post<any, any>('/notification-tasks', payload),
  send: (id: number | string) => http.post<any, any>(`/notification-tasks/${id}/send`),
  cancel: (id: number | string) => http.post<any, any>(`/notification-tasks/${id}/cancel`),
}

export const usersApi = {
  list: (params: Dict = {}) => http.get<any, any>('/users', { params }),
  create: (payload: Dict) => http.post<any, any>('/users', payload),
  update: (id: number | string, payload: Dict) => http.put<any, any>(`/users/${id}`, payload),
  toggle: (id: number | string) => http.patch<any, any>(`/users/${id}/status`, {}),
}

export const repairApi = {
  list: (params: Dict = {}) => http.get<any, any>('/repair-orders', { params }),
  create: (payload: Dict) => http.post<any, any>('/repair-orders', payload),
  assign: (id: number | string, assignee: string) => http.post<any, any>(`/repair-orders/${id}/assign`, { assignee }),
  close: (id: number | string) => http.post<any, any>(`/repair-orders/${id}/close`),
}

export const feedbackApi = {
  list: (params: Dict = {}) => http.get<any, any>('/feedbacks', { params }),
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
  transactions: (params: Dict = {}) => http.get<any, any>('/finance/transactions', { params }),
  withdrawals: (params: Dict = {}) => http.get<any, any>('/finance/withdrawals', { params }),
  reviewWithdrawal: (id: number | string, payload: Dict) => http.post<any, any>(`/finance/withdrawals/${id}/review`, payload),
  retryWithdrawal: (id: number | string) => http.post<any, any>(`/finance/withdrawals/${id}/retry`),
  reconciliations: () => http.get<any, any>('/finance/reconciliations'),
  recheck: (id: number | string) => http.post<any, any>(`/finance/reconciliations/${id}/recheck`),
  orders: (params: Dict = {}) => http.get<any, any>('/finance/orders', { params }),
}

export const disputesApi = {
  list: (params: Dict = {}) => http.get<any, any>('/disputes', { params }),
  mediate: (id: number | string, note: string) => http.post<any, any>(`/disputes/${id}/mediate`, { note }),
  resolve: (id: number | string, conclusion: string) => http.post<any, any>(`/disputes/${id}/resolve`, { conclusion }),
  freeze: (id: number | string, reason: string) => http.post<any, any>(`/disputes/${id}/freeze`, { reason }),
}

export const auditApi = {
  list: (params: Dict = {}) => http.get<any, any>('/audit-logs', { params }),
  detail: (id: number | string) => http.get<any, any>(`/audit-logs/${id}`),
}

export const exportsApi = {
  list: () => http.get<any, any>('/exports'),
}
