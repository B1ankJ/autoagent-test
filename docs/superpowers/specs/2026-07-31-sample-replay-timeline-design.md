# Sample Replay Timeline — Design

## Problem

Debugging a failed/odd GUI (`gui_pc_web`/`gui_android`) sample today means manually
cross-referencing two disconnected views on SampleDetail: a horizontal strip of
milestone/per-action screenshots (`ScreenshotStrip`) and a separate table of raw
`action_log` entries (`t_ms`, action type, coordinates/locator, ok/error). Neither
view shows "what the screen looked like right before/after this specific action" —
reconstructing that sequence by eye across two disjoint UI elements is slow and
error-prone, especially for samples with many steps.

## Goals

- Replace the screenshot strip + action log table on SampleDetail with a single
  scrubbable timeline: a large image of the screen state at the current point in
  time, a bottom slider marking every screenshot/action along a shared time axis,
  and per-action detail (target coordinates/locator, success/failure) shown when an
  action marker is selected.
- No backend changes — merge existing data client-side.

## Non-goals (this iteration)

- `agent_pc`/`agent_android` support. Their `action_log` shape (`step`/`raw`/`action`/
  `execution`, no timestamp) is structurally different from the GUI executors'
  (`t_ms`-based) — folding both into one timeline model is real design work on its
  own, deferred to a follow-up. Samples in these modes keep the current screenshot
  strip (see "Fallback" below) rather than a half-correct timeline.
- Autoplay. Manual scrub/click navigation only.
- Any change to how `action_log` or screenshots are captured/stored server-side.

## Data model

Two existing data sources, both already fetched by SampleDetail today:

- `sample.metadata.action_log: { t_ms: number, action: string, ok?: boolean, error?: string, x?, y?, x1?, y1?, x2?, y2?, locator?, key?, package?, text_length? }[]`
  — populated by `ActionRunner`/`AndroidActionRunner` for `gui_pc_web`/`gui_android`
  samples only. `t_ms` is elapsed milliseconds since the runner was constructed,
  which happens right after session setup, immediately before the action loop
  starts.
- Screenshots via the existing `listScreenshots(batchId, sampleId)` — each entry has
  `name`, `label`, `taken_at` (absolute datetime), `is_sensitive`. No `t_ms`.

### Merging onto one axis

`t_ms` and `taken_at` have different origins (monotonic-since-runner-start vs.
wall-clock), so they can't be compared directly. Anchor on the *first* screenshot
instead of `sample.started_at`: the first screenshot is always the "ready"
milestone, captured right after session setup — the same moment the action loop
(and its `t_ms` clock) starts. So:

```
screenshot.elapsedMs = (screenshot.taken_at - screenshots[0].taken_at) in ms
action.elapsedMs     = action.t_ms
```

Both series then merge-sort into one `TimelineEvent[]` by `elapsedMs`:

```ts
type TimelineEvent =
  | { kind: 'screenshot'; elapsedMs: number; screenshot: ScreenshotInfo }
  | { kind: 'action'; elapsedMs: number; entry: ActionLogEntry }
```

This is an approximation (JPEG encode + disk write time between the actual screen
capture and `taken_at` isn't accounted for), not a certified log — acceptable for a
debugging aid, and consistent with how `t_ms` values already work today (also just
"close enough" for reading a timeline by eye).

## Components

**`SampleReplayTimeline.tsx`** (new, replaces `ScreenshotStrip` usage + the inline
action log `<Table>` on SampleDetail):

- Input: `batchId`, `sampleId`, `actionLog: ActionLogEntry[]` (from
  `sample.metadata.action_log`, already loaded by SampleDetail).
- Fetches screenshots via the existing `listScreenshots` (same query SampleDetail
  already runs), builds the merged `TimelineEvent[]` client-side.
- State: `selectedIndex` into the merged array (starts at the last event overall —
  usually a milestone screenshot, the final state — the most useful default for
  "why did this fail").
- Layout:
  - Large image: `screenshotUrl(...)` for "the screenshot at or before
    `selectedIndex`" (an action event has no image of its own — it reuses the
    nearest preceding screenshot).
  - Below the image: when the selected event is an action, an info line reusing the
    existing `formatActionTarget`-style rendering (coordinates/locator/key) plus an
    ok/error badge.
  - Bottom: AntD `<Slider>`, `min=0`/`max=events.length-1`, custom `marks` at every
    event index — screenshot marks in blue, action marks green (ok) or red
    (`ok === false`). Clicking a mark or dragging the handle sets `selectedIndex`.
    Tooltip on hover shows the label/action name + elapsed time (`Xs` / `X.Xs`).

**Fallback (no `action_log`)**: `gui_pc_web`/`gui_android` samples always have one
(even a single "ready" entry at minimum, per the executors above); other modes
(`api`, `agent_pc`, `agent_android`) or legacy pre-verbose-logs samples may have
none. When `actionLog` is empty, `SampleReplayTimeline` renders screenshots-only —
same slider, only blue marks, no action-detail panel. This is a strict subset of
the full behavior (same component, not a separate code path), so there's no
dead-end mode to maintain separately.

## Error handling

- Zero screenshots at all (sample never got far enough to capture one): render the
  existing `EmptyState` pattern already used elsewhere on this page, no slider.
- An individual screenshot fails to load (404/network): reuse `ScreenshotStrip`'s
  existing broken-image handling approach for the large image area.

## Testing

- Unit test the merge/sort function in isolation (pure function, easy to hit edge
  cases: empty action_log, empty screenshots, out-of-order timestamps, ties).
- Component test: renders with a fixture of 3 screenshots + 4 actions, verifies
  slider mark count, clicking a mark updates the large image `src` and shows the
  right action detail, and the no-`action_log` fallback shows screenshot-only marks.
