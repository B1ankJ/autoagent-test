import type { Sample } from '../types/api'
import { hasLLMExtractionData, selectEffectiveResponseText } from './llmExtraction'

/** One side (A or B) of a compared sample: its duration and the single
 * "effective" response (rule vs LLM-reviewed, same priority as everywhere
 * else in the app), for the first prompt round only. */
export interface SampleSide {
  durationMs?: number
  effectiveResponse: string
}

/** One aligned row: a sample id and each batch's side (null = the id is
 * absent from that batch). */
export interface SampleComparisonRow {
  sampleId: string
  a: SampleSide | null
  b: SampleSide | null
}

export interface BatchComparison {
  rows: SampleComparisonRow[]
  commonCount: number
  onlyACount: number
  onlyBCount: number
}

// Only the first prompt round is compared — most batches are single-round,
// and multi-round comparison is an explicit non-goal for this iteration.
function sideOf(sample: Sample): SampleSide {
  const llmEnabled = hasLLMExtractionData(sample.llm_responses, sample.llm_errors)
  const effectiveResponse = selectEffectiveResponseText({
    ruleResponse: sample.responses?.[0],
    llmResponse: sample.llm_responses?.[0],
    llmError: sample.llm_errors?.[0],
    llmEnabled,
  })
  return { durationMs: sample.duration_ms, effectiveResponse }
}

/** Aligns two batches' sample arrays by `Sample.id`. Rows cover every id
 * present in either batch, sorted by id. A row where the id exists in only
 * one batch has the missing side as `null`. */
export function buildBatchComparison(samplesA: Sample[], samplesB: Sample[]): BatchComparison {
  const mapA = new Map(samplesA.map((s) => [s.id, s]))
  const mapB = new Map(samplesB.map((s) => [s.id, s]))
  const allIds = Array.from(new Set([...mapA.keys(), ...mapB.keys()])).sort()

  let commonCount = 0
  let onlyACount = 0
  let onlyBCount = 0

  const rows: SampleComparisonRow[] = allIds.map((id) => {
    const sa = mapA.get(id)
    const sb = mapB.get(id)
    if (sa && sb) commonCount++
    else if (sa) onlyACount++
    else onlyBCount++
    return {
      sampleId: id,
      a: sa ? sideOf(sa) : null,
      b: sb ? sideOf(sb) : null,
    }
  })

  return { rows, commonCount, onlyACount, onlyBCount }
}
