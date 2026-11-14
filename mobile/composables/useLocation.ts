import { ref } from 'vue'
import type { CommunitySummary } from '../models'

export interface Coords {
  latitude: number
  longitude: number
}

export function useLocation() {
  const locating = ref(false)
  const permissionDenied = ref(false)
  const coords = ref<Coords | null>(null)

  function getLocation(): Promise<Coords | null> {
    locating.value = true
    return new Promise((resolve) => {
      if (typeof uni === 'undefined') {
        locating.value = false
        resolve(null)
        return
      }
      uni.getLocation({
        type: 'gcj02',
        success: (res: any) => {
          coords.value = { latitude: res.latitude, longitude: res.longitude }
          permissionDenied.value = false
          locating.value = false
          resolve(coords.value)
        },
        fail: () => {
          permissionDenied.value = true
          locating.value = false
          resolve(null)
        },
      })
    })
  }

  /** 定位失败时回退到绑定小区坐标，由服务端返回距离 */
  function fallbackCommunity(community: CommunitySummary | null): string {
    return community?.name ?? '当前小区'
  }

  function openPermissionSettings(): void {
    if (typeof uni === 'undefined') return
    uni.openSetting?.({})
  }

  return {
    locating,
    permissionDenied,
    coords,
    getLocation,
    fallbackCommunity,
    openPermissionSettings,
  }
}
