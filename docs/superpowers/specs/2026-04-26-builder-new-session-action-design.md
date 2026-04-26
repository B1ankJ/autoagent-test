# Builder New Session Action Design

Date: 2026-04-26
Branch: `plan4-android-executor`
Status: Proposed

## Goal

Add a dedicated Builder flow for generating `new_session_action` during profile authoring.

The flow must support:

- apps that do not need a new-session action
- apps that require one or more taps before a fresh conversation is ready
- user-confirmed `tap_xy` output only
- optional AI recommendation for each step, with manual override before the action is written into draft YAML

The flow must not change runtime semantics:

- `new_session_action` remains a profile capability
- runtime execution still depends on `sample.new_session=true`
- this design only changes how Builder helps produce the action sequence

## Non-Goals

- No support for `click_locator`
- No automatic execution of the recommended taps during Builder capture
- No attempt to infer `new_session_action` from only the existing `idle/editing` captures
- No change to executor behavior, API batch semantics, or test runner defaults

## Problem

Current Builder can generate or review fields such as `input_locator`, `send_action`, and `response_extraction`, but `new_session_action` is effectively absent from the authoring flow.

That gap is structural:

- `new_session_action` is not a static field like a locator
- it often depends on a short navigation flow
- some apps require zero taps
- some require one tap
- some require multiple taps across different transient UI states

Trying to infer this from the existing two static Builder captures is not reliable enough.

## User Model

The user knows whether the target app needs a fresh-conversation flow and approximately how many taps are needed.

The Builder should therefore ask the user for two things up front:

1. whether the profile should carry a `new_session_action`
2. how many tap steps are needed if it should

Once those are known, Builder can guide the user through collecting one screenshot/XML pair for each step in the state immediately before the tap should happen.

## Recommended Approach

Use a dedicated multi-step Builder subflow:

1. User selects whether to configure `new_session_action`
2. User selects the number of steps
3. Builder captures one "before tap" screen per step
4. For each captured step, Builder produces one recommended `tap_xy`
5. User accepts or overrides the recommendation
6. Confirmed taps are serialized into `new_session_action`
7. Draft YAML includes the generated action sequence

This is the recommended approach because it matches the real shape of the problem:

- `new_session_action` is a sequence, not a single field
- the user can reliably position the app before each tap
- AI can help, but user confirmation remains the safety barrier

## Alternatives Considered

### 1. Manual-only point selection

Capture the screenshot for each step and require the user to click the exact tap point with no recommendation.

Pros:

- lowest implementation risk
- fully deterministic

Cons:

- weak Builder ergonomics
- gives up most of the value of assisted authoring

### 2. Pure AI sequence generation

Capture all step screens, then ask AI to generate the full tap sequence without per-step user confirmation.

Pros:

- lowest user effort

Cons:

- too brittle for first release
- one wrong step makes the rest of the sequence untrustworthy
- hard to debug and explain

### 3. Recommended: AI recommendation plus manual confirmation

Generate a recommended tap point for each step, but require the user to accept or override it before it becomes part of the draft.

Pros:

- balanced speed and reliability
- keeps AI assistance while preserving a human safety gate
- easy to explain in UI

Cons:

- more front-end interaction than pure automation

## UI Design

### Session Setup

Add a new control group in Builder:

- `New Session Strategy`
  - `不配置`
  - `配置多步新开对话`

If the user chooses `配置多步新开对话`, show:

- `Step Count`
  - integer selector, initial range `1..3`
  - default `1`

This field is intentionally small in scope for v1. The user must state the expected number of taps instead of asking Builder to discover the length of the flow.

### New Session Capture Panel

When strategy is enabled, show a dedicated panel below the normal capture steps.

For each step `N`:

- title: `New Session Step N`
- instruction: "请把手机停留在本次点击前的界面，然后点击 Capture。"
- `Capture` button
- preview area
- recommended point status
- actions:
  - `接受推荐`
  - `重新点选`
  - `清除本步`

The user interaction per step is:

1. position the phone on the correct pre-tap screen
2. click `Capture`
3. wait for Builder to render the screenshot and recommended tap point
4. either accept the point or click on the image to override it

Each step remains unresolved until it has one confirmed `(x, y)` pair.

### Review and Draft Integration

Do not mix these steps into the existing generic `Review Items` list.

Instead, show a dedicated card:

- `New Session Actions`

That card lists:

- configured step count
- per-step status:
  - `待确认`
  - `已确认`
  - `已人工覆盖`
- the final generated sequence in compact form

The main `Draft YAML` display updates as soon as a step is confirmed or overridden.

## Data Model

Builder draft state needs a separate structure for this flow.

Suggested logical shape:

```json
{
  "new_session_strategy": "disabled" | "guided_tap_sequence",
  "new_session_steps": [
    {
      "step_index": 0,
      "capture": {
        "xml_artifact": "new_session_step_1.xml",
        "screenshot_artifact": "new_session_step_1.png"
      },
      "recommended_tap": {
        "x": 123,
        "y": 456,
        "reason": "top-right plus button"
      },
      "confirmed_tap": {
        "x": 123,
        "y": 456
      },
      "source": "recommended" | "manual"
    }
  ]
}
```

The final draft serialization remains:

```yaml
new_session_action:
  - action: tap_xy
    x: 123
    y: 456
  - action: tap_xy
    x: 888
    y: 210
```

If strategy is disabled, serialize:

```yaml
new_session_action: []
```

## AI Recommendation Strategy

The recommendation unit is one capture at a time.

Input per step:

- screenshot taken immediately before the desired tap
- corresponding XML
- step index
- total step count
- short instruction that the model must identify the most likely UI target that advances toward a fresh conversation

Output per step:

- exactly one `(x, y)` tap point
- short explanation string for UI display

The model is not allowed to emit:

- multiple candidate points
- a locator
- a longer action script

The reason for this constraint is to keep the Builder interaction simple and keep the confirmed output format stable.

## Why Step-by-Step Instead of Whole-Sequence Inference

Whole-sequence inference would require the model to imagine future UI states it cannot see yet.

Step-by-step recommendation is stronger because:

- each step has grounded evidence
- the user controls the pre-tap state
- errors are localized to one step
- overrides remain easy

This also keeps the debugging surface small: if step 2 is wrong, only step 2 needs to be recaptured or corrected.

## Builder State Rules

### Draft Gating

If `New Session Strategy = 不配置`:

- no additional gating applies

If `New Session Strategy = 配置多步新开对话`:

- every declared step must have a confirmed tap before the new-session sequence is treated as complete

This should not block normal draft generation for unrelated fields, but it should block claiming that `new_session_action` is ready.

### Connectivity Test

The Builder connectivity test should remain callable without automatically running the new-session flow during authoring.

Reason:

- the Builder goal here is authoring the sequence, not proving it live on-device during capture
- runtime validation of `new_session_action` belongs to explicit execution flows where `sample.new_session=true`

Optionally, the UI may later add a dedicated `Test New Session Flow` button, but that is out of scope for this design.

## Runtime Semantics

This design assumes the runtime contract already established on the branch:

- `sample.new_session=false` by default
- `new_session_action` runs only when `sample.new_session=true`

Builder therefore only produces the profile-side capability. It does not change when that capability is used.

## Error Handling

### Capture failure

If a step capture fails:

- keep the step unresolved
- preserve earlier confirmed steps
- show inline retry action

### AI recommendation failure

If AI recommendation fails for a captured step:

- still show the screenshot
- mark the step as `需人工点选`
- allow the user to click directly on the image and continue

This fallback is required so the feature remains useful even without model availability.

### User changes step count mid-flow

If the user reduces step count:

- truncate higher-index steps after confirmation dialog

If the user increases step count:

- append unresolved empty steps

Changing step count invalidates only the added or removed step range. Existing earlier confirmed steps remain.

## Testing Strategy

### Frontend

- strategy toggle visibility and defaults
- dynamic step count rendering
- step status transitions
- accepting recommended tap
- manual override on image click
- truncation behavior when step count shrinks
- draft YAML updates after confirmation

### Backend

- per-step artifact persistence
- step recommendation request/response validation
- serialization to `new_session_action`
- fallback behavior when recommendation is unavailable

### Manual Smoke

Run at least these cases:

1. app with no new-session flow
2. app with one-tap new-session flow
3. app with two-step flow such as `plus -> new chat`
4. step recommendation failure followed by manual override

## Implementation Boundaries

This should be built in phases:

1. UI scaffolding for strategy and step count
2. per-step capture persistence
3. AI recommendation for one step
4. manual override on image click
5. draft YAML integration
6. optional targeted validation flow later

This sequencing keeps the first usable slice small and prevents the feature from depending on automatic end-to-end execution too early.

## Open Decisions Closed in This Spec

These decisions are intentionally fixed to remove ambiguity:

- output action type is `tap_xy` only
- captures are taken before each tap
- the user explicitly states the number of steps
- AI gives one recommended point per step
- user confirmation remains mandatory before a step is finalized
- `new_session_action` stays outside generic `Review Items`

## Recommendation

Proceed with the dedicated guided multi-step tap-sequence flow.

It is the cleanest way to represent `new_session_action` in Builder without weakening runtime safety or overloading the existing draft-review system.
