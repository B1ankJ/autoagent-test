import { describe, expect, it } from 'vitest'

import { formatDurationMs } from './duration'

describe('formatDurationMs', () => {
  it('formats sub-second durations in ms', () => {
    expect(formatDurationMs(850)).toBe('850ms')
    expect(formatDurationMs(0)).toBe('0ms')
  })

  it('formats sub-minute durations in seconds with one decimal', () => {
    expect(formatDurationMs(12300)).toBe('12.3s')
    expect(formatDurationMs(59999)).toBe('60.0s')
  })

  it('formats minute-plus durations as Xm Ys', () => {
    expect(formatDurationMs(65000)).toBe('1m 5s')
    expect(formatDurationMs(125000)).toBe('2m 5s')
  })
})
