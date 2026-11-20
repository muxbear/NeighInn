import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { HomeBundle, Item, ItemComment, ZoneKey } from '../models'
import { itemService } from '../services/item.service'
import { STORAGE_KEYS } from '../config/constants'
import { getStorage, removeStorage, setStorage } from '../utils/storage'
import { logger } from '../utils/logger'

const HOME_CACHE_MS = 10 * 60 * 1000

interface HomeCache {
  feed: HomeBundle
  at: number
}

function feedKey(zone: ZoneKey, category: string, sort: string): string {
  return `${zone}::${category}::${sort}`
}

export const useItemStore = defineStore('item', () => {
  const cached = getStorage<HomeCache | null>(STORAGE_KEYS.homeFeed, null)
  const homeFeed = ref<HomeBundle | null>(cached?.feed ?? null)
  const homeLoadedAt = ref(cached?.at ?? 0)
  const homeLoading = ref(false)
  const homeError = ref('')

  const nearbyItems = ref<Item[]>([])
  const nearbyPage = ref(1)
  const nearbyHasMore = ref(true)
  const nearbyLoading = ref(false)

  const zoneFeeds = ref<Record<string, Item[]>>({})
  const zonePages = ref<Record<string, number>>({})
  const zoneHasMore = ref<Record<string, boolean>>({})
  const zoneLoading = ref<Record<string, boolean>>({})
  const zoneTotals = ref<Record<string, number>>({})

  const detailCache = ref<Record<string, Item>>({})
  const commentsCache = ref<Record<string, ItemComment[]>>({})
  const myItems = ref<Item[]>([])
  const myItemsLoading = ref(false)
  const favorites = ref<Item[]>([])

  const hourHotItems = computed(() => homeFeed.value?.hotItems ?? [])

  function applyFavorite(id: string, favorite: boolean): void {
    const apply = (item: Item) => {
      if (item.id === id) item.favorite = favorite
    }
    if (homeFeed.value) {
      homeFeed.value.hotItems.forEach(apply)
    }
    nearbyItems.value.forEach(apply)
    Object.values(zoneFeeds.value).forEach((list) => list.forEach(apply))
    myItems.value.forEach(apply)
    favorites.value.forEach(apply)
    Object.values(detailCache.value).forEach(apply)
  }

  async function fetchHome(force = false): Promise<void> {
    const fresh = Date.now() - homeLoadedAt.value < HOME_CACHE_MS
    if (!force && homeFeed.value && fresh) return
    homeLoading.value = true
    homeError.value = ''
    try {
      const feed = await itemService.getHome()
      feed.hotItems.forEach((item) => {
        if (item.favorite === undefined) item.favorite = false
      })
      homeFeed.value = feed
      homeLoadedAt.value = Date.now()
      setStorage<HomeCache>(STORAGE_KEYS.homeFeed, { feed, at: homeLoadedAt.value })
    } catch (error) {
      homeError.value = error instanceof Error ? error.message : '加载失败'
      logger.warn('ItemStore', 'fetchHome failed', error)
      if (!homeFeed.value) throw error
    } finally {
      homeLoading.value = false
    }
  }

  async function fetchNearby(refresh = false): Promise<void> {
    if (!refresh && !nearbyHasMore.value) return
    nearbyLoading.value = true
    const page = refresh ? 1 : nearbyPage.value + 1
    try {
      const result = await itemService.getNearby(page)
      nearbyItems.value = refresh || page === 1 ? result.list : [...nearbyItems.value, ...result.list]
      nearbyPage.value = page
      nearbyHasMore.value = result.hasMore
    } finally {
      nearbyLoading.value = false
    }
  }

  async function fetchZone(
    zone: ZoneKey,
    options: { category?: string; sort?: string; refresh?: boolean } = {},
  ): Promise<void> {
    const category = options.category ?? '全部'
    const sort = options.sort ?? '最新发布'
    const key = feedKey(zone, category, sort)
    const currentPage = zonePages.value[key] ?? 0
    if (!options.refresh && zoneHasMore.value[key] === false) return
    zoneLoading.value = { ...zoneLoading.value, [key]: true }
    const page = options.refresh ? 1 : currentPage + 1
    try {
      const result = await itemService.getZone(zone, { category, sort, page })
      const existing = zoneFeeds.value[key] ?? []
      zoneFeeds.value = {
        ...zoneFeeds.value,
        [key]: options.refresh || page === 1 ? result.list : [...existing, ...result.list],
      }
      zonePages.value = { ...zonePages.value, [key]: page }
      zoneHasMore.value = { ...zoneHasMore.value, [key]: result.hasMore }
      zoneTotals.value = { ...zoneTotals.value, [key]: result.total }
    } finally {
      zoneLoading.value = { ...zoneLoading.value, [key]: false }
    }
  }

  function getZoneItems(zone: ZoneKey, category = '全部', sort = '最新发布'): Item[] {
    return zoneFeeds.value[feedKey(zone, category, sort)] ?? []
  }

  function hasMoreZone(zone: ZoneKey, category = '全部', sort = '最新发布'): boolean {
    return zoneHasMore.value[feedKey(zone, category, sort)] ?? true
  }

  function isLoadingZone(zone: ZoneKey, category = '全部', sort = '最新发布'): boolean {
    return Boolean(zoneLoading.value[feedKey(zone, category, sort)])
  }

  function getZoneTotal(zone: ZoneKey, category = '全部', sort = '最新发布'): number {
    return zoneTotals.value[feedKey(zone, category, sort)] ?? 0
  }

  async function fetchDetail(id: string, force = false): Promise<Item> {
    if (!force && detailCache.value[id]) return detailCache.value[id]
    const item = await itemService.getDetail(id)
    detailCache.value = { ...detailCache.value, [id]: item }
    return item
  }

  async function fetchComments(id: string): Promise<ItemComment[]> {
    const list = await itemService.getComments(id)
    commentsCache.value = { ...commentsCache.value, [id]: list }
    return list
  }

  async function addComment(id: string, content: string): Promise<ItemComment> {
    const comment = await itemService.addComment(id, content)
    commentsCache.value = {
      ...commentsCache.value,
      [id]: [comment, ...(commentsCache.value[id] ?? [])],
    }
    return comment
  }

  async function toggleFavorite(item: Item): Promise<void> {
    const previous = Boolean(item.favorite)
    const next = !previous
    applyFavorite(item.id, next)
    try {
      const result = await itemService.toggleFavorite(item.id)
      applyFavorite(item.id, result.favorite)
      if (result.favorite) {
        const source = detailCache.value[item.id] ?? item
        if (!favorites.value.some((entry) => entry.id === item.id)) {
          favorites.value = [{ ...source, favorite: true }, ...favorites.value]
        }
      } else {
        favorites.value = favorites.value.filter((entry) => entry.id !== item.id)
      }
    } catch (error) {
      applyFavorite(item.id, previous)
      throw error
    }
  }

  async function fetchMyItems(): Promise<void> {
    myItemsLoading.value = true
    try {
      const result = await itemService.getMyItems(1, 50)
      myItems.value = result.list
    } finally {
      myItemsLoading.value = false
    }
  }

  async function offShelf(id: string): Promise<void> {
    await itemService.offShelf(id)
    const item = myItems.value.find((entry) => entry.id === id)
    if (item) item.status = 'OFF_SHELF'
  }

  async function renew(id: string): Promise<void> {
    await itemService.renew(id)
  }

  async function removeItem(id: string): Promise<void> {
    await itemService.remove(id)
    myItems.value = myItems.value.filter((entry) => entry.id !== id)
  }

  async function fetchFavorites(): Promise<void> {
    const bundle = await itemService.getFavorites('item')
    favorites.value = bundle.items
  }

  /**
   * 清空与账号绑定的小区内容缓存。
   * 首页 feed 按用户所属小区隔离，切换账号/退出登录后必须丢弃，
   * 否则新注册用户会先看到上一个账号（可能是其它小区）的缓存内容。
   */
  function resetUserContent(): void {
    homeFeed.value = null
    homeLoadedAt.value = 0
    homeLoading.value = false
    homeError.value = ''
    nearbyItems.value = []
    nearbyPage.value = 1
    nearbyHasMore.value = true
    nearbyLoading.value = false
    zoneFeeds.value = {}
    zonePages.value = {}
    zoneHasMore.value = {}
    zoneLoading.value = {}
    zoneTotals.value = {}
    detailCache.value = {}
    commentsCache.value = {}
    myItems.value = []
    myItemsLoading.value = false
    favorites.value = []
    removeStorage(STORAGE_KEYS.homeFeed)
  }

  return {
    homeFeed,
    homeLoadedAt,
    homeLoading,
    homeError,
    nearbyItems,
    nearbyPage,
    nearbyHasMore,
    nearbyLoading,
    zoneFeeds,
    detailCache,
    commentsCache,
    myItems,
    myItemsLoading,
    favorites,
    hourHotItems,
    fetchHome,
    fetchNearby,
    fetchZone,
    getZoneItems,
    hasMoreZone,
    isLoadingZone,
    getZoneTotal,
    fetchDetail,
    fetchComments,
    addComment,
    toggleFavorite,
    applyFavorite,
    fetchMyItems,
    offShelf,
    renew,
    removeItem,
    fetchFavorites,
    resetUserContent,
  }
})
