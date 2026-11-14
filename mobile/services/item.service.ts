import * as itemApi from '../api/item.api'
import { ApiError } from '../api/errors'
import type {
  AuditProgress,
  CreateItemResult,
  CreditInfo,
  DistanceInfo,
  FavoriteBundle,
  HomeBundle,
  Item,
  ItemComment,
  ItemDraft,
  MineStats,
  PageResult,
  SearchResult,
  ZoneKey,
} from '../models'
import { validateItemDraft } from '../utils/validator'

export const itemService = {
  getHome(): Promise<HomeBundle> {
    return itemApi.getHomeBundle()
  },

  getNearby(page = 1, pageSize = 20): Promise<PageResult<Item>> {
    return itemApi.getItems({ page, pageSize, near: true, sort: '离我最近' })
  },

  getZone(
    zone: ZoneKey,
    options: { category?: string; sort?: string; page?: number; pageSize?: number } = {},
  ): Promise<PageResult<Item>> {
    return itemApi.getItems({
      zone,
      category: options.category,
      sort: options.sort,
      page: options.page ?? 1,
      pageSize: options.pageSize ?? 4,
    })
  },

  async getDetail(id: string): Promise<Item> {
    if (!id) throw new ApiError(40001, '缺少物品 ID')
    const item = await itemApi.getItemDetail(id)
    itemApi.addViewHistory(id).catch(() => undefined)
    return item
  },

  getComments(id: string): Promise<ItemComment[]> {
    return itemApi.getItemComments(id)
  },

  addComment(id: string, content: string): Promise<ItemComment> {
    if (!content.trim()) throw new ApiError(40001, '留言内容不能为空')
    return itemApi.addItemComment(id, content.trim())
  },

  toggleFavorite(id: string): Promise<{ favorite: boolean }> {
    return itemApi.toggleFavorite(id)
  },

  async publish(draft: ItemDraft): Promise<CreateItemResult> {
    const validation = validateItemDraft(draft)
    if (!validation.valid) {
      const first = Object.values(validation.errors)[0]
      throw new ApiError(40001, first)
    }
    const created = await itemApi.createItem(draft)
    await itemApi.submitItem(created.id)
    return created
  },

  submit(id: string): Promise<{ auditId: string; status: string }> {
    return itemApi.submitItem(id)
  },

  getAuditProgress(id: string): Promise<AuditProgress> {
    return itemApi.getAuditProgress(id)
  },

  getMyItems(page = 1, pageSize = 20): Promise<PageResult<Item>> {
    return itemApi.getMyItems(page, pageSize)
  },

  update(id: string, draft: Partial<ItemDraft>): Promise<Item> {
    return itemApi.updateItem(id, draft)
  },

  renew(id: string): Promise<{ success: boolean }> {
    return itemApi.renewItem(id)
  },

  offShelf(id: string): Promise<{ success: boolean }> {
    return itemApi.offShelfItem(id)
  },

  remove(id: string): Promise<{ success: boolean }> {
    return itemApi.deleteItem(id)
  },

  getFavorites(type: 'item' | 'service' | 'life' = 'item'): Promise<FavoriteBundle> {
    return itemApi.getFavorites(type)
  },

  getHistory(): Promise<Item[]> {
    return itemApi.getViewHistory()
  },

  search(keyword: string): Promise<SearchResult> {
    return itemApi.searchAll(keyword.trim())
  },

  getHotKeywords(): Promise<string[]> {
    return itemApi.getHotKeywords()
  },

  getSearchHistory(): Promise<string[]> {
    return itemApi.getSearchHistory()
  },

  addSearchHistory(keyword: string): Promise<string[]> {
    return itemApi.addSearchHistory(keyword)
  },

  clearSearchHistory(): Promise<string[]> {
    return itemApi.clearSearchHistory()
  },

  getMineStats(): Promise<MineStats> {
    return itemApi.getMineStats()
  },

  getCreditInfo(): Promise<CreditInfo> {
    return itemApi.getCreditInfo()
  },

  getDistance(id: string): Promise<DistanceInfo> {
    return itemApi.getItemDistance(id)
  },
}
