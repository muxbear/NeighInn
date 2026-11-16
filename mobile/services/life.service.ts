import * as lifeApi from '../api/life.api'
import { ApiError } from '../api/errors'
import type { LifeComment, LifePost, PageResult, PublishLifePayload } from '../models'
import { validateLifeDraft } from '../utils/validator'

export const lifeService = {
  getPosts(category = '全部', page = 1, pageSize = 20): Promise<PageResult<LifePost>> {
    return lifeApi.getLifePosts({ category, page, pageSize })
  },

  /** 我的生活动态（含待审核/已驳回等状态），用于「我的」页查看审核进度。 */
  getMinePosts(page = 1, pageSize = 20): Promise<PageResult<LifePost>> {
    return lifeApi.getMyLifePosts(page, pageSize)
  },

  getDetail(id: string): Promise<LifePost> {
    return lifeApi.getLifePost(id)
  },

  async publish(payload: PublishLifePayload): Promise<LifePost> {
    const validation = validateLifeDraft({
      title: payload.title,
      media: payload.media,
      category: payload.category,
    })
    if (!validation.valid) {
      const first = Object.values(validation.errors)[0]
      throw new ApiError(40001, first)
    }
    return lifeApi.publishLife(payload)
  },

  toggleLike(id: string): Promise<{ liked: boolean; likes: number }> {
    return lifeApi.toggleLifeLike(id)
  },

  getComments(id: string): Promise<LifeComment[]> {
    return lifeApi.getLifeComments(id)
  },

  addComment(id: string, content: string): Promise<LifeComment> {
    if (!content.trim()) throw new ApiError(40001, '评论内容不能为空')
    return lifeApi.addLifeComment(id, content.trim())
  },
}
