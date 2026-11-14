import { describe, expect, it } from 'vitest'
import { maskAddress, maskIdCard, maskName, maskPhone, redactSensitive } from '../../utils/desensitize'

describe('desensitize', () => {
  it('masks phone numbers', () => {
    expect(maskPhone('13800005628')).toBe('138 **** 5628')
    expect(maskPhone('138 0000 5628')).toBe('138 **** 5628')
    expect(maskPhone('123')).toBe('123')
  })

  it('masks names', () => {
    expect(maskName('张三')).toBe('张*')
    expect(maskName('欧阳娜娜')).toBe('欧**')
    expect(maskName('李')).toBe('李')
    expect(maskName('')).toBe('')
  })

  it('masks id card and address', () => {
    expect(maskIdCard('110101199001011234')).toBe('110101********1234')
    expect(maskAddress('阳光花园小区3号楼1202')).toBe('阳光花园小区****')
  })

  it('redacts sensitive keys recursively', () => {
    const result = redactSensitive({
      accessToken: 'token-value',
      phone: '13800005628',
      name: '张三',
      nested: { idCard: '110101199001011234', note: 'ok' },
    }) as Record<string, any>
    expect(result.accessToken).toBe('***')
    expect(result.phone).toBe('***')
    expect(result.name).toBe('张*')
    expect(result.nested.idCard).toBe('***')
    expect(result.nested.note).toBe('ok')
  })
})
