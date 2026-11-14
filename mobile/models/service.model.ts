export type ServiceKind = '求助' | '提供'

export interface ServicePost {
  id: number | string
  kind: ServiceKind
  icon: string
  category: string
  title: string
  description: string
  time: string
  place: string
  distance: string
  reward: string
  author: string
  avatar: string
  avatarClass: string
  responses: number
  price?: string
  credit?: string
  serviceCount?: number
  rating?: string
}

export interface ServiceQuery {
  kind?: ServiceKind
  category?: string
  page?: number
  pageSize?: number
}
