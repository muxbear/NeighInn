export type LifeCategory = '小区风景' | '邻里日常' | '个人风采' | '萌宠生活'
export type LifeMediaType = 'video' | 'gallery'

export interface LifePost {
  id: string
  type: LifeMediaType
  category: LifeCategory
  title: string
  description: string
  images: string[]
  mediaKeys?: string[]
  cover: string
  duration?: string
  author: string
  avatar: string
  avatarClass: string
  area: string
  time: string
  /** 审核状态：PENDING_REVIEW / PUBLISHED / REJECTED / OFFLINE / DRAFT */
  status?: string
  statusLabel?: string
  views: number
  likes: number
  comments: number
  liked?: boolean
  following?: boolean
  createdAt?: number
  publishedAt?: number
}

export interface LifeComment {
  id: string
  author: string
  avatar: string
  content: string
  time: string
  verified?: boolean
}

export interface LifePostQuery {
  category?: string
  page?: number
  pageSize?: number
}

export interface PublishLifePayload {
  mediaType: LifeMediaType
  media: string[]
  title: string
  description: string
  category: LifeCategory
}
