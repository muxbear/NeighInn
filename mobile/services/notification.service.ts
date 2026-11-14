import * as notificationApi from '../api/notification.api'
import type {
  AppNotification,
  Broadcast,
  NotificationSettings,
  PageResult,
  UnreadSummary,
} from '../models'

export const notificationService = {
  getList(category = '全部', page = 1, pageSize = 20): Promise<PageResult<AppNotification>> {
    return notificationApi.getNotifications(category, page, pageSize)
  },

  getUnread(): Promise<UnreadSummary> {
    return notificationApi.getUnreadSummary()
  },

  read(id: number): Promise<{ success: boolean; unread: number }> {
    return notificationApi.readNotification(id)
  },

  readAll(): Promise<{ success: boolean }> {
    return notificationApi.readAllNotifications()
  },

  getSettings(): Promise<NotificationSettings> {
    return notificationApi.getNotificationSettings()
  },

  updateSettings(settings: Partial<NotificationSettings>): Promise<NotificationSettings> {
    return notificationApi.updateNotificationSettings(settings)
  },

  getBroadcasts(): Promise<Broadcast[]> {
    return notificationApi.getBroadcasts()
  },

  getBroadcast(id: string): Promise<Broadcast> {
    return notificationApi.getBroadcastDetail(id)
  },

  favoriteBroadcast(id: string): Promise<{ favorited: boolean }> {
    return notificationApi.favoriteBroadcast(id)
  },

  respondBroadcast(id: string): Promise<{ success: boolean; responseCount: number }> {
    return notificationApi.respondBroadcast(id)
  },
}
