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
    // 仅按 ID 精确匹配。列表缺失时返回 null，避免静默回退到无关社区（如列表首项）。
    currentCommunity(state) {
      return state.communities.find((item) => Number(item.id) === state.currentCommunityId) ?? null
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
    /** 登记或更新单个社区：筛选栏选中、社区运维变更后保持共享列表最新。 */
    upsertCommunity(row: any) {
      if (!row || row.id === undefined || row.id === null) return
      const id = Number(row.id)
      if (!Number.isFinite(id)) return
      const index = this.communities.findIndex((item) => Number(item.id) === id)
      if (index >= 0) this.communities.splice(index, 1, { ...this.communities[index], ...row })
      else this.communities.push(row)
    },
    async loadCommunities() {
      const data = await communityApi.list({ page: 1, pageSize: 50 })
      // 待审批/已驳回的小区不是运营空间，不能出现在顶部社区切换里。
      this.communities = (data.items ?? []).filter(
        (item: any) => !['PENDING', 'REJECTED'].includes(String(item.statusCode || item.status || '')),
      )
      if (!this.communities.some((item: any) => Number(item.id) === this.currentCommunityId)) {
        // 当前社区可能不在前 50 条内（刚创建或分页之外）：按 ID 补取详情后再决定是否回退。
        try {
          const detail = await communityApi.detail(this.currentCommunityId)
          if (detail?.id !== undefined) {
            this.upsertCommunity(detail)
            return
          }
        } catch {
          // 社区不存在或超出数据范围时退回列表首项
        }
        this.currentCommunityId = Number(this.communities[0]?.id || 1)
        localStorage.setItem('ni_community_id', String(this.currentCommunityId))
      }
    },
    /**
     * 切换当前运营社区。
     * @param row 选中社区的完整行；传入时同步登记到 communities，
     *            避免「筛选栏能搜到、共享列表却没有」导致名称回退到其他社区。
     */
    switchCommunity(id: number, row?: any) {
      if (row) this.upsertCommunity(row)
      this.currentCommunityId = id
      localStorage.setItem('ni_community_id', String(id))
      // 列表未包含该社区时异步补取详情（例如分页之外或刚创建的社区）。
      if (!this.communities.some((item) => Number(item.id) === id)) {
        communityApi.detail(id)
          .then((detail) => {
            if (detail?.id !== undefined) this.upsertCommunity(detail)
          })
          .catch(() => undefined)
      }
    },
    toggleSidebar(value?: boolean) {
      this.sidebarOpen = value ?? !this.sidebarOpen
    },
  },
})
