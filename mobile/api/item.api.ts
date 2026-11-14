import type {
  AuditProgress,
  AuditSubmitResult,
  CreateItemResult,
  CreditInfo,
  DistanceInfo,
  FavoriteBundle,
  HomeBundle,
  Item,
  ItemComment,
  ItemDraft,
  ItemQuery,
  MineStats,
  PageResult,
  SearchResult,
} from '../models'
import { del, get, post, put } from './request'
import { withQuery } from './query'

export function getHomeBundle(): Promise<HomeBundle> {
  return get<HomeBundle>('/home')
}

export function getItems(query: ItemQuery = {}): Promise<PageResult<Item>> {
  return get<PageResult<Item>>(withQuery('/items', query))
}

export function getMyItems(page = 1, pageSize = 20): Promise<PageResult<Item>> {
  return get<PageResult<Item>>(withQuery('/items/mine', { page, pageSize }))
}

export function getItemDetail(id: string): Promise<Item> {
  return get<Item>(`/items/${id}`)
}

export function createItem(draft: ItemDraft): Promise<CreateItemResult> {
  return post<CreateItemResult>('/items', draft as unknown as Record<string, any>, { loading: true })
}

export function submitItem(id: string): Promise<AuditSubmitResult> {
  return post<AuditSubmitResult>(`/items/${id}/submit`, {}, { loading: true })
}

export function getAuditProgress(id: string): Promise<AuditProgress> {
  return get<AuditProgress>(`/items/${id}/audit-progress`, undefined, { retry: false })
}

export function updateItem(id: string, draft: Partial<ItemDraft>): Promise<Item> {
  return put<Item>(`/items/${id}`, draft as Record<string, any>, { loading: true })
}

export function renewItem(id: string): Promise<{ success: boolean }> {
  return post(`/items/${id}/renew`, {})
}

export function offShelfItem(id: string): Promise<{ success: boolean }> {
  return post(`/items/${id}/off-shelf`, {})
}

export function deleteItem(id: string): Promise<{ success: boolean }> {
  return del(`/items/${id}`)
}

export function getItemComments(id: string): Promise<ItemComment[]> {
  return get<ItemComment[]>(`/items/${id}/comments`)
}

export function addItemComment(id: string, content: string): Promise<ItemComment> {
  return post<ItemComment>(`/items/${id}/comments`, { content })
}

export function toggleFavorite(id: string): Promise<{ favorite: boolean }> {
  return post<{ favorite: boolean }>(`/items/${id}/favorite`, {}, { idempotent: false })
}

export function getItemDistance(id: string): Promise<DistanceInfo> {
  return get<DistanceInfo>(`/items/${id}/distance`)
}

export function getFavorites(type: 'item' | 'service' | 'life' = 'item'): Promise<FavoriteBundle> {
  return get<FavoriteBundle>(withQuery('/favorites', { type }))
}

export function addFavorite(id: string): Promise<{ success: boolean }> {
  return post('/favorites', { id })
}

export function removeFavorite(id: string): Promise<{ success: boolean }> {
  return del('/favorites', { id })
}

export function getViewHistory(): Promise<Item[]> {
  return get<Item[]>('/history')
}

export function addViewHistory(id: string): Promise<{ success: boolean }> {
  return post('/history', { id }, { idempotent: false })
}

export function searchAll(keyword: string): Promise<SearchResult> {
  return get<SearchResult>(withQuery('/search', { keyword }))
}

export function getHotKeywords(): Promise<string[]> {
  return get<string[]>('/search/hot')
}

export function getSearchHistory(): Promise<string[]> {
  return get<string[]>('/search/history')
}

export function addSearchHistory(keyword: string): Promise<string[]> {
  return post<string[]>('/search/history', { keyword }, { idempotent: false })
}

export function clearSearchHistory(): Promise<string[]> {
  return del<string[]>('/search/history')
}

export function getMineStats(): Promise<MineStats> {
  return get<MineStats>('/mine/stats')
}

export function getCreditInfo(): Promise<CreditInfo> {
  return get<CreditInfo>('/mine/credit')
}
