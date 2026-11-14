import * as serviceApi from '../api/service.api'
import type { PageResult, ServiceKind, ServicePost } from '../models'

export const serviceService = {
  getList(
    kind: ServiceKind | '' = '',
    category = '全部',
    page = 1,
    pageSize = 20,
  ): Promise<PageResult<ServicePost>> {
    return serviceApi.getServices({
      kind: kind || undefined,
      category,
      page,
      pageSize,
    })
  },

  respond(id: number | string): Promise<{ success: boolean; responses: number }> {
    return serviceApi.respondService(id)
  },

  publish(payload: Partial<ServicePost>): Promise<ServicePost> {
    return serviceApi.createService(payload)
  },
}
