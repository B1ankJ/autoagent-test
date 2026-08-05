export interface HighlightSegment {
  text: string
  mark: boolean
}

/** Split `text` into plain/marked segments around case-insensitive
 * occurrences of `term`. The term is regex-escaped so metacharacters match
 * literally. An empty term or no match returns the whole text unmarked. */
export function splitHighlight(text: string, term: string): HighlightSegment[] {
  if (!term) return [{ text, mark: false }]
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi')).filter((p) => p !== '')
  const isMatch = new RegExp(`^${escaped}$`, 'i')
  const out = parts.map((p) => ({ text: p, mark: isMatch.test(p) }))
  return out.length ? out : [{ text, mark: false }]
}
