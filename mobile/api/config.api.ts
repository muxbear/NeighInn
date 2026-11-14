import type { AppConfig, CategoryBundle, NotificationSettings, PresignResult } from '../models'
import { get, post } from './request'

export function getAppConfig(): Promise<AppConfig> {
  return get<AppConfig>('/config/app')
}

export function getCategories(): Promise<CategoryBundle> {
  return get<CategoryBundle>('/categories')
}

export function presignUpload(payload: { fileName: string; fileType: string }): Promise<PresignResult> {
  return post<PresignResult>('/uploads/presign', payload)
}

export function trackBatch(events: Array<Record<string, any>>): Promise<{ accepted: number }> {
  return post('/track/batch', { events }, { auth: false, idempotent: false })
}

export type { NotificationSettings }
