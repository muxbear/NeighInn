/**
 * 统一服务端分页响应适配。
 *
 * web/backend 的分页契约是 { items, page, pageSize, total, hasMore }；
 * 移动端内部模型（models/common.model.ts PageResult）统一使用 { list, ... }。
 * 在 HTTP 边界把 items 映射为 list，避免各 store 直接依赖服务端字段名，
 * 也避免后端契约变化时逐个修改页面。
 */
export function normalizePageResult<T>(data: any): T {
  if (
    data &&
    typeof data === 'object' &&
    Array.isArray(data.items) &&
    data.list === undefined &&
    ('hasMore' in data || 'total' in data)
  ) {
    return { ...data, list: data.items } as T
  }
  return data as T
}
