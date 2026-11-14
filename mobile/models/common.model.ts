export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  traceId: string
}

export interface PageQuery {
  page?: number
  pageSize?: number
}

export interface PageResult<T> {
  list: T[]
  page: number
  pageSize: number
  total: number
  hasMore: boolean
}

export interface IdLabel {
  id: string
  label: string
}

export interface SelectOption<T = string> {
  value: T
  label: string
  desc?: string
}
