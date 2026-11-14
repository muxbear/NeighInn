import type {
  AppNotification,
  Broadcast,
  NotificationSettings,
  PageResult,
  UnreadSummary,
} from '../models'
import { get, post, put } from './request'
import { withQuery } from './query'

export function getNotifications(category = '全部', page = 1, pageSize = 20): Promise<PageResult<AppNotification>> {
  return get<PageResult<AppNotification>>(withQuery('/notifications', { category, page, pageSize }))
}

export function getUnreadSummary(): Promise<UnreadSummary> {
  return get<UnreadSummary>('/notifications/unread')
}

export function readNotification(id: number): Promise<{ success: boolean; unread: number }> {
  return post(`/notifications/${id}/read`, {}, { idempotent: false })
}

export function readAllNotifications(): Promise<{ success: boolean }> {
  return post('/notifications/read-all', {}, { idempotent: false })
}

export function getNotificationSettings(): Promise<NotificationSettings> {
  return get<NotificationSettings>('/notifications/settings')
}

export function updateNotificationSettings(settings: Partial<NotificationSettings>): Promise<NotificationSettings> {
  return put<NotificationSettings>('/notifications/settings', settings)
}

export function getBroadcasts(): Promise<Broadcast[]> {
  return get<Broadcast[]>('/broadcasts')
}

export function getBroadcastDetail(id: string): Promise<Broadcast> {
  return get<Broadcast>(`/broadcasts/${id}`)
}

export function favoriteBroadcast(id: string): Promise<{ favorited: boolean }> {
  return post<{ favorited: boolean }>(`/broadcasts/${id}/favorite`, {}, { idempotent: false })
}

export function respondBroadcast(id: string): Promise<{ success: boolean; responseCount: number }> {
  return post(`/broadcasts/${id}/respond`, {})
}
