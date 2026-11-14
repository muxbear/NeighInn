import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { CommunityApplyPayload, CommunityBinding } from '../models'
import { communityService } from '../services/community.service'

export const useCommunityStore = defineStore('community', () => {
  const bindings = ref<CommunityBinding[]>([])
  const nearby = ref<CommunityBinding[]>([])
  const currentId = ref('')
  const loading = ref(false)

  const current = computed<CommunityBinding | null>(() => {
    const found = bindings.value.find((item) => item.id === currentId.value)
    if (found) return found
    return bindings.value.find((item) => item.status === '已认证') ?? bindings.value[0] ?? null
  })

  const verifiedBindings = computed(() => bindings.value.filter((item) => item.status === '已认证'))

  async function fetchMine(): Promise<void> {
    loading.value = true
    try {
      bindings.value = await communityService.getMine()
      if (!currentId.value) {
        currentId.value = bindings.value.find((item) => item.status === '已认证')?.id ?? bindings.value[0]?.id ?? ''
      }
    } finally {
      loading.value = false
    }
  }

  async function fetchNearby(): Promise<void> {
    nearby.value = await communityService.getNearby()
  }

  async function search(keyword: string): Promise<CommunityBinding[]> {
    const result = await communityService.search(keyword)
    nearby.value = result
    return result
  }

  async function apply(id: string, payload: CommunityApplyPayload): Promise<void> {
    await communityService.verify(id, payload)
    await fetchMine()
  }

  function setCurrent(id: string): void {
    currentId.value = id
  }

  return {
    bindings,
    nearby,
    currentId,
    loading,
    current,
    verifiedBindings,
    fetchMine,
    fetchNearby,
    search,
    apply,
    setCurrent,
  }
})
