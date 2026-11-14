import { defineStore } from 'pinia'
import { authApi } from '@/api'

type Admin = {
  id: string
  username: string
  realName: string
  avatarText: string
  isSuperAdmin: boolean
  roles: { code: string; name: string }[]
  permissions: string[]
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    admin: null as Admin | null,
    loaded: false,
    loading: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.admin),
    isSuperAdmin: (state) => Boolean(state.admin?.isSuperAdmin),
    permissions: (state) => state.admin?.permissions ?? [],
  },
  actions: {
    hasPermission(code: string) {
      return this.isSuperAdmin || this.permissions.includes(code)
    },
    async login(username: string, password: string) {
      this.loading = true
      try {
        const data = await authApi.login({ username, password })
        this.admin = data.admin
        this.loaded = true
        return data
      } finally {
        this.loading = false
      }
    },
    async fetchMe() {
      if (this.loading) return
      this.loading = true
      try {
        const data = await authApi.me()
        this.admin = data.admin
        this.loaded = true
      } catch {
        this.admin = null
        this.loaded = true
        throw new Error('unauthorized')
      } finally {
        this.loading = false
      }
    },
    async logout() {
      try {
        await authApi.logout()
      } finally {
        this.admin = null
      }
    },
  },
})
