import { describe, expect, it } from 'vitest'
import { normalizePageResult } from '../../api/pagination'
import type { PageResult } from '../../models'

interface Row {
  id: number
}

describe('normalizePageResult', () => {
  it('maps backend items to the mobile list field', () => {
    const result = normalizePageResult<PageResult<Row> & { items: Row[] }>({
      items: [{ id: 1 }],
      page: 1,
      pageSize: 20,
      total: 1,
      hasMore: false,
    })

    expect(result.list).toEqual([{ id: 1 }])
    expect(result.items).toEqual([{ id: 1 }])
    expect(result.hasMore).toBe(false)
  })

  it('keeps an existing list field untouched', () => {
    const result = normalizePageResult<PageResult<Row>>({
      list: [{ id: 2 }],
      items: [{ id: 2 }],
      page: 1,
      pageSize: 20,
      total: 1,
      hasMore: false,
    } as PageResult<Row>)

    expect(result.list).toEqual([{ id: 2 }])
  })

  it('leaves non-paginated bundles untouched', () => {
    const bundle = { items: ['gift', 'swap'] }
    const result = normalizePageResult<typeof bundle>(bundle)

    expect(result).toBe(bundle)
    expect('list' in result).toBe(false)
  })
})
