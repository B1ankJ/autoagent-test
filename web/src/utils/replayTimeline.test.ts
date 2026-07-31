import { describe, expect, it } from 'vitest'
import { buildTimelineEvents, formatActionTarget, type ActionLogEntry } from './replayTimeline'
import type { ScreenshotInfo } from '../types/api'

describe('buildTimelineEvents', () => {
  it('returns an empty array when there is nothing at all', () => {
    expect(buildTimelineEvents([], [])).toEqual([])
  })

  it('sorts screenshot-only input by taken_at, anchored so the first is elapsedMs=0', () => {
    const shots: ScreenshotInfo[] = [
      { name: 'a.jpg', label: 'ready', taken_at: '2026-01-01T00:00:00.000Z' },
      { name: 'b.jpg', label: 'done', taken_at: '2026-01-01T00:00:02.500Z' },
    ]
    const events = buildTimelineEvents([], shots)
    expect(events).toEqual([
      { kind: 'screenshot', elapsedMs: 0, screenshot: shots[0] },
      { kind: 'screenshot', elapsedMs: 2500, screenshot: shots[1] },
    ])
  })

  it('sorts action-only input by t_ms directly', () => {
    const actions: ActionLogEntry[] = [
      { t_ms: 500, action: 'send' },
      { t_ms: 100, action: 'tap_xy', x: 1, y: 2 },
    ]
    const events = buildTimelineEvents(actions, [])
    expect(events.map((e) => e.elapsedMs)).toEqual([100, 500])
    expect(events[0]).toEqual({ kind: 'action', elapsedMs: 100, entry: actions[1] })
  })

  it('interleaves screenshots and actions on one sorted axis', () => {
    const shots: ScreenshotInfo[] = [
      { name: 'a.jpg', label: 'ready', taken_at: '2026-01-01T00:00:00.000Z' },
      { name: 'b.jpg', label: 'after_send', taken_at: '2026-01-01T00:00:01.000Z' },
    ]
    const actions: ActionLogEntry[] = [{ t_ms: 500, action: 'tap_xy', x: 1, y: 2 }]
    const events = buildTimelineEvents(actions, shots)
    expect(events.map((e) => e.kind)).toEqual(['screenshot', 'action', 'screenshot'])
    expect(events.map((e) => e.elapsedMs)).toEqual([0, 500, 1000])
  })

  it('breaks a tie (identical elapsedMs) by putting the screenshot first', () => {
    const shots: ScreenshotInfo[] = [
      { name: 'a.jpg', label: 'ready', taken_at: '2026-01-01T00:00:00.000Z' },
    ]
    const actions: ActionLogEntry[] = [{ t_ms: 0, action: 'tap_xy', x: 1, y: 2 }]
    const events = buildTimelineEvents(actions, shots)
    expect(events.map((e) => e.kind)).toEqual(['screenshot', 'action'])
  })
})

describe('formatActionTarget', () => {
  it('formats a tap coordinate', () => {
    expect(formatActionTarget({ x: 495, y: 2059 })).toBe('(495, 2059)')
  })

  it('formats a locator', () => {
    expect(formatActionTarget({ locator: { type: 'xpath', value: '//*[@text="发送"]' } })).toBe(
      'xpath://*[@text="发送"]',
    )
  })

  it('formats a swipe path', () => {
    expect(formatActionTarget({ x1: 1, y1: 2, x2: 3, y2: 4 })).toBe('(1, 2) -> (3, 4)')
  })

  it('falls back to "-" for an unrecognized shape', () => {
    expect(formatActionTarget({})).toBe('-')
  })
})
