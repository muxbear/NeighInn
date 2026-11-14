export type AuditStatus = 'PROCESSING' | 'PASSED' | 'REJECTED' | 'TIMEOUT'
export type AuditStepStatus = 'PENDING' | 'PROCESSING' | 'DONE' | 'FAILED'

export interface AuditStep {
  key: string
  title: string
  status: AuditStepStatus
  message?: string
}

export interface AuditDimension {
  name: string
  score: number
  desc: string
}

export interface AuditReport {
  passed: boolean
  score: number
  dimensions: AuditDimension[]
  risks: string[]
  suggestions: string[]
  traceId: string
  checkedAt: number
}

export interface AuditProgress {
  itemId: string
  status: AuditStatus
  progress: number
  currentText: string
  steps: AuditStep[]
  report?: AuditReport
  rejectReasons?: string[]
}
