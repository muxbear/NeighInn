import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LifeComment, LifePost } from '../models'
import { lifeService } from '../services/life.service'

export const useLifeStore = defineStore('life', () => {
  const posts = ref<LifePost[]>([])
  const category = ref('全部')
  const page = ref(1)
  const hasMore = ref(true)
  const loading = ref(false)
  const detailCache = ref<Record<string, LifePost>>({})
  const commentsCache = ref<Record<string, LifeComment[]>>({})

  async function fetchPosts(nextCategory = '', refresh = false): Promise<void> {
    if (nextCategory) category.value = nextCategory
    if (loading.value) return
    if (!refresh && !hasMore.value) return
    loading.value = true
    const targetPage = refresh ? 1 : page.value + 1
    try {
      const result = await lifeService.getPosts(category.value, targetPage)
      posts.value = refresh || targetPage === 1 ? result.list : [...posts.value, ...result.list]
      page.value = targetPage
      hasMore.value = result.hasMore
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(id: string): Promise<LifePost> {
    if (detailCache.value[id]) return detailCache.value[id]
    const post = await lifeService.getDetail(id)
    detailCache.value = { ...detailCache.value, [id]: post }
    return post
  }

  async function toggleLike(post: LifePost): Promise<void> {
    const previous = Boolean(post.liked)
    const next = !previous
    applyLike(post.id, next)
    try {
      const result = await lifeService.toggleLike(post.id)
      applyLike(post.id, result.liked)
    } catch (error) {
      applyLike(post.id, previous)
      throw error
    }
  }

  function applyLike(id: string, liked: boolean): void {
    const update = (post: LifePost) => {
      if (post.id !== id) return
      if (post.liked !== liked) post.likes = Math.max(0, post.likes + (liked ? 1 : -1))
      post.liked = liked
    }
    posts.value.forEach(update)
    if (detailCache.value[id]) update(detailCache.value[id])
  }

  async function fetchComments(id: string): Promise<LifeComment[]> {
    const list = await lifeService.getComments(id)
    commentsCache.value = { ...commentsCache.value, [id]: list }
    return list
  }

  async function addComment(id: string, content: string): Promise<LifeComment> {
    const comment = await lifeService.addComment(id, content)
    commentsCache.value = { ...commentsCache.value, [id]: [comment, ...(commentsCache.value[id] ?? [])] }
    const post = detailCache.value[id]
    if (post) post.comments += 1
    return comment
  }

  return {
    posts,
    category,
    page,
    hasMore,
    loading,
    detailCache,
    commentsCache,
    fetchPosts,
    fetchDetail,
    toggleLike,
    fetchComments,
    addComment,
  }
})
