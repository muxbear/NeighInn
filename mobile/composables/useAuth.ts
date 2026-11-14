import { computed } from 'vue'
import { useUserStore } from '../stores/user.store'
import { supportsOneClickLogin } from '../utils/platform'

export function useAuth() {
  const user = useUserStore()

  const isLoggedIn = computed(() => user.isLoggedIn)
  const isVerifiedOwner = computed(() => user.isVerifiedOwner)
  const profile = computed(() => user.profile)

  function requireLogin(): boolean {
    if (user.isLoggedIn) return true
    uni.navigateTo({ url: '/pages/auth/login' })
    return false
  }

  function requireVerified(): boolean {
    if (!requireLogin()) return false
    if (!user.isVerifiedOwner) {
      uni.navigateTo({ url: '/pages/auth/owner-proof' })
      return false
    }
    return true
  }

  function goLogin(): void {
    uni.navigateTo({ url: '/pages/auth/login' })
  }

  const oneClickAvailable = computed(() => supportsOneClickLogin())

  return {
    user,
    profile,
    isLoggedIn,
    isVerifiedOwner,
    oneClickAvailable,
    requireLogin,
    requireVerified,
    goLogin,
  }
}
