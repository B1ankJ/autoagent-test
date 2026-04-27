# Builder New Session Recommendation Status Design

Date: 2026-04-27
Branch: `plan4-android-executor`
Status: Proposed

## Goal

Improve the `Build Profile -> New Session Action` flow so the UI can clearly distinguish:

- `VLM` is not configured, so no automatic recommendation is possible
- a recommendation request was attempted but failed
- a recommendation was produced and can be accepted

The current experience is too ambiguous:

- the `接受推荐` button appears disabled without explaining why
- users often need to click `重新点选` just to keep moving
- missing `VLM` configuration and actual recommendation failures look the same from the UI

This work must keep the existing guided new-session authoring flow intact:

- `tap_xy` remains the only supported action type
- manual point selection remains available as a fallback
- `new_session_action` serialization rules do not change

## Non-Goals

- No change to `tap_xy` serialization
- No change to `new_session_action` ordering semantics
- No new support for `click_locator`
- No automatic execution of new-session taps during Builder capture
- No broader redesign of the Builder page layout
- No change to the existing profile builder review system outside the new-session panel

## Problem

The current new-session panel has two user-facing issues:

1. The `接受推荐` button stays disabled or appears inactive without telling the user whether the reason is:
   - missing `VLM`
   - recommendation request failure
   - a step that simply has not been captured yet
2. The panel currently relies on a single `recommended_tap.status` shape, which is too coarse to explain what happened when recommendation is unavailable.

As a result, users must guess whether they should:

- reconfigure `VLM`
- retry capture
- or switch to manual point selection

## Recommended Approach

Promote recommendation availability into an explicit state machine on each new-session step:

- `idle`
- `ready`
- `unavailable`
- `failed`

Add one companion error field:

- `recommendation_error`

This gives the backend a stable place to encode why recommendation is not available, and the frontend a stable place to render the appropriate call to action.

Recommended high-level behavior:

- `idle`: step has not been captured yet, so there is nothing to recommend
- `ready`: recommendation exists and `接受推荐` is enabled
- `unavailable`: `VLM` is not configured, so only manual selection is possible
- `failed`: recommendation was attempted but failed; manual selection still works

## Alternatives Considered

### 1. Keep the current single status and only change the button label

Pros:

- smallest change
- no backend schema impact

Cons:

- does not solve the real ambiguity
- still hides the difference between missing `VLM` and an actual request failure

### 2. Recommended: explicit availability state + error reason

Pros:

- communicates the true reason clearly
- keeps manual fallback available
- scales to more precise error messages later

Cons:

- requires both backend and frontend changes

### 3. Add a generic failure string only

Pros:

- easier than a full state machine

Cons:

- still awkward in the UI
- harder to determine when the button should be enabled versus disabled

## Data Model

Each new-session step should expose:

- `recommended_tap.status`: one of `idle`, `ready`, `unavailable`, `failed`
- `recommended_tap.point`: present only when `status === "ready"`
- `recommended_tap.reason`: present only when `status === "ready"`
- `recommendation_error`: a stable reason code or message for non-ready states

Suggested `recommendation_error` values:

- `vlm_unavailable`
- `connect_error`
- `auth_error`
- `model_error`
- `response_shape_error`

The backend should not infer these from the frontend. It should set them when the step is captured.

## Backend Behavior

The `POST /profile-builder/sessions/{id}/new-session/step/{step_index}/capture` flow should:

1. capture screenshot and XML as today
2. attempt recommendation only when `VLM` is configured
3. set the new-step state to `ready` on success
4. set the new-step state to `unavailable` when no `VLM` config exists
5. set the new-step state to `failed` when the recommendation request fails

The backend must preserve the existing manual fallback:

- the step can still be manually confirmed regardless of recommendation state
- the final `new_session_action` is still built from confirmed taps only

The backend should return enough state for the UI to render a clear message without re-deriving the reason from unrelated fields.

## Frontend Behavior

The `New Session Action` card should render each step as follows:

### `idle`
- show a neutral message that capture has not been run yet
- keep `接受推荐` disabled
- keep `重新点选` available only after capture, if the screenshot exists

### `ready`
- show the recommended tap point and short reason
- enable `接受推荐`
- keep `重新点选` available

### `unavailable`
- show a warning such as `当前未配置 VLM，仅支持人工点选`
- keep `接受推荐` disabled
- keep `重新点选` available when a screenshot exists

### `failed`
- show a warning such as `推荐请求失败：认证失败`
- keep `接受推荐` disabled
- keep `重新点选` available when a screenshot exists

The current helper button behavior should remain:

- `接受推荐` only works when a recommendation is actually ready
- manual point selection remains the fallback path for all non-ready states

## UX Constraints

- The user should never have to guess why `接受推荐` is disabled
- The user should not need to select `重新点选` just to discover whether recommendation is unavailable
- The presence of a `VLM` configuration should be visible in the panel state, not hidden behind a disabled button
- Manual selection should remain one click away whenever a screenshot exists

## Testing

Update frontend tests to cover:

- `VLM` missing shows an explicit unavailable message
- recommendation failure shows a distinct failure message
- `ready` enables `接受推荐`
- manual point selection still works when recommendation is unavailable

Update backend integration tests to cover:

- missing `VLM` produces `unavailable`
- recommendation provider failure produces `failed`
- successful recommendation produces `ready`
- manual confirmation still serializes into `new_session_action`

## Out of Scope

This change does not include:

- changing how `new_session_action` is serialized
- changing how many steps the user can configure
- redesigning the new-session capture flow itself
- changing the existing profile-builder review item semantics

## Acceptance Criteria

This change is complete when:

1. the new-session panel explains why recommendation is disabled
2. the UI distinguishes `VLM` unavailable from recommendation failure
3. users can still complete the flow by manual selection in both cases
4. the backend returns stable step-state information for the UI to render
5. automated tests cover the new states and messages
