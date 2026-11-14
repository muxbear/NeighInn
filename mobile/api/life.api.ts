import type { LifeComment, LifePost, LifePostQuery, PageResult, PublishLifePayload } from '../models'
import { get, post } from './request'
import { withQuery } from './query'

export function getLifePosts(query: LifePostQuery = {}): Promise<PageResult<LifePost>> {
  return get<PageResult<LifePost>>(withQuery('/life/posts', query))
}

export function getLifePost(id: string): Promise<LifePost> {
  return get<LifePost>(`/life/posts/${id}`)
}

export function publishLife(payload: PublishLifePayload): Promise<LifePost> {
  return post<LifePost>('/life/posts', payload as unknown as Record<string, any>, { loading: true })
}

export function toggleLifeLike(id: string): Promise<{ liked: boolean; likes: number }> {
  return post<{ liked: boolean; likes: number }>(`/life/posts/${id}/like`, {}, { idempotent: false })
}

export function getLifeComments(id: string): Promise<LifeComment[]> {
  return get<LifeComment[]>(`/life/posts/${id}/comments`)
}

export function addLifeComment(id: string, content: string): Promise<LifeComment> {
  return post<LifeComment>(`/life/posts/${id}/comments`, { content })
}
