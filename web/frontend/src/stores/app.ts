import { defineStore } from 'pinia'
import { communityApi } from '@/api'

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebarOpen: false,
    commandOpen: false,
    toastMessage: '',
    toastTimer: 0 as number | undefined,
    communities: [] as any[],
    currentCommunityId: Number(localStorage.getItem('ni_community_id') || 1),
  }),
  getters: {
    currentCommunity(state) {
      return state.communities.find((item) => Number(item.id) === state.currentCommunityId) ?? state.communities[0]
    },
  },
  actions: {
    showToast(message: string) {
      this.toastMessage = message
      if (this.toastTimer) window.clearTimeout(this.toastTimer)
      this.toastTimer = window.setTimeout(() => {
        this.toastMessage = ''
      }, 2200)
    },
    async loadCommunities() {
      const data = await communityApi.list({ page: 1, pageSize: 50 })
      this.communities = data.items ?? []
      if (!this.communities.some((item: any) => Number(item.id) === this.currentCommunityId)) {
        this.currentCommunityId = Number(this.communities[0]?.id || 1)
      }
    },
    switchCommunity(id: number) {
      this.currentCommunityId = id
      localStorage.setItem('ni_community_id', String(id))
    },
    toggleSidebar(value?: boolean) {
      this.sidebarOpen = value ?? !this.sidebarOpen
    },
  },
})
