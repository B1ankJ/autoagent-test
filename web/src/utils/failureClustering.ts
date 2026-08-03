import type { Sample } from '../types/api'

export interface FailureCluster {
  pattern: string
  count: number
  sampleIds: string[]
  example: string
}

// Order matters: the ms rule must run before the "s" duration rule so
// "30000ms" becomes "<MS>ms" first — by the time the "s" rule runs, there
// are no digits left directly before that "ms" for it to also match.
const NORMALIZATION_RULES: Array<[RegExp, string]> = [
  [/\d+(\.\d+)?ms\b/g, '<MS>ms'],
  [/\b\d+(\.\d+)?s\b/g, '<N>s'],
  [/\(\s*-?\d+\s*,\s*-?\d+\s*\)/g, '(<X>, <Y>)'],
  [/\bemulator-\d+\b/g, '<DEVICE>'],
  // Requires at least one digit in the run (via the lookahead) so a plain
  // English word that happens to use only a-f letters (e.g. "facade",
  // "deface") isn't mistaken for a hex id — real ids/hashes/serials always
  // have at least one digit in practice.
  [/\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{6,}\b/g, '<ID>'],
  [/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*/g, '<TIMESTAMP>'],
]

/** Replaces run-specific variable substrings (timeouts, coordinates, device
 * serials, hex ids, timestamps) in an error string with placeholder tokens,
 * so two errors with the same root cause but different embedded details
 * normalize to the same string. Deliberately does not touch quoted content
 * (locator/selector strings) — two "element not found" errors for two
 * different selectors are a real distinction worth keeping separate. */
export function normalizeError(error: string): string {
  return NORMALIZATION_RULES.reduce(
    (text, [pattern, replacement]) => text.replace(pattern, replacement),
    error,
  )
}

/** Groups a batch's failed samples by normalized error text, sorted by
 * count descending (ties keep first-appearance order — Array.sort is
 * stable, and Map preserves insertion order). */
export function groupFailuresByError(samples: Sample[]): FailureCluster[] {
  const groups = new Map<string, { sampleIds: string[]; example: string }>()
  for (const sample of samples) {
    if (sample.status !== 'failed' || !sample.error) continue
    const pattern = normalizeError(sample.error)
    const existing = groups.get(pattern)
    if (existing) {
      existing.sampleIds.push(sample.id)
    } else {
      groups.set(pattern, { sampleIds: [sample.id], example: sample.error })
    }
  }
  return [...groups.entries()]
    .map(([pattern, { sampleIds, example }]) => ({
      pattern,
      count: sampleIds.length,
      sampleIds,
      example,
    }))
    .sort((a, b) => b.count - a.count)
}
