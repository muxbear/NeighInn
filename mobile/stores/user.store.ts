import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  LoginResult,
  LoginSmsOptions,
  OnboardingStatus,
  RegisterCompletePayload,
  UserProfile,
} from '../models'
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
  const isRealnameVerified = computed(
    () => profile.value?.realnameVerified === true
      || profile.value?.authStatus === 'VERIFIED_UNOWNER'
      || profile.value?.authStatus === 'VERIFIED_OWNER',
  )
  const isVerifiedOwner = computed(
    () => profile.value?.ownerVerified === true
      || profile.value?.authStatus === 'VERIFIED_OWNER',
  )
  const realnameStatus = computed(() => profile.value?.realnameStatus ?? 'UNVERIFIED')
  const ownerStatus = computed(() => profile.value?.ownerStatus ?? 'UNVERIFIED')
  const avatarSrc = computed(() => {
    if (!profile.value) return ''
    if (profile.value.avatarDataUrl) return profile.value.avatarDataUrl
    return profile.value.avatarPreset ? `/static/avatars/${profile.value.avatarPreset}.svg` : ''
  })
  const displayPhone = computed(() => maskPhone(profile.value?.phone ?? ''))
  const authStatus = computed(() => profile.value?.authStatus ?? 'NOT_LOGIN')
  // 旧版本本地缓存没有 onboardingStatus，按已完成处理，避免存量用户被引导。
  const onboardingStatus = computed<OnboardingStatus>(
    () => profile.value?.onboardingStatus ?? 'COMPLETED',
  )
  const needsOnboarding = computed(
    () => onboardingStatus.value === 'NEW' || onboardingStatus.value === 'PROFILE_COMPLETED',
  )

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
    const nextProfile: UserProfile = {
      ...result.profile,
      onboardingStatus:
        result.profile.onboardingStatus ??
        result.onboardingStatus ??
        (result.isNewUser ? 'NEW' : 'COMPLETED'),
    }
    profile.value = nextProfile
    setStorage(STORAGE_KEYS.userProfile, nextProfile)
    logger.setUserId(nextProfile.id)
    wsService.connect()
  }

  async function loginWithSms(
    phone: string,
    code: string,
    options: LoginSmsOptions = {},
  ): Promise<LoginResult> {
    loading.value = true
    try {
      const result = await authService.loginBySms(phone, code, options)
      applyLogin(result)
      return result
    } finally {
      loading.value = false
    }
  }

  async function completeRegistration(payload: RegisterCompletePayload): Promise<void> {
    const updated = await authService.completeRegistration(payload)
    profile.value = updated
    setStorage(STORAGE_KEYS.userProfile, updated)
  }

  async function loginWithOneClick(carrierToken: string): Promise<LoginResult> {
    loading.value = true
    try {
      const result = await authService.loginByOneClick(carrierToken)
      applyLogin(result)
      return result
    } finally {
      loading.value = false
    }
  }

  async function loginWithWechat(code: string): Promise<LoginResult> {
    loading.value = true
    try {
      const result = await authService.loginByWechat(code)
      applyLogin(result)
      return result
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
    isRealnameVerified,
    isVerifiedOwner,
    realnameStatus,
    ownerStatus,
    avatarSrc,
    displayPhone,
    authStatus,
    onboardingStatus,
    needsOnboarding,
    hydrate,
    applyLogin,
    loginWithSms,
    loginWithOneClick,
    loginWithWechat,
    completeRegistration,
    refreshProfile,
    updateProfile,
    updateAvatar,
    updateCommunity,
    logout,
  }
})
