import { describe, expect, it } from 'vitest'
import { buildAnomalyParams } from './anomalies'

describe('buildAnomalyParams', () => {
  it('omits unset filters and passes set ones', () => {
    expect(buildAnomalyParams({ limit: 50, offset: 0 })).toEqual({ limit: 50, offset: 0 })
    expect(
      buildAnomalyParams({ limit: 50, offset: 0, type: 'duration', acknowledged: false }),
    ).toEqual({ limit: 50, offset: 0, type: 'duration', acknowledged: false })
  })
})
