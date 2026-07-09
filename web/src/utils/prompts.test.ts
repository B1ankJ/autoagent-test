import { describe, expect, it } from 'vitest'
import { splitPrompts } from './prompts'

describe('splitPrompts', () => {
  it('splits multiple prompts separated by a blank line', () => {
    expect(splitPrompts('hello\n\nworld')).toEqual(['hello', 'world'])
  })

  it('keeps a single newline inside one prompt', () => {
    expect(splitPrompts('line one\nline two')).toEqual(['line one\nline two'])
  })

  it('treats a whitespace-only blank line as a separator too', () => {
    expect(splitPrompts('a\n  \nb')).toEqual(['a', 'b'])
  })

  it('collapses multiple consecutive blank lines into one separator', () => {
    expect(splitPrompts('a\n\n\n\nb')).toEqual(['a', 'b'])
  })

  it('normalizes CRLF line endings', () => {
    expect(splitPrompts('a\r\n\r\nb')).toEqual(['a', 'b'])
  })

  it('trims leading/trailing whitespace per prompt and drops empty entries', () => {
    expect(splitPrompts('  \n\n  first  \n\n\n  second  \n\n  ')).toEqual(['first', 'second'])
  })

  it('returns an empty array for blank input', () => {
    expect(splitPrompts('   \n\n  ')).toEqual([])
  })
})
