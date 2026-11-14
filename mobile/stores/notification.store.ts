import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  AppNotification,
  Broadcast,
  NotificationSettings,
} from '../models'
import { notificationService } from '../services/notification.service'

export const useNotificationStore = defineStore('notification', () => {
  const list = ref<AppNotification[]>([])
  const unread = ref(0)
  const category = ref('全部')
  const loading = ref(false)
  const settings = ref<NotificationSettings>({
    pushEnabled: true,
    tradeEnabled: true,
    communityEnabled: true,
    interactionEnabled: true,
  })
  const broadcasts = ref<Broadcast[]>([])
  const detailCache = ref<Record<string, Broadcast>>({})

  const unreadList = computed(() => list.value.filter((item) => !item.read))

  async function fetchNotifications(nextCategory = '', refresh = false): Promise<void> {
    if (nextCategory) category.value = nextCategory
    loading.value = true
    try {
      const result = await notificationService.getList(category.value, 1, 50)
      list.value = result.list
      if (refresh) {
        unread.value = result.list.filter((item) => !item.read).length
      }
    } finally {
      loading.value = false
    }
  }

  async function fetchUnread(): Promise<void> {
    const summary = await notificationService.getUnread()
    unread.value = summary.count
  }

  async function markRead(id: number): Promise<void> {
    const target = list.value.find((item) => item.id === id)
    if (target && !target.read) {
      target.read = true
      unread.value = Math.max(0, unread.value - 1)
    }
    await notificationService.read(id)
  }

  async function readAll(): Promise<void> {
    await notificationService.readAll()
    list.value.forEach((item) => {
      item.read = true
    })
    unread.value = 0
  }

  async function fetchSettings(): Promise<void> {
    settings.value = await notificationService.getSettings()
  }

  async function updateSettings(payload: Partial<NotificationSettings>): Promise<void> {
    settings.value = await notificationService.updateSettings(payload)
  }

  async function fetchBroadcasts(): Promise<void> {
    broadcasts.value = await notificationService.getBroadcasts()
  }

  async function fetchBroadcastDetail(id: string): Promise<Broadcast> {
    if (detailCache.value[id]) return detailCache.value[id]
    const detail = await notificationService.getBroadcast(id)
    detailCache.value = { ...detailCache.value, [id]: detail }
    return detail
  }

  async function toggleBroadcastFavorite(id: string): Promise<void> {
    const detail = detailCache.value[id] ?? broadcasts.value.find((item) => item.id === id)
    const previous = Boolean(detail?.favorited)
    if (detail) detail.favorited = !previous
    try {
      const result = await notificationService.favoriteBroadcast(id)
      if (detail) detail.favorited = result.favorited
    } catch (error) {
      if (detail) detail.favorited = previous
      throw error
    }
  }

  return {
    list,
    unread,
    category,
    loading,
    settings,
    broadcasts,
    detailCache,
    unreadList,
    fetchNotifications,
    fetchUnread,
    markRead,
    readAll,
    fetchSettings,
    updateSettings,
    fetchBroadcasts,
    fetchBroadcastDetail,
    toggleBroadcastFavorite,
  }
})
