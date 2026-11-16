import { describe, expect, it } from 'vitest'
import {
  clampText,
  isEmail,
  isNickname,
  isPhone,
  isPrice,
  isSmsCode,
  textLength,
  validateItemDraft,
  validateLifeDraft,
  validateProfile,
} from '../../utils/validator'
import type { ItemDraft } from '../../models'

const validDraft: ItemDraft = {
  images: ['a.jpg', 'b.jpg', 'c.jpg'],
  title: '原木儿童成长椅',
  tradeType: '出售',
  price: '268',
  barterExpect: '',
  condition: '轻微使用痕迹',
  category: '家具家电',
  qualityDesc: '家中自用，保养良好，没有磕碰，功能一切正常。',
}

describe('validator', () => {
  it('validates phone numbers', () => {
    expect(isPhone('13800005628')).toBe(true)
    expect(isPhone('12800005628')).toBe(false)
    expect(isPhone('1380000562')).toBe(false)
  })

  it('validates sms code and email', () => {
    expect(isSmsCode('123456')).toBe(true)
    expect(isSmsCode('12345')).toBe(false)
    expect(isEmail('neighbor@example.com')).toBe(true)
    expect(isEmail('bad@')).toBe(false)
  })

  it('validates nickname', () => {
    expect(isNickname('温暖的邻居')).toBe(true)
    expect(isNickname('')).toBe(false)
    expect(isNickname('一二三四五六七八九十一二三四五六七')).toBe(false)
  })

  it('validates price', () => {
    expect(isPrice('0.01')).toBe(true)
    expect(isPrice('268')).toBe(true)
    expect(isPrice('0')).toBe(false)
    expect(isPrice('12.345')).toBe(false)
    expect(isPrice('abc')).toBe(false)
  })

  it('validates a complete item draft', () => {
    expect(validateItemDraft(validDraft).valid).toBe(true)
  })

  it('requires at least 3 images and 20-char quality description', () => {
    const result = validateItemDraft({
      ...validDraft,
      images: ['a.jpg'],
      qualityDesc: '太短',
      price: '',
    })
    expect(result.valid).toBe(false)
    expect(result.errors.images).toBeTruthy()
    expect(result.errors.price).toBeTruthy()
    expect(result.errors.qualityDesc).toBeTruthy()
  })

  it('requires barter expectation for swap', () => {
    const result = validateItemDraft({
      ...validDraft,
      tradeType: '互换',
      barterExpect: '',
      price: '',
    })
    expect(result.valid).toBe(false)
    expect(result.errors.barterExpect).toBeTruthy()
  })

  it('validates life draft', () => {
    expect(validateLifeDraft({ title: '傍晚的小区花园', media: ['a.jpg'], category: '小区风景' }).valid).toBe(true)
    expect(validateLifeDraft({ title: '', media: [], category: '' }).valid).toBe(false)
  })

  it('validates profile', () => {
    expect(
      validateProfile({
        nickname: '温暖的邻居',
        phone: '13800005628',
        email: 'neighbor@example.com',
        address: '阳光花园 3 号楼',
      }).valid,
    ).toBe(true)
    expect(validateProfile({ nickname: '', phone: '1', email: 'bad', address: '' }).valid).toBe(false)
  })

  it('counts and clamps Chinese text by code point', () => {
    expect(textLength('邻居好')).toBe(3)
    expect(clampText('一二三四五', 3)).toBe('一二三')
  })
})
