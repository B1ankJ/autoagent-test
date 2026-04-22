# Plan 3 — Web GUI Executor (Playwright) — Design

- **Date:** 2026-04-22
- **Status:** Draft (awaiting implementation plan)
- **Predecessor:** Plan 2 React Web UI (tag `web-ui-v0.2.0`)
- **Language:** Python 3.11, TypeScript

---

## 1. Scope

### 1.1 Goal

Add `mode=gui_pc_web` execution capability to AutoAgent Test. Playwright drives a real Chromium to open a target chat site, fill a prompt, send it, wait for the response to complete, and read the final text from the DOM. Full-fidelity response capture at parity with the API executor.

### 1.2 Deliverables

**Backend:**
- `WebExecutor` (Playwright-based) implementing the existing `Executor` abstract base.
- `ActionRunner` executing 6 action types for `recovery_path` and `new_session_action`.
- `CompleteDetector` implementing `dom_stable` and `send_button_reenable`.
- `ScreenshotStore` writing screenshots under `<data_root>/logs/<batch_id>/<sample_id>/NNN_<label>.png`.
- In-process event bus + SSE endpoint for streaming batch progress.
- Scheduler auto-downgrades concurrency to 1 for profiles with `browser.user_data_dir`.
- Three new HTTP endpoints: screenshot list, screenshot download, SSE events.
- `/tests/sync` dispatches by `profile.platform` to the correct executor.

**Frontend:**
- `gui_pc_web` option in mode dropdowns (BatchNew, Tests/Quick).
- Connectivity test button in Profile Edit enabled for `platform: web` profiles (180s per-call timeout).
- SampleDetail page: horizontal screenshot strip (lazy-loaded thumbs, modal viewer with keyboard nav) + action log table.
- `useBatchStream(id)` hook replacing `useBatch(id)` polling while preserving the consumer-facing return shape.

**Tests:**
- ~18 unit tests mocking Playwright (action runner, complete detector, screenshot store, web executor, event bus, sample model).
- ~7 integration tests: real Playwright against `tests/fixtures/fake_chat.html` (gated by `@pytest.mark.playwright`), plus HTTP-only integration tests for SSE and screenshot endpoints.
- Existing 68 tests must not regress.

**Docs:**
- This design document.
- Implementation plan at `docs/superpowers/plans/2026-04-22-plan-3-web-gui-executor.md` (next step).
- README updated with Web executor usage + `playwright install chromium` prerequisite.
- CLAUDE.md updated on Plan 3 completion.

### 1.3 Explicit non-goals

- Android executor (Plan 4).
- VLM-assisted completion detection / `vlm_task` action type.
- Automatic re-login via `recovery_path` when the persistent session expires.
- Screenshot TTL / automatic cleanup (deferred to Plan 5).
- WebSocket (SSE covers the same scope more simply).

---

## 2. Decisions Already Made (from brainstorming)

| # | Question | Decision |
|---|---|---|
| 1 | Scope | Option A: full (executor + full Plan 2 handoff items: mode dropdown, connectivity test, SSE replacement, SampleDetail screenshots). |
| 2 | Concurrency & persistent sessions | Option A: profile with `user_data_dir` auto-forces serial (`concurrency=1`, WARN log); ephemeral profiles honor `batch.concurrency`. |
| 3 | Testing approach | Option A: mocked-Playwright unit tests (default) + real-Playwright integration tests against `fake_chat.html` (marked `@pytest.mark.playwright`, default-run, require one-time `playwright install chromium`). |
| 4 | Progress push | Option B: SSE (`text/event-stream`) over a GET endpoint. Uses `sse-starlette`. Frontend `EventSource` handles reconnect natively. |
| 5 | Screenshot strategy | Option A: tied to existing `ExecutorContext.verbose_logs`. Verbose (current default `True`) → per-action screenshots; non-verbose → milestones only. Always-on screenshot for errors and `recovery_path` triggers. Screenshots served via cached immutable HTTP endpoints. |
| 6 | Action vocabulary | Option B (medium, 6 actions): `goto`, `wait_for`, `click`, `sleep`, `fill`, `press`. `fill.text` supports `$ENV_VAR` expansion; missing env var → `ValueError` at runtime. No `eval_js` (injection surface), no explicit `screenshot` action (redundant with auto-capture). |

---

## 3. Architecture

### 3.1 Module layout

```
src/autoagent/
  executors/
    web_executor.py        ← new. Subclasses Executor; implements execute()
    action_runner.py       ← new. 6 actions, used by web_executor
    complete_detector.py   ← new. dom_stable + send_button_reenable
    screenshot_store.py    ← new. Path generation + directory creation
  scheduler/
    batch_scheduler.py     ← modified. Web profile → concurrency=1 (WARN log)
  api/
    batches.py             ← modified. +3 endpoints (screenshots list/download, SSE events)
    tests.py               ← modified. /tests/sync dispatches by profile.platform
  events/
    bus.py                 ← new. In-process pub/sub
  main.py                  ← unchanged
tests/
  fixtures/
    fake_chat.html         ← new. Integration test target
  unit/
    test_action_runner.py        ← new
    test_complete_detector.py    ← new
    test_screenshot_store.py     ← new
    test_web_executor_unit.py    ← new
    test_event_bus.py            ← new
  integration/
    test_web_executor_e2e.py     ← new, @pytest.mark.playwright
    test_sse_endpoint.py         ← new
    test_screenshots_endpoint.py ← new
```

### 3.2 Web sample execution flow

```
Scheduler
  └─▶ WebExecutor.execute(sample, profile, ctx)
        ├─▶ Browser = chromium.launch(
        │       headless=profile.browser.headless,
        │       user_data_dir=profile.browser.user_data_dir,  # if set
        │   )
        │   # user_data_dir != None: single Browser shared for the whole batch
        │   # user_data_dir == None: new Browser per sample (ephemeral)
        ├─▶ Context = browser.new_context()
        ├─▶ Page = context.new_page()
        ├─▶ goto(profile.url)  →  wait for profile.ready_check    [screenshot: 01_ready]
        ├─▶ if sample.new_session: ActionRunner.run(profile.new_session_action)
        ├─▶ for prompt in sample.prompts:
        │     ├─▶ page.fill(profile.input_selector, prompt)        [screenshot: 02_filled]
        │     ├─▶ send_method (keyboard press / click_button)      [screenshot: 03_sent]
        │     ├─▶ CompleteDetector.wait(profile.complete_detection, page)
        │     ├─▶ text = page.inner_text(profile.response_container_selector)
        │     └─▶                                                   [screenshot: 04_done]
        │         append text to responses[]
        └─▶ return responses
  ── exception ──▶ ActionRunner.run(profile.recovery_path)          [screenshot: 99_recovery]
                    retry (up to sample.retry + 1 total attempts)

ctx.action_log: list[dict]  appended throughout; copied to SampleResult.metadata["action_log"]
SampleResult.logs_dir = <data_root>/logs/<batch_id>/<sample_id>
```

### 3.3 Browser lifecycle

- **Ephemeral profile (`user_data_dir` is None):** one `chromium.launch()` per sample; disposed at sample end. `batch.concurrency` is honored fully.
- **Persistent profile (`user_data_dir` set):** one `chromium.launch_persistent_context(user_data_dir=...)` for the whole batch; each sample gets its own `Page` but shares the context. Chromium's single-profile file-lock prevents parallel launches, so scheduler forces `concurrency=1` with a WARN log if the user requested higher.

### 3.4 Event bus + SSE

In-process pub/sub:

```python
# events/bus.py  (pseudocode)
class BatchEventBus:
    _subs: dict[str, set[asyncio.Queue]]   # batch_id → subscriber queues
    _seq: dict[str, int]                   # batch_id → monotonic counter

    async def publish(self, batch_id: str, kind: str, payload: dict) -> None: ...
    def subscribe(self, batch_id: str) -> AsyncIterator[dict]: ...     # unsub on GC
```

Published events (each `kind` with a monotonic `seq`):

- `sample_update`: `{sample_id, status, duration_ms}` — emitted when a sample enters or leaves `running`.
- `batch_progress`: `{done, failed, total, running}` — emitted after each sample completion.
- `batch_done`: `{status: done | failed | cancelled}` — terminal; client should close `EventSource`.

SSE endpoint (`sse-starlette`):

```python
@router.get("/batches/{batch_id}/events")
async def stream_events(batch_id: str, user = Depends(require_user)) -> EventSourceResponse:
    ...
```

**Durability:** the bus is in-memory per process. Each batch keeps a small ring buffer of the last ~100 events in memory to support SSE `Last-Event-ID` resume across brief disconnects. On process restart the buffer is empty, and clients fall back to a fresh `GET /batches/{id}` snapshot (which includes the current `seq`) and re-subscribe.

### 3.5 Scheduler concurrency rule

Before launching web executors for a batch, scheduler loads the profile. If `profile.browser.user_data_dir` is truthy:

```python
if actual_concurrency > 1:
    log.warning("batch %s: profile %s has user_data_dir; forcing concurrency=1",
                batch_id, profile.name)
    actual_concurrency = 1
```

API executor and ephemeral web profiles keep the caller's `batch.concurrency`.

---

## 4. Data Model Changes

- `SampleResult.metadata["action_log"]: list[dict]` where each entry is `{t_ms: int, action: str, selector: str | None, ok: bool, error: str | None}`. Stored inside the existing `metadata` dict; no schema change to `SampleResult`.
- `SampleResult.logs_dir: str | None` — already exists; the web executor populates it.
- `Sample.mode`: extended from `Literal["api"]` to `Literal["api", "gui_pc_web"]`.
- **`BatchDetail` gains a new field `seq: int`** — the last event seq absorbed into the snapshot. Used by the frontend to reconcile initial GET + SSE stream (§6.1). Default `0` when the bus has never published for this batch.

Frontend `ExecutionMode` in `web/src/types/api.ts` extended accordingly; `BatchDetail` type gains `seq: number`.

---

## 5. API Surface (3 new endpoints + 1 router change)

All under `/api/v1`, all `Depends(require_user)`.

### 5.1 `GET /batches/{batch_id}/samples/{sample_id}/screenshots`

List screenshots for a sample. Response:

```json
[
  {"name": "01_ready.png", "label": "ready", "taken_at": "2026-04-22T12:34:56Z"},
  {"name": "02_filled.png", "label": "filled", "taken_at": "..."}
]
```

### 5.2 `GET /batches/{batch_id}/samples/{sample_id}/screenshots/{name}`

Returns the PNG. Response headers:

```
Content-Type: image/png
Cache-Control: public, max-age=31536000, immutable
```

Filename whitelist regex: `^\d{2,3}_[a-z0-9_]+\.png$`. Any other value → 400. The full resolved path is additionally validated to live under `<data_root>/logs/<batch_id>/<sample_id>/` via `Path.resolve()` comparison, preventing traversal via unicode or symlink.

### 5.3 `GET /batches/{batch_id}/events`

SSE stream. Each event is JSON with fields `{seq, kind, payload, ts}`. See §3.4.

### 5.4 `POST /tests/sync` dispatch change

Existing endpoint. Internally:

```python
if profile.platform == "api":      executor = ApiExecutor()
elif profile.platform == "web":    executor = WebExecutor()
else:                              raise HTTPException(400, "unsupported platform")
```

Connectivity test (Profile Edit button) reuses this endpoint; no new route. Frontend applies a per-call 180s axios timeout override when the target profile is `platform: web`.

---

## 6. Frontend Changes

| File | Action | Summary |
|---|---|---|
| `types/api.ts` | modify | `ExecutionMode = "api" \| "gui_pc_web"`; new `ScreenshotInfo`; optional `action_log` typing on `SampleResult.metadata` |
| `pages/Profiles/Edit.tsx` | modify | Connectivity test enabled for `platform: web`; axios `.post(..., {..., timeout: 180000})` override per-call |
| `pages/Batches/New.tsx` | modify | Mode dropdown adds `gui_pc_web`; profile filter follows selected mode |
| `pages/Tests/Quick.tsx` | modify | Same mode extension; 180s per-call timeout for web sync |
| `pages/Batches/SampleDetail.tsx` | modify | Add `ScreenshotStrip` + `ActionLogTable` blocks |
| `api/batches.ts` | modify | `useBatch(id)` → `useBatchStream(id)`; consumer-facing return shape unchanged |
| `api/screenshots.ts` | **new** | `listScreenshots(batchId, sampleId)` + `screenshotUrl(batchId, sampleId, name)` |
| `hooks/useBatchStream.ts` | **new** | Internal: `useQuery` initial snapshot + `EventSource` for live updates; `seq` dedup; unmount closes source |
| `components/ScreenshotStrip.tsx` | **new** | Lazy-loaded `<img loading="lazy">` thumbs + `Modal` viewer + keyboard arrows |

### 6.1 Event ordering & reconciliation

To handle EventSource auto-reconnect without state corruption:

1. Initial `GET /batches/{id}` returns the current state plus a `seq` indicating the last event absorbed into that snapshot.
2. Client subscribes to SSE.
3. Incoming events with `seq <= initial_seq` are dropped.
4. Events with larger `seq` apply via `queryClient.setQueryData`, monotonically.
5. On disconnect, `EventSource` auto-reconnects; the client resends `Last-Event-ID` (standard SSE), and the server replays from that point if the event is still in a small ring buffer; otherwise the client re-runs step 1.

Note: per §3.4 the server does not persist events across process restarts. If the server restarts, the ring buffer is empty and the client falls back to step 1.

### 6.2 Preserved contracts

`useBatch(id)` → `useBatchStream(id)` is a drop-in replacement. Return type identical. Consumers in `BatchDetail.tsx` / `SampleDetail.tsx` compile without changes other than the import swap.

---

## 7. Testing

### 7.1 Shared fixture `tests/fixtures/fake_chat.html`

Pure static HTML + inline JS. Loadable via `file://`. Behavior:

- `<textarea id="input">` — toggles `#send`'s `disabled` attribute.
- `<button id="send" disabled>` — on click, disables itself, appends a new `<div data-role="assistant">` under `#responses`, types out a canned reply character-by-character over ~600 ms, then re-enables `#send`. This produces both:
  - **dom_stable**: `#responses` last-child text stops changing for ≥ 1s after typing completes.
  - **send_button_reenable**: `#send` transitions disabled → enabled exactly at generation end.
- `<button id="new-chat">` — empties `#responses` (tests `new_session_action`).

### 7.2 Unit tests (default, mocked Playwright)

- `test_action_runner.py` — each of 6 actions translates to expected Playwright call; `$ENV_VAR` expansion works; missing env var raises `ValueError`.
- `test_complete_detector.py` — `dom_stable` returns after N consecutive identical text hashes; `send_button_reenable` returns on disabled→enabled transition; both respect `max_wait_sec`.
- `test_screenshot_store.py` — path format `NNN_<label>.png` with zero-padded auto-increment; non-`[a-z0-9_]` in `label` is slug-sanitized; directories auto-created.
- `test_web_executor_unit.py` — sample lifecycle with mocked Playwright; `new_session=True` triggers `new_session_action`; exception triggers `recovery_path` and retry; max attempt count honored.
- `test_event_bus.py` — pub/sub; multiple subscribers both receive; `seq` monotonic per batch; unsubscribe stops delivery.

### 7.3 Integration tests

- `test_web_executor_e2e.py` (`@pytest.mark.playwright`) — real Chromium + `fake_chat.html`. Cases: 1-prompt happy path, 3-prompt multi-turn, `new_session=True`, forced error (bad selector) → `recovery_path` → ultimate failure after retries.
- `test_sse_endpoint.py` — `httpx.AsyncClient` SSE subscription; bus publish visible to subscriber; subscriber exit doesn't hold bus refs.
- `test_screenshots_endpoint.py` — seeded PNGs in temp dir; list/download work; path traversal attempts (`../../etc/passwd`, unicode) return 400.

### 7.4 CI strategy

- `python3.11 -m pytest -q` runs everything (including `playwright` marked tests). Requires one-time `python3.11 -m playwright install chromium --with-deps`.
- `python3.11 -m pytest -q -m "not playwright"` runs fast subset; documented in CLAUDE.md "Common commands" for quick dev loops.
- `pyproject.toml` adds:
  ```toml
  [tool.pytest.ini_options]
  markers = ["playwright: requires real Chromium via `playwright install`"]
  ```

---

## 8. Dependencies & Install

**New Python deps:**

| Package | Version | Purpose |
|---|---|---|
| `playwright` | `>=1.46,<2.0` | Browser automation |
| `sse-starlette` | `>=2.1,<3.0` | SSE endpoint on FastAPI |

No new frontend dependencies. `EventSource` is a native browser API; AntD's existing `Modal` / `Table` / `Image` components cover the new UI blocks.

**Post-install (documented in README & CLAUDE.md):**

```bash
python3.11 -m playwright install chromium --with-deps
```

`--with-deps` installs system libs (libnss3 etc.) on Linux; no-op on macOS.

**New env var (optional):**

| Variable | Default | Purpose |
|---|---|---|
| `PLAYWRIGHT_BROWSERS_PATH` | unset | Customize browser cache location (useful in CI) |

**Settings impact:** none. `WebProfile` schema already exists in `profiles/schemas.py`; `ExecutorContext.verbose_logs` already exists.

---

## 9. Task Breakdown (hand-off to writing-plans)

~20 tasks across 4 phases, rough dependency graph:

```
Phase A (infra)
  1. Deps + docs (pyproject, README, CLAUDE.md)
  2. Sample.mode enum extend (backend + frontend types)
  3. Event bus + unit tests
  4. fake_chat.html fixture

Phase B (executor core)
  5. ActionRunner + unit tests
  6. CompleteDetector + unit tests
  7. ScreenshotStore + unit tests
  8. WebExecutor (mocked Playwright) + unit tests
  9. WebExecutor (real Playwright) integration test, @pytest.mark.playwright

Phase C (scheduler + API)
  10. Scheduler web concurrency downgrade + test
  11. Scheduler event bus publishes + integration test
  12. SSE endpoint + integration test
  13. Screenshots endpoints (list + download + guards) + integration test
  14. /tests/sync dispatch by platform + integration test (connectivity for web)

Phase D (frontend)
  15. Types + api/screenshots + useBatchStream hook + unit tests
  16. Mode dropdown + profile filter (BatchNew, Tests/Quick)
  17. Profile Edit connectivity enable + timeout override for web
  18. SampleDetail: ScreenshotStrip + ActionLogTable
  19. Swap useBatch → useBatchStream in BatchDetail consumer

Phase E (wrap)
  20. Final verification + browser smoke + CLAUDE.md completion + tag web-gui-executor-v0.3.0
```

Dependency edges:

```
1 → 2 → {3, 4, 5, 6, 7} → 8 → 9
                          ↓
                         10 → 11 → 12
                              ↓
                         {13, 14}          (parallel)
                              ↓
                         15 → {16, 17, 18} → 19 → 20
```

### 9.1 Size estimate

- Backend new code: ~1200 lines (executors ~500 + detector ~150 + action runner ~200 + bus ~100 + API ~150 + tests ~800).
- Frontend new code: ~400 lines.
- Fixture HTML: ~100 lines.
- Total: ~2500 lines (notably smaller than Plan 2's +6600 because profile schema already exists and no new pages).
- New test cases: ~25 (18 unit + 7 integration).

---

## 10. Acceptance Criteria

Plan 3 is done when:

1. `python3.11 -m pytest -q` passes (68 prior + ~25 new, ~93 total).
2. `python3.11 -m pytest -q -m "not playwright"` passes without Chromium installed.
3. `ruff check .` + `ruff format --check .` clean.
4. `cd web && pnpm test && pnpm lint && pnpm build` clean.
5. Profile Edit connectivity test works end-to-end for a `platform: web` profile against `fake_chat.html` (or a real target if the operator configures one).
6. A batch with 3 web samples and `concurrency=2` on an ephemeral profile completes with `done` status, 2 samples running in parallel at peak. Screenshots visible in SampleDetail.
7. BatchDetail page updates in real time via SSE (verified by disabling polling in devtools and seeing progress still move).
8. `useBatchStream` cleanly closes `EventSource` on unmount (no dangling connections in devtools Network panel).
9. CLAUDE.md reflects Plan 3 complete; tag `web-gui-executor-v0.3.0` pushed.

---

## 11. Hand-off to Plan 4 (Android Executor)

- The `Executor` abstract base already accommodates Android via the same contract. Plan 4 adds `AndroidExecutor` under `executors/android_executor.py`.
- The `CompleteDetector` module structure extends naturally: add `ui_tree_stable` and `pixel_stable` as additional strategies. Same interface.
- The `ScreenshotStore` module is shared: Android screenshots land in the same layout.
- The SSE event bus is platform-agnostic; Android events will reuse the same event kinds.
- Android will introduce a `DevicePool` (ADB device lock / acquire / release) that does not exist yet. This is Plan 4-specific.

---

## 12. Open questions (intentionally deferred)

- **Browser version pinning.** Playwright downloads whatever matches its version; if a target site breaks on a new Chromium revision, we have no mitigation today. Plan 5 can add `playwright install chromium@<version>` pinning.
- **Headed mode on CI.** If we ever add CI, real-Playwright tests must run headless (fake_chat.html works headless fine). No action needed until CI is added.
- **Long-running browser across batches.** Today each batch launches/tears down its own Browser. Cross-batch browser reuse would reduce cold-start but complicates lifecycle. Not pursued.
- **Rate limiting / politeness.** We don't throttle requests to target sites. If abuse becomes a concern, Plan 5 can add per-profile rate limits.
