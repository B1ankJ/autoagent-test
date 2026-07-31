import type { ScreenshotInfo } from '../types/api'

export interface ActionLogEntry {
  t_ms: number
  action?: string
  ok?: boolean
  error?: string
  x?: number
  y?: number
  x1?: number
  y1?: number
  x2?: number
  y2?: number
  locator?: { type?: string; value?: string }
  key?: string
  package?: string
  activity?: string
  url?: string
  text_length?: number
}

export type TimelineEvent =
  | { kind: 'screenshot'; elapsedMs: number; screenshot: ScreenshotInfo }
  | { kind: 'action'; elapsedMs: number; entry: ActionLogEntry }

/**
 * Merges action_log (t_ms, relative to when the action loop started) and
 * screenshots (taken_at, absolute) onto one sorted time axis. Anchored on
 * the first screenshot's taken_at as elapsedMs=0 — that's always the
 * "ready" milestone, captured right when the action loop (and its t_ms
 * clock) starts, so the two series line up closely enough for a debugging
 * timeline without needing any backend change to record a shared clock.
 */
export function buildTimelineEvents(
  actionLog: ActionLogEntry[],
  screenshots: ScreenshotInfo[],
): TimelineEvent[] {
  const firstShotMs = screenshots.length > 0 ? new Date(screenshots[0].taken_at).getTime() : 0

  const screenshotEvents: TimelineEvent[] = screenshots.map((screenshot) => ({
    kind: 'screenshot',
    elapsedMs: new Date(screenshot.taken_at).getTime() - firstShotMs,
    screenshot,
  }))
  const actionEvents: TimelineEvent[] = actionLog.map((entry) => ({
    kind: 'action',
    elapsedMs: entry.t_ms,
    entry,
  }))

  // Array.prototype.sort is stable (guaranteed since ES2019) — screenshots
  // are concatenated first, so a tie keeps the screenshot ahead of the
  // action, a reasonable default ("here's the frame, then what happened").
  return [...screenshotEvents, ...actionEvents].sort((a, b) => a.elapsedMs - b.elapsedMs)
}

function formatLocator(locator: unknown): string {
  if (!locator || typeof locator !== 'object') return '-'
  const maybeLocator = locator as { type?: unknown; value?: unknown }
  if (typeof maybeLocator.type === 'string' && typeof maybeLocator.value === 'string') {
    return `${maybeLocator.type}:${maybeLocator.value}`
  }
  return '-'
}

/** Moved here from SampleDetail.tsx (its only caller) — describes an
 * action_log entry's target in one short string for display. */
export function formatActionTarget(record: Record<string, unknown>): string {
  if (typeof record.x === 'number' && typeof record.y === 'number') {
    return `(${record.x}, ${record.y})`
  }
  if (record.locator) {
    return formatLocator(record.locator)
  }
  if (typeof record.url === 'string') {
    return record.url
  }
  if (
    typeof record.x1 === 'number' &&
    typeof record.y1 === 'number' &&
    typeof record.x2 === 'number' &&
    typeof record.y2 === 'number'
  ) {
    return `(${record.x1}, ${record.y1}) -> (${record.x2}, ${record.y2})`
  }
  if (typeof record.key === 'string') {
    return record.key
  }
  if (typeof record.package === 'string' && typeof record.activity === 'string') {
    return `${record.package}/${record.activity}`
  }
  if (typeof record.package === 'string') {
    return record.package
  }
  return '-'
}
