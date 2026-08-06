import { describe, expect, it } from 'vitest'
import { buildSearchParams } from './search'

describe('buildSearchParams', () => {
  it('always sends q/limit/offset and omits empty/default filters', () => {
    expect(buildSearchParams({ q: 'hi', page: 1 })).toEqual({ q: 'hi', limit: 20, offset: 0 })
  })

  it('forwards the set filters and computes offset', () => {
    expect(
      buildSearchParams({
        q: 'hi',
        page: 2,
        pageSize: 10,
        targetProfile: 'p',
        fields: 'prompt',
        status: ['failed', 'done'],
        createdAfter: '2026-08-01T00:00:00Z',
        createdBefore: '2026-08-06T00:00:00Z',
      }),
    ).toEqual({
      q: 'hi',
      limit: 10,
      offset: 10,
      target_profile: 'p',
      fields: 'prompt',
      status: ['failed', 'done'],
      created_after: '2026-08-01T00:00:00Z',
      created_before: '2026-08-06T00:00:00Z',
    })
  })

  it('omits fields when "all" and status when empty', () => {
    expect(buildSearchParams({ q: 'hi', page: 1, fields: 'all', status: [] })).toEqual({
      q: 'hi',
      limit: 20,
      offset: 0,
    })
  })
})
