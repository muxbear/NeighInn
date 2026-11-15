import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { AppConfig, AppSettings } from '../models'
import { AGREEMENT_VERSION, PRIVACY_VERSION, STORAGE_KEYS } from '../config/constants'
import { getAppConfig } from '../api/config.api'
import { getStorage, setStorage } from '../utils/storage'
import { logger } from '../utils/logger'

const DEFAULT_SETTINGS: AppSettings = {
  pushEnabled: true,
  tradeNotifyEnabled: true,
  communityNotifyEnabled: true,
  elderMode: false,
  theme: 'light',
  showBio: true,
  shareAddressAfterOrder: true,
}

const DEFAULT_CONFIG: AppConfig = {
  nearbyRadiusKm: 3,
  maxCommunities: 3,
  maxItemImages: 12,
  minItemImages: 3,
  maxLifeImages: 12,
  maxVideoSeconds: 180,
  payTimeoutMinutes: 30,
  appointmentAutoCancelHours: 48,
  supportPhone: '400-800-2026',
  userAgreementVersion: AGREEMENT_VERSION,
  privacyPolicyVersion: PRIVACY_VERSION,
}

export const useAppStore = defineStore('app', () => {
  const settings = ref<AppSettings>({ ...DEFAULT_SETTINGS, ...getStorage(STORAGE_KEYS.settings, DEFAULT_SETTINGS) })
  const config = ref<AppConfig>({ ...DEFAULT_CONFIG })
  const statusBarHeight = ref(0)
  const safeAreaBottom = ref(0)
  const network = ref<'online' | 'offline' | 'unknown'>('unknown')
  const bootstrapped = ref(false)

  const elderMode = computed(() => settings.value.elderMode)
  const fontScale = computed(() => (settings.value.elderMode ? 2 : 0))

  function measureWindow(): void {
    if (typeof uni === 'undefined') return
    try {
      const info = typeof uni.getWindowInfo === 'function' ? uni.getWindowInfo() : uni.getSystemInfoSync()
      statusBarHeight.value = Number(info?.statusBarHeight ?? 0)
      const insets = info?.safeAreaInsets
      if (insets && typeof insets.bottom === 'number') {
        safeAreaBottom.value = insets.bottom
      } else if (informSafeArea(info)) {
        safeAreaBottom.value = Math.max(0, Number(info.screenHeight ?? 0) - Number(info.safeArea.bottom ?? 0))
      }
    } catch (error) {
      logger.warn('App', 'measure window failed', error)
    }
  }

  function informSafeArea(info: any): boolean {
    return Boolean(info && info.safeArea && typeof info.safeArea.bottom === 'number')
  }

  function watchNetwork(): void {
    if (typeof uni === 'undefined') return
    try {
      uni.getNetworkType({
        success: (res: any) => {
          network.value = res.networkType === 'none' ? 'offline' : 'online'
        },
      })
      uni.onNetworkStatusChange((res: any) => {
        network.value = res.isConnected ? 'online' : 'offline'
      })
    } catch {
      network.value = 'online'
    }
  }

  async function loadConfig(): Promise<void> {
    try {
      config.value = await getAppConfig()
    } catch (error) {
      logger.warn('App', 'load config failed, use defaults', error)
    }
  }

  async function bootstrap(): Promise<void> {
    measureWindow()
    watchNetwork()
    await loadConfig()
    bootstrapped.value = true
  }

  function persistSettings(): void {
    setStorage(STORAGE_KEYS.settings, settings.value)
  }

  function updateSetting<K extends keyof AppSettings>(key: K, value: AppSettings[K]): void {
    settings.value = { ...settings.value, [key]: value }
    persistSettings()
  }

  function toggleElderMode(): void {
    updateSetting('elderMode', !settings.value.elderMode)
  }

  function setTheme(theme: AppSettings['theme']): void {
    updateSetting('theme', theme)
  }

  return {
    settings,
    config,
    statusBarHeight,
    safeAreaBottom,
    network,
    bootstrapped,
    elderMode,
    fontScale,
    bootstrap,
    measureWindow,
    updateSetting,
    toggleElderMode,
    setTheme,
    loadConfig,
  }
})
