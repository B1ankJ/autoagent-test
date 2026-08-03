import { describe, expect, it } from 'vitest'
import { buildBatchComparison } from './batchComparison'
import type { Sample } from '../types/api'

function sample(overrides: Partial<Sample> & { id: string }): Sample {
  return {
    prompts: ['hi'],
    mode: 'api',
    target_profile: 'p',
    ...overrides,
  }
}

describe('buildBatchComparison', () => {
  it('aligns samples by id, sorted by id, counting common/only-A/only-B', () => {
    const a = [
      sample({ id: 's2', responses: ['A2'], duration_ms: 100 }),
      sample({ id: 's1', responses: ['A1'], duration_ms: 200 }),
      sample({ id: 'only-a', responses: ['x'], duration_ms: 50 }),
    ]
    const b = [
      sample({ id: 's1', responses: ['B1'], duration_ms: 220 }),
      sample({ id: 's2', responses: ['A2'], duration_ms: 90 }),
      sample({ id: 'only-b', responses: ['y'], duration_ms: 60 }),
    ]

    const result = buildBatchComparison(a, b)

    expect(result.rows.map((r) => r.sampleId)).toEqual([
      'only-a',
      'only-b',
      's1',
      's2',
    ])
    expect(result.commonCount).toBe(2)
    expect(result.onlyACount).toBe(1)
    expect(result.onlyBCount).toBe(1)

    const s1 = result.rows.find((r) => r.sampleId === 's1')!
    expect(s1.a).toEqual({ durationMs: 200, effectiveResponse: 'A1' })
    expect(s1.b).toEqual({ durationMs: 220, effectiveResponse: 'B1' })

    const onlyA = result.rows.find((r) => r.sampleId === 'only-a')!
    expect(onlyA.a).not.toBeNull()
    expect(onlyA.b).toBeNull()

    const onlyB = result.rows.find((r) => r.sampleId === 'only-b')!
    expect(onlyB.a).toBeNull()
    expect(onlyB.b).not.toBeNull()
  })

  it('uses the LLM-reviewed response as effective when LLM extraction succeeded', () => {
    const a = [
      sample({
        id: 's1',
        responses: ['raw'],
        llm_responses: ['reviewed'],
        llm_errors: [null],
      }),
    ]
    const b = [sample({ id: 's1', responses: ['raw'] })]

    const result = buildBatchComparison(a, b)
    const row = result.rows[0]
    expect(row.a?.effectiveResponse).toBe('reviewed')
    expect(row.b?.effectiveResponse).toBe('raw')
  })

  it('falls back to the raw response when the LLM extraction errored', () => {
    const a = [
      sample({
        id: 's1',
        responses: ['raw'],
        llm_responses: [''],
        llm_errors: ['auth failed'],
      }),
    ]
    const result = buildBatchComparison(a, [])
    expect(result.rows[0].a?.effectiveResponse).toBe('raw')
  })

  it('compares only the first round of a multi-round sample', () => {
    const a = [sample({ id: 's1', responses: ['first', 'second'] })]
    const b = [sample({ id: 's1', responses: ['FIRST', 'SECOND'] })]
    const result = buildBatchComparison(a, b)
    expect(result.rows[0].a?.effectiveResponse).toBe('first')
    expect(result.rows[0].b?.effectiveResponse).toBe('FIRST')
  })

  it('returns empty rows and zero counts for two empty batches', () => {
    const result = buildBatchComparison([], [])
    expect(result.rows).toEqual([])
    expect(result.commonCount).toBe(0)
    expect(result.onlyACount).toBe(0)
    expect(result.onlyBCount).toBe(0)
  })
})
