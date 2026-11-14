import { describe, expect, it } from 'vitest'
import { createIdempotencyKey, IdempotencyScope, uuidv4 } from '../../utils/idempotency'

describe('idempotency', () => {
  it('generates a UUID-like value', () => {
    const value = uuidv4()
    expect(value).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
  })

  it('generates unique keys', () => {
    const first = createIdempotencyKey('test')
    const second = createIdempotencyKey('test')
    expect(first).not.toBe(second)
    expect(first.startsWith('test-')).toBe(true)
  })

  it('keeps the same key within a scope until reset', () => {
    const scope = new IdempotencyScope('pay')
    const value = scope.value
    expect(scope.value).toBe(value)
    const next = scope.reset('pay')
    expect(next).not.toBe(value)
  })
})
