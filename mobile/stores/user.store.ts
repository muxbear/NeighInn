import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { LoginResult, UserProfile } from '../models'
import { STORAGE_KEYS } from '../config/constants'
import { authService } from '../services/auth.service'
import { profileService } from '../services/profile.service'
import { wsService } from '../services/ws.service'
import { env } from '../config/env'
import { getStorage, removeStorage, secureStorage, setStorage } from '../utils/storage'
import { logger } from '../utils/logger'
import { maskPhone } from '../utils/desensitize'

export const useUserStore = defineStore('user', () => {
  const accessToken = ref(secureStorage.getAccessToken())
  const refreshToken = ref(secureStorage.getRefreshToken())
  const profile = ref<UserProfile | null>(getStorage<UserProfile | null>(STORAGE_KEYS.userProfile, null))
  const loading = ref(false)
  const hydrated = ref(false)

  const isLoggedIn = computed(() => Boolean(accessToken.value))
  const isVerifiedOwner = computed(() => profile.value?.authStatus === 'VERIFIED_OWNER')
  const avatarSrc = computed(() => {
    if (!profile.value) return ''
    if (profile.value.avatarDataUrl) return profile.value.avatarDataUrl
    return profile.value.avatarPreset ? `/static/avatars/${profile.value.avatarPreset}.svg` : ''
  })
  const displayPhone = computed(() => maskPhone(profile.value?.phone ?? ''))
  const authStatus = computed(() => profile.value?.authStatus ?? 'NOT_LOGIN')

  function hydrate(): void {
    if (hydrated.value) return
    hydrated.value = true
    // 兼容旧版本自动注入的演示会话：升级后先回到登录页，与 Figma 的登录首屏一致。
    if (env.mock && accessToken.value === 'mock-demo-access-token') {
      accessToken.value = ''
      refreshToken.value = ''
      secureStorage.clear()
    }
  }

  function applyLogin(result: LoginResult): void {
    accessToken.value = result.accessToken
    refreshToken.value = result.refreshToken
    secureStorage.setTokens(result.accessToken, result.refreshToken)
    profile.value = result.profile
    setStorage(STORAGE_KEYS.userProfile, result.profile)
    logger.setUserId(result.profile.id)
    wsService.connect()
  }

  async function loginWithSms(phone: string, code: string): Promise<void> {
    loading.value = true
    try {
      const result = await authService.loginBySms(phone, code)
      applyLogin(result)
    } finally {
      loading.value = false
    }
  }

  async function loginWithOneClick(carrierToken: string): Promise<void> {
    loading.value = true
    try {
      const result = await authService.loginByOneClick(carrierToken)
      applyLogin(result)
    } finally {
      loading.value = false
    }
  }

  async function loginWithWechat(code: string): Promise<void> {
    loading.value = true
    try {
      const result = await authService.loginByWechat(code)
      applyLogin(result)
    } finally {
      loading.value = false
    }
  }

  async function refreshProfile(): Promise<void> {
    if (!isLoggedIn.value) return
    try {
      profile.value = await profileService.getProfile()
      setStorage(STORAGE_KEYS.userProfile, profile.value)
    } catch (error) {
      logger.warn('User', 'refresh profile failed', error)
    }
  }

  async function updateProfile(payload: Partial<UserProfile>): Promise<void> {
    const updated = await profileService.updateProfile(payload)
    profile.value = updated
    setStorage(STORAGE_KEYS.userProfile, updated)
  }

  async function updateAvatar(payload: { avatarPreset?: string; avatarDataUrl?: string }): Promise<void> {
    const updated = await profileService.updateAvatar(payload)
    profile.value = updated
    setStorage(STORAGE_KEYS.userProfile, updated)
  }

  function updateCommunity(name: string): void {
    if (!profile.value) return
    profile.value = { ...profile.value, communityName: name }
    setStorage(STORAGE_KEYS.userProfile, profile.value)
  }

  async function logout(): Promise<void> {
    try {
      await authService.logout()
    } catch (error) {
      logger.warn('User', 'logout api failed', error)
    }
    accessToken.value = ''
    refreshToken.value = ''
    profile.value = null
    secureStorage.clear()
    removeStorage(STORAGE_KEYS.userProfile)
    wsService.disconnect()
    if (typeof uni !== 'undefined') {
      uni.reLaunch({ url: '/pages/auth/login' })
    }
  }

  return {
    accessToken,
    refreshToken,
    profile,
    loading,
    isLoggedIn,
    isVerifiedOwner,
    avatarSrc,
    displayPhone,
    authStatus,
    hydrate,
    applyLogin,
    loginWithSms,
    loginWithOneClick,
    loginWithWechat,
    refreshProfile,
    updateProfile,
    updateAvatar,
    updateCommunity,
    logout,
  }
})
