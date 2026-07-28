import { describe, expect, it } from 'vitest'

import { filterLogContent } from './logFilter'

const APP_INFO = '2026-07-28 10:00:00,123 INFO autoagent.main - started'
const APP_ERROR = '2026-07-28 10:00:01,456 ERROR autoagent.api - boom'
const TRACE_HEADER = 'Traceback (most recent call last):'
const TRACE_FRAME = '  File "app.py", line 10, in foo'
const UVICORN_INFO = 'INFO:     Uvicorn running on http://0.0.0.0:8000'

describe('filterLogContent', () => {
  it('returns everything unchanged when no filters are given', () => {
    const content = [APP_INFO, APP_ERROR].join('\n')
    expect(filterLogContent(content)).toBe(content)
  })

  it('filters records by level', () => {
    const content = [APP_INFO, APP_ERROR].join('\n')
    const result = filterLogContent(content, { levels: new Set(['ERROR']) })
    expect(result).toBe(APP_ERROR)
  })

  it('keeps traceback continuation lines attached to their ERROR record', () => {
    const content = [APP_INFO, APP_ERROR, TRACE_HEADER, TRACE_FRAME].join('\n')
    const result = filterLogContent(content, { levels: new Set(['ERROR']) })
    expect(result).toBe([APP_ERROR, TRACE_HEADER, TRACE_FRAME].join('\n'))
  })

  it('treats an empty or full level set as "no filtering"', () => {
    const content = [APP_INFO, APP_ERROR].join('\n')
    expect(filterLogContent(content, { levels: new Set() })).toBe(content)
    expect(
      filterLogContent(content, {
        levels: new Set(['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']),
      }),
    ).toBe(content)
  })

  it('filters by case-insensitive search text', () => {
    const content = [APP_INFO, APP_ERROR].join('\n')
    expect(filterLogContent(content, { search: 'BOOM' })).toBe(APP_ERROR)
    expect(filterLogContent(content, { search: 'nope' })).toBe('')
  })

  it('combines level and search filters', () => {
    const content = [APP_INFO, APP_ERROR].join('\n')
    const result = filterLogContent(content, {
      levels: new Set(['ERROR']),
      search: 'started',
    })
    expect(result).toBe('')
  })

  it('normalizes WARN to WARNING and recognizes uvicorn-style lines', () => {
    const uvicornWarn = 'WARN:     something odd'
    const content = [UVICORN_INFO, uvicornWarn].join('\n')
    expect(filterLogContent(content, { levels: new Set(['WARNING']) })).toBe(uvicornWarn)
  })

  it('always keeps unrecognized leading content regardless of level filter', () => {
    const preamble = 'some startup banner with no timestamp'
    const content = [preamble, APP_ERROR].join('\n')
    const result = filterLogContent(content, { levels: new Set(['ERROR']) })
    expect(result).toBe(content)
  })
})
