import { describe, expect, it } from 'vitest'
import { groupFailuresByError, normalizeError } from './failureClustering'
import type { Sample } from '../types/api'

describe('normalizeError', () => {
  it('replaces a millisecond timeout', () => {
    expect(normalizeError('timeout 30000ms exceeded')).toBe('timeout <MS>ms exceeded')
  })

  it('replaces a decimal-second duration', () => {
    expect(normalizeError('waited 5.2s for selector')).toBe('waited <N>s for selector')
  })

  it('replaces a tap coordinate pair', () => {
    expect(normalizeError('tap at (495, 2059) failed')).toBe('tap at (<X>, <Y>) failed')
  })

  it('replaces an emulator device serial', () => {
    expect(normalizeError('device offline: emulator-5554')).toBe('device offline: <DEVICE>')
  })

  it('replaces a hex id that contains at least one digit', () => {
    expect(normalizeError('session abc123def456 not found')).toBe('session <ID> not found')
  })

  it('does not treat an all-letter word that happens to be hex-safe as an id', () => {
    // "facade" is 6 letters, all within a-f, but has no digit — a real word,
    // not an id, must not be replaced. This is exactly the false-positive
    // class the digit-lookahead in the id rule exists to avoid.
    expect(normalizeError('applied a facade wrapper')).toBe('applied a facade wrapper')
  })

  it('replaces an ISO-ish timestamp', () => {
    expect(normalizeError('failed at 2026-08-03T00:00:00Z')).toBe('failed at <TIMESTAMP>')
  })

  it('leaves quoted locator/selector content untouched', () => {
    expect(normalizeError("element not found: '#send-button'")).toBe(
      "element not found: '#send-button'",
    )
  })
})

function failedSample(id: string, error: string): Sample {
  return { id, prompts: ['x'], mode: 'api', target_profile: 'p', status: 'failed', error }
}

describe('groupFailuresByError', () => {
  it('returns nothing when there are no failed samples', () => {
    const samples: Sample[] = [
      { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', status: 'done' },
    ]
    expect(groupFailuresByError(samples)).toEqual([])
  })

  it('ignores a failed sample with no error text', () => {
    const samples: Sample[] = [
      { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', status: 'failed' },
    ]
    expect(groupFailuresByError(samples)).toEqual([])
  })

  it('groups errors that normalize to the same pattern', () => {
    const samples = [
      failedSample('s1', 'device offline: emulator-5554'),
      failedSample('s2', 'device offline: emulator-5556'),
    ]
    const groups = groupFailuresByError(samples)
    expect(groups).toEqual([
      {
        pattern: 'device offline: <DEVICE>',
        count: 2,
        sampleIds: ['s1', 's2'],
        example: 'device offline: emulator-5554',
      },
    ])
  })

  it('keeps genuinely different errors in separate groups', () => {
    const samples = [
      failedSample('s1', "element not found: '#send-button'"),
      failedSample('s2', "element not found: '#input'"),
    ]
    expect(groupFailuresByError(samples)).toHaveLength(2)
  })

  it('sorts groups by count descending', () => {
    const samples = [
      failedSample('s1', 'timeout 1000ms'),
      failedSample('s2', 'device offline: emulator-5554'),
      failedSample('s3', 'device offline: emulator-5556'),
      failedSample('s4', 'device offline: emulator-5558'),
    ]
    const groups = groupFailuresByError(samples)
    expect(groups.map((g) => g.count)).toEqual([3, 1])
    expect(groups[0].pattern).toBe('device offline: <DEVICE>')
  })
})
