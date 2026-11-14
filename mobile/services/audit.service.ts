import { getAuditProgress } from '../api/item.api'
import type { AuditProgress } from '../models'

export const auditService = {
  getProgress(itemId: string): Promise<AuditProgress> {
    return getAuditProgress(itemId)
  },
}
