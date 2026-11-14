import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ServiceKind, ServicePost } from '../models'
import { serviceService } from '../services/service.service'

export const useServiceStore = defineStore('service', () => {
  const helpList = ref<ServicePost[]>([])
  const offerList = ref<ServicePost[]>([])
  const loading = ref(false)
  const category = ref('全部')

  async function fetchList(kind: ServiceKind, nextCategory = '全部'): Promise<void> {
    category.value = nextCategory
    loading.value = true
    try {
      const result = await serviceService.getList(kind, nextCategory)
      if (kind === '求助') helpList.value = result.list
      else offerList.value = result.list
    } finally {
      loading.value = false
    }
  }

  function getByKind(kind: ServiceKind): ServicePost[] {
    return kind === '求助' ? helpList.value : offerList.value
  }

  async function respond(id: number | string): Promise<void> {
    const result = await serviceService.respond(id)
    const update = (post: ServicePost) => {
      if (String(post.id) === String(id)) post.responses = result.responses
    }
    helpList.value.forEach(update)
    offerList.value.forEach(update)
  }

  return {
    helpList,
    offerList,
    loading,
    category,
    fetchList,
    getByKind,
    respond,
  }
})
