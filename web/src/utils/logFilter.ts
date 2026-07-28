export const LOG_LEVELS = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'] as const
export type LogLevel = (typeof LOG_LEVELS)[number]

// Matches this app's own format ("%(asctime)s %(levelname)s %(name)s -
// %(message)s", see utils/logging.py) plus uvicorn's "LEVEL:    message"
// lines, since the log file is the whole process's stdout+stderr.
const APP_RECORD_START =
  /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+\s+(CRITICAL|ERROR|WARNING|WARN|INFO|DEBUG)\b/
const UVICORN_RECORD_START = /^(CRITICAL|ERROR|WARNING|WARN|INFO|DEBUG):\s/

function normalizeLevel(text: string): LogLevel {
  return text === 'WARN' ? 'WARNING' : (text as LogLevel)
}

/** Returns the detected level if `line` starts a new log record, or
 * `undefined` if it's a continuation line (traceback frame, multi-line
 * message, etc.) belonging to whatever record came before it. */
function detectRecordStart(line: string): LogLevel | null | undefined {
  const appMatch = line.match(APP_RECORD_START)
  if (appMatch) return normalizeLevel(appMatch[1])
  const uvicornMatch = line.match(UVICORN_RECORD_START)
  if (uvicornMatch) return normalizeLevel(uvicornMatch[1])
  return undefined
}

interface LogRecord {
  level: LogLevel | null
  lines: string[]
}

function parseRecords(content: string): LogRecord[] {
  const lines = content.split('\n')
  const records: LogRecord[] = []
  for (const line of lines) {
    const detected = detectRecordStart(line)
    if (detected !== undefined || records.length === 0) {
      records.push({ level: detected ?? null, lines: [line] })
    } else {
      records[records.length - 1].lines.push(line)
    }
  }
  return records
}

export interface LogFilterOptions {
  levels?: ReadonlySet<LogLevel>
  search?: string
}

/** Filters raw log text by level and free-text search, keeping continuation
 * lines (e.g. a traceback) attached to the record they belong to so a
 * level filter never severs a stack trace from its ERROR line. */
export function filterLogContent(content: string, opts: LogFilterOptions = {}): string {
  const { levels, search } = opts
  const allLevelsSelected = !levels || levels.size === 0 || levels.size === LOG_LEVELS.length
  const needle = search?.trim().toLowerCase()

  const kept = parseRecords(content).filter((record) => {
    if (!allLevelsSelected && record.level !== null && !levels!.has(record.level)) {
      return false
    }
    if (needle) {
      return record.lines.some((line) => line.toLowerCase().includes(needle))
    }
    return true
  })
  return kept.map((r) => r.lines.join('\n')).join('\n')
}
