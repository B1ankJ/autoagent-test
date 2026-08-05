import { describe, expect, it } from 'vitest'
import { splitHighlight } from './highlight'

describe('splitHighlight', () => {
  it('marks case-insensitive matches and leaves the rest plain', () => {
    expect(splitHighlight('Hello WORLD hello', 'hello')).toEqual([
      { text: 'Hello', mark: true },
      { text: ' WORLD ', mark: false },
      { text: 'hello', mark: true },
    ])
  })

  it('escapes regex metacharacters in the term', () => {
    expect(splitHighlight('a.b.c', '.')).toEqual([
      { text: 'a', mark: false },
      { text: '.', mark: true },
      { text: 'b', mark: false },
      { text: '.', mark: true },
      { text: 'c', mark: false },
    ])
  })

  it('returns the whole text unmarked when there is no match or empty term', () => {
    expect(splitHighlight('abc', 'x')).toEqual([{ text: 'abc', mark: false }])
    expect(splitHighlight('abc', '')).toEqual([{ text: 'abc', mark: false }])
  })
})
