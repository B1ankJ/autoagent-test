import { describe, expect, it } from 'vitest'
import { buildAnomalyParams } from './anomalies'

describe('buildAnomalyParams', () => {
  it('omits unset filters and passes set ones', () => {
    expect(buildAnomalyParams({ limit: 50, offset: 0 })).toEqual({ limit: 50, offset: 0 })
    expect(
      buildAnomalyParams({ limit: 50, offset: 0, type: 'duration', acknowledged: false }),
    ).toEqual({ limit: 50, offset: 0, type: 'duration', acknowledged: false })
  })

  it('forwards the created_after/created_before time bounds', () => {
    expect(
      buildAnomalyParams({
        limit: 50,
        offset: 0,
        created_after: '2026-08-01T00:00:00.000Z',
        created_before: '2026-08-04T00:00:00.000Z',
      }),
    ).toEqual({
      limit: 50,
      offset: 0,
      created_after: '2026-08-01T00:00:00.000Z',
      created_before: '2026-08-04T00:00:00.000Z',
    })
  })
})
