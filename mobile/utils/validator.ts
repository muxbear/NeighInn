import type { ItemDraft } from '../models/item.model'

export interface ValidationResult {
  valid: boolean
  errors: Record<string, string>
}

export function isPhone(value: string): boolean {
  return /^1[3-9]\d{9}$/.test(String(value || '').trim())
}

export function isSmsCode(value: string): boolean {
  return /^\d{6}$/.test(String(value || '').trim())
}

export function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || '').trim())
}

export function isNickname(value: string): boolean {
  const text = String(value || '').trim()
  return text.length > 0 && text.length <= 16
}

export function isPrice(value: string | number): boolean {
  const text = String(value ?? '').trim()
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return false
  const num = Number.parseFloat(text)
  return Number.isFinite(num) && num > 0 && num <= 999999
}

export function textLength(value: string): number {
  return Array.from(String(value || '')).length
}

export function clampText(value: string, max: number): string {
  return Array.from(String(value || '')).slice(0, max).join('')
}

export function validateItemDraft(draft: ItemDraft): ValidationResult {
  const errors: Record<string, string> = {}

  if (!draft.images || draft.images.length < 3) {
    errors.images = '请至少上传 3 张实拍照片'
  }
  if (draft.images && draft.images.length > 12) {
    errors.images = '最多上传 12 张照片'
  }
  if (textLength(draft.title?.trim() ?? '') < 2) {
    errors.title = '标题需 2–30 个字'
  } else if (textLength(draft.title) > 30) {
    errors.title = '标题最多 30 字'
  }
  if (draft.tradeType === '出售' && !isPrice(draft.price)) {
    errors.price = '请填写有效价格（0.01–999999）'
  }
  if (draft.tradeType === '互换' && textLength(draft.barterExpect?.trim() ?? '') < 2) {
    errors.barterExpect = '请填写期望交换的物品（至少 2 个字）'
  }
  if (!draft.category) {
    errors.category = '请选择物品分类'
  }
  if (!draft.condition) {
    errors.condition = '请选择物品成色'
  }
  if (textLength(draft.qualityDesc) < 20) {
    errors.qualityDesc = '质量说明至少 20 字'
  }

  return { valid: Object.keys(errors).length === 0, errors }
}

export function validateLifeDraft(payload: {
  title: string
  media: string[]
  category: string
}): ValidationResult {
  const errors: Record<string, string> = {}
  if (!payload.media || payload.media.length === 0) {
    errors.media = '请上传视频或照片'
  }
  if (!payload.title || !payload.title.trim()) {
    errors.title = '请填写标题'
  } else if (textLength(payload.title) > 40) {
    errors.title = '标题最多 40 字'
  }
  if (!payload.category) {
    errors.category = '请选择分类'
  }
  return { valid: Object.keys(errors).length === 0, errors }
}

export function validateProfile(payload: {
  nickname: string
  phone: string
  email: string
  address: string
}): ValidationResult {
  const errors: Record<string, string> = {}
  if (!isNickname(payload.nickname)) errors.nickname = '昵称必填，最多 16 字'
  if (payload.phone && !isPhone(payload.phone)) errors.phone = '请输入正确的手机号'
  if (payload.email && !isEmail(payload.email)) errors.email = '请输入正确的邮箱'
  if (!payload.address || !payload.address.trim()) errors.address = '请填写家庭地址'
  return { valid: Object.keys(errors).length === 0, errors }
}

export function countText(value: string): number {
  return textLength(value)
}
