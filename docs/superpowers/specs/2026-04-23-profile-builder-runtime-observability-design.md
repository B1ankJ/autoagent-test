# Profile Builder Runtime Observability Design

## Goal

Make the Android Profile Builder observable while it runs so an operator can understand what the
system is doing without digging through backend logs or artifact directories.

This scope covers:

- capture progress visibility for `idle`, `editing`, and `response`
- connectivity-test progress visibility
- key screenshot previews during the builder flow
- automatic page refresh while the builder is running

This scope does not cover:

- replacing polling with SSE
- full action-by-action replay timelines
- video recording
- OCR/text annotations over screenshots

## User Outcome

The operator should be able to open the Builder page and see:

- which builder step is running now
- which steps are pending, complete, or failed
- the latest key screenshot for the current step
- the most recent few screenshots from earlier steps
- whether the connectivity test succeeded, and the final response or error summary

The operator should not need to inspect `executor.log`, `connectivity_result.json`, or raw capture
files during normal use.

## Recommended Approach

### Option A: Poll a server-side runtime snapshot

Add a builder runtime snapshot model persisted as `runtime.json`, expose it through a dedicated API,
and have the Builder page poll it every 1 to 2 seconds while work is active.

Pros:

- fits the existing backend architecture
- easy to debug because the runtime state is persisted on disk
- resilient to page reloads
- lower implementation risk than adding a new event stream

Cons:

- not truly real-time
- adds periodic requests while a builder session is open

### Option B: Add builder-specific SSE events

Push builder events over a new stream endpoint and update the Builder page reactively.

Pros:

- best real-time UX
- avoids polling

Cons:

- significantly more backend complexity
- new event model to maintain
- overkill for a mostly single-operator workflow

### Option C: Infer state from raw artifacts only

Have the frontend inspect which files exist and derive builder status without a dedicated runtime
model.

Pros:

- smallest backend change

Cons:

- brittle and hard to evolve
- poor separation of concerns
- makes the frontend responsible for workflow semantics

### Recommendation

Use Option A.

It gives the operator the visibility they need while keeping the backend changes incremental and
testable. It also creates a clean path to SSE later if needed.

## Backend Design

### New Runtime Artifact

Each builder session gains a persisted runtime snapshot:

`data/profile_builder/<session_id>/runtime.json`

This file is the single source of truth for the Builder page runtime state.

### New API

Add:

`GET /api/v1/profile-builder/sessions/{session_id}/runtime`

Response shape:

```json
{
  "session_id": "pb_123",
  "session_status": "draft",
  "current_step": "capture_editing",
  "step_state": "running",
  "last_error": null,
  "captures": [
    {
      "step": "idle",
      "status": "done",
      "screenshot": "capture_idle.png",
      "updated_at": "2026-04-23T18:00:00Z"
    },
    {
      "step": "editing",
      "status": "running",
      "screenshot": "capture_editing.png",
      "updated_at": "2026-04-23T18:00:05Z"
    },
    {
      "step": "response",
      "status": "pending",
      "screenshot": null,
      "updated_at": null
    }
  ],
  "connectivity": {
    "status": "idle",
    "result_status": null,
    "result_summary": null,
    "screens": []
  },
  "recent_screens": [
    {
      "step": "editing",
      "label": "capture_editing",
      "path": "capture_editing.png",
      "taken_at": "2026-04-23T18:00:05Z"
    }
  ]
}
```

### Backend State Model

Track these top-level fields:

- `session_status`: `draft | ready | validating | validated | failed`
- `current_step`: builder-specific step key
- `step_state`: `idle | running | done | failed`
- `last_error`: nullable string

Track capture-specific status for:

- `idle`
- `editing`
- `response`

Each capture record stores:

- step
- status: `pending | running | done | failed`
- screenshot filename or `null`
- update timestamp

Track connectivity-specific status in a dedicated object so validate progress does not get flattened
into generic session state.

### Runtime Update Rules

Update `runtime.json` at these points:

- before each capture begins: mark the step `running`
- after each capture completes: mark the step `done`, attach its screenshot
- if capture fails: mark the step `failed`, set `last_error`
- before draft generation: set `current_step=generate_draft`, `step_state=running`
- after draft generation: set `step_state=done`, keep `session_status=ready`
- before review application: set `current_step=apply_review`, `step_state=running`
- after review application: set `step_state=done`
- before validation: set `session_status=validating`, `current_step=connectivity`,
  `step_state=running`
- during validation: refresh recent screenshots and connectivity status
- after validation success: set `session_status=validated`, `step_state=done`
- after validation failure: set `session_status=ready` or `failed` depending on result shape, and
  populate `last_error`

All writes should be persisted so page reloads are safe.

## Key Screenshot Strategy

### Capture Steps

Keep one key screenshot per capture step:

- `capture_idle.png`
- `capture_editing.png`
- `capture_response.png`

These are the stable visual artifacts for the builder baseline.

### Draft Generation

Do not introduce draft-generation screenshots in the MVP.

That phase is better represented by:

- `candidates.json`
- `review_items.json`
- `draft_profile.yaml`

### Review Application

Do not introduce review-specific screenshots in the MVP.

Review is primarily a draft mutation, not a UI exploration phase.

### Connectivity Validation

Capture only a small, high-signal set of frames:

- `validate_before_input.png`
- `validate_after_input.png`
- `validate_after_send.png`
- `validate_after_result.png`
- `validate_on_error.png` when needed

These correspond to the exact moments the operator most needs to inspect:

- starting page state
- whether prompt entry actually succeeded
- whether sending succeeded
- what the final visible state looked like

### Recent Screenshot History

The runtime snapshot should expose:

- the current step's latest key screenshot as the main preview
- the most recent 3 screenshots across prior steps as a small history strip

This gives the operator both current-state visibility and immediate short-term history without
turning the page into a noisy timeline.

## Frontend Design

### Layout

Enhance the Builder page with four visible regions:

1. Top status bar
2. Step timeline
3. Screenshot preview panel
4. Existing review/YAML/result sections

### Top Status Bar

Show:

- overall builder status
- current running step
- latest update timestamp
- error summary when present

This section should be visible without scrolling.

### Step Timeline

Show ordered steps:

- Capture Idle
- Capture Editing
- Capture Response
- Generate Draft
- Apply Review
- Run Connectivity Test

Each step renders one of:

- pending
- running
- done
- failed

Current step should be visually highlighted.

### Screenshot Preview Panel

Show:

- one large preview for the current step
- a small strip of the recent few screenshots

Each preview includes:

- step name
- screenshot label
- capture time

The panel auto-refreshes as runtime data changes.

### Existing Review and Draft Sections

Keep the current sections:

- Review Items
- Draft YAML
- Connectivity Result

These remain below the observability surfaces and continue to support the builder workflow.

## Polling Behavior

### Refresh Strategy

Use automatic polling rather than manual refresh.

Suggested intervals:

- when runtime is active (`running`, `validating`): every 1500 ms
- when idle or complete: every 4000 ms

Polling should start once a builder session exists.

### Stop Conditions

Do not fully stop polling after completion. Instead, reduce frequency so the page remains accurate
if the user applies review actions or reruns validation.

## Storage and Naming

### Stable Artifacts

Keep using:

- `capture_idle.xml`
- `capture_idle.png`
- `capture_editing.xml`
- `capture_editing.png`
- `capture_response.xml`
- `capture_response.png`
- `candidates.json`
- `review_items.json`
- `draft_profile.yaml`
- `connectivity_result.json`

### Runtime-Specific Artifacts

Add:

- `runtime.json`
- `validate_before_input.png`
- `validate_after_input.png`
- `validate_after_send.png`
- `validate_after_result.png`
- `validate_on_error.png`

This naming scheme should be deterministic and easy to display without frontend inference logic.

## Error Handling

When a step fails:

- persist failure state into `runtime.json`
- preserve the most recent screenshot if available
- store a short operator-facing `last_error`
- do not require the operator to inspect backend logs for the first failure read

The Builder page should surface failure in the top status bar and in the step timeline.

## Testing Strategy

### Backend

Add focused tests for:

- runtime snapshot persistence
- runtime API response shape
- capture updates reflected in runtime state
- validate screenshot registration reflected in runtime state
- failure states updating `last_error`

### Frontend

Add focused tests for:

- runtime polling hook behavior
- step status rendering
- screenshot preview rendering
- runtime updates after mock polling responses change

### Manual Smoke

Run a browser smoke covering:

- create session
- perform three captures
- generate draft
- apply review item
- run connectivity
- watch status and screenshot panel update during the flow

## MVP Boundary

Implement now:

- runtime snapshot persistence
- runtime GET endpoint
- capture and validate runtime updates
- key validation screenshots
- Builder status/timeline/screenshot panel
- automatic polling

Defer:

- SSE event stream
- full replay timeline
- screenshot annotation overlays
- richer screenshot gallery/history controls
- video capture

## Risks

### Risk: runtime and session state diverge

Mitigation:

- update runtime and session artifacts in the same workflow boundaries
- persist runtime on every state transition

### Risk: screenshot preview paths become hard to resolve

Mitigation:

- keep filenames stable and relative to `artifact_dir`
- have runtime payload carry explicit filenames instead of making the frontend infer them

### Risk: connectivity screenshots add too much storage

Mitigation:

- store only the 4 to 5 key frames, not full action-by-action screenshots

## Success Criteria

The feature is successful when:

- the operator can see builder progress without opening logs
- the current step and last key screenshot update automatically
- the connectivity phase visibly shows input/send/result progression
- builder failures are understandable from the page alone in most cases
