import { STORAGE_KEYS } from '../config/constants'
import { logger } from './logger'

function hasUni(): boolean {
  return typeof uni !== 'undefined'
}

export function getStorage<T>(key: string, fallback: T): T {
  if (!hasUni()) return fallback
  try {
    const value = uni.getStorageSync(key)
    if (value === '' || value === undefined || value === null) return fallback
    return value as T
  } catch (error) {
    logger.warn('Storage', `read failed: ${key}`, error)
    return fallback
  }
}

export function setStorage<T>(key: string, value: T): void {
  if (!hasUni()) return
  try {
    uni.setStorageSync(key, value)
  } catch (error) {
    logger.warn('Storage', `write failed: ${key}`, error)
  }
}

export function removeStorage(key: string): void {
  if (!hasUni()) return
  try {
    uni.removeStorageSync(key)
  } catch (error) {
    logger.warn('Storage', `remove failed: ${key}`, error)
  }
}

export function getStorageRaw(key: string): unknown {
  if (!hasUni()) return undefined
  try {
    return uni.getStorageSync(key)
  } catch {
    return undefined
  }
}

/**
 * Token 存储入口。
 * 正式 App 需替换为 UTS 加密存储（Keystore / Keychain / HUKS）；
 * 当前实现只做统一入口，避免页面直接操作 Storage。
 */
export const secureStorage = {
  getAccessToken(): string {
    return getStorage<string>(STORAGE_KEYS.accessToken, '')
  },
  getRefreshToken(): string {
    return getStorage<string>(STORAGE_KEYS.refreshToken, '')
  },
  setTokens(accessToken: string, refreshToken: string): void {
    setStorage(STORAGE_KEYS.accessToken, accessToken)
    setStorage(STORAGE_KEYS.refreshToken, refreshToken)
  },
  clear(): void {
    removeStorage(STORAGE_KEYS.accessToken)
    removeStorage(STORAGE_KEYS.refreshToken)
    removeStorage(STORAGE_KEYS.userProfile)
  },
}

export function clearSessionStorage(): void {
  secureStorage.clear()
  removeStorage(STORAGE_KEYS.mockSession)
}
