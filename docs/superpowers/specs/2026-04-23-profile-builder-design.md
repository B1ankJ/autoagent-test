# Profile Builder Design

Date: 2026-04-23

## Goal

Reduce the manual cost of creating and maintaining GUI profiles, especially Android app profiles, by introducing a human-in-the-loop profile builder.

The target outcome is:

- humans spend more time once on profile setup
- batch execution spends less human time later
- profile creation moves from raw YAML editing to guided evidence collection and targeted confirmation

This design focuses on an MVP that helps generate and validate profiles for Android GUI testing first, while keeping the architecture extensible to PC web GUI profiles later.

## Problem

Current profile creation is expensive because users must manually:

- inspect the target page state
- pull and interpret UI XML
- infer package, activity, input locator, send locator, response extraction strategy, and completion strategy
- run repeated connectivity tests
- adjust YAML by trial and error

This works, but the cost is too high for broad profile coverage.

The system should shift effort from low-level YAML authoring to:

- evidence collection
- candidate generation
- limited human review on uncertain fields
- immediate connectivity feedback

## Product Principle

The system is not trying to be fully automatic.

The design assumes:

- machine handles collection, parsing, candidate generation, and draft authoring
- human intervenes only when uncertainty is high
- once a profile passes connectivity, later batch work should require much less manual effort

This is a human-in-the-loop builder, not a black-box generator.

## Scope

### MVP In Scope

- Android profile draft generation
- guided capture of 2 to 3 app states
- rule-based candidate extraction from XML and screenshots
- optional LLM-assisted draft generation
- explicit human confirmation for low-confidence fields
- one-click connectivity validation from the generated draft
- artifact persistence for debugging and later refinement

### Out of Scope for MVP

- full no-human profile generation
- autonomous profile repair across arbitrary apps
- screen recording and gesture learning
- batch-time automatic profile mutation
- PC web support beyond architecture placeholders

## User Experience

### Mode

The MVP uses a guided flow with assistant behavior:

1. user selects a device
2. user selects `Build Profile`
3. system guides the user to capture three states
4. system generates a draft profile and review items
5. user confirms only uncertain fields
6. system runs connectivity test immediately
7. user saves the profile if connectivity succeeds

This combines a guided workflow with selective human confirmation.

### Guided Capture States

The builder asks the user to prepare these states:

1. Idle conversation state
   - target chat page visible
   - no input active yet

2. Editing state
   - input box activated
   - send controls visible in editing layout

3. Response state
   - one short test message sent
   - assistant response visible and settled

The system captures for each state:

- current package and activity
- `uiautomator dump` XML
- screenshot
- optional focused window metadata

### Human Review

The system only asks the human to review fields with low confidence or multiple plausible candidates.

MVP review targets:

- input locator
- send button locator
- response region strategy
- completion strategy when multiple plausible options exist

The user should not need to manually edit YAML first.

## High-Level Architecture

The builder has five stages.

### 1. Capture

Collect state artifacts from the selected device.

Artifacts per step:

- `window.xml`
- `window.png`
- `dumpsys_window.txt`
- derived metadata such as package and activity

### 2. Candidate Extraction

Parse the raw XML into a reduced structured representation.

The extractor identifies candidate nodes for:

- input controls
- send controls
- response containers
- bubble text nodes
- likely noise nodes such as time labels, navigation controls, and tool buttons

It also computes state differences:

- nodes that appear only in editing state
- nodes that move between idle and editing state
- nodes that appear after response

### 3. Draft Generation

Build a draft profile from structured candidates.

This stage has two layers:

- deterministic rule engine
- optional LLM reasoning layer

The rule layer narrows the search space first. The LLM does not receive the full raw XML as its primary input. It receives:

- filtered candidates
- state summaries
- selected screenshot observations
- output schema requirements

### 4. Review Resolution

The draft includes confidence per field.

Fields above threshold are accepted automatically.

Fields below threshold are converted into `review_items` for UI confirmation.

### 5. Validation

The system immediately runs a connectivity test using the drafted profile.

Outputs:

- pass or fail
- sample logs
- generated artifacts
- suggested next adjustments if failed

## Generation Strategy

### Rule Layer

The rule layer is responsible for first-pass narrowing.

Examples:

- `package` from foreground window metadata
- `activity` from current focused app
- input candidates from `EditText`, editable nodes, or nodes whose activation produces editing-state change
- send candidates from rightmost clickable controls near the input area in editing state
- response extraction candidates from large scrolling containers containing repeated text nodes
- noise filtering for clocks, tab labels, tool chips, and footer disclaimers

The rule layer also records why each candidate was chosen.

### LLM Layer

The LLM layer is optional and configurable.

It receives:

- compact structured candidate JSON
- selected screenshot summaries or OCR snippets
- prompt templates
- strict output schema

It returns:

- draft profile YAML or equivalent structured object
- field-level confidence
- rationale
- explicit uncertainty markers

The system must never depend on unconstrained free-form LLM output.

## LLM Configuration

The builder should support configurable LLM backend settings:

- `base_url`
- `model`
- `api_key`
- optional timeout
- optional temperature

The LLM integration is only one stage in the pipeline. If no LLM is configured, the system should still produce a rule-only draft and review items.

## Data Contracts

### Draft Output

The builder produces:

- `draft_profile.yaml`
- `candidates.json`
- `review_items.json`
- capture artifacts under a build session directory

### `review_items.json`

Each review item should include:

- field name
- reason for uncertainty
- recommended option
- alternative candidates
- evidence references such as screenshot path and XML node snippet

This allows the UI to present targeted decisions rather than exposing raw YAML immediately.

## UI Flow

### Page Entry

Add a `Build Profile` action from the Profiles area or Device area.

### Builder Steps

1. Select device
2. Select platform type
3. Guided capture prompts
4. Review uncertain fields
5. Preview generated YAML
6. Run connectivity test
7. Save profile

### Failure Handling

If connectivity fails, the builder should show:

- failing stage
- generated artifacts
- the exact field likely responsible
- quick edit path for the failing field

The user should be able to adjust and rerun without restarting the whole build flow.

## Storage Layout

Each build session should persist its artifacts.

Proposed directory shape:

`data/profile_builder/<session_id>/`

Suggested contents:

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

## Success Criteria

The MVP is successful if:

- most profile fields are auto-filled
- the user only needs a small number of confirmation decisions
- first generated draft can usually be made connectivity-valid within 1 to 2 iterations
- saved profiles reduce later batch-time human involvement

Success is not defined as full automation.

## Risks

### 1. Over-reliance on raw XML

Some apps expose incomplete or unstable UI trees.

Mitigation:

- combine XML with screenshots
- allow human review
- keep OCR fallback available

### 2. LLM drift or hallucination

Mitigation:

- rule-first narrowing
- structured output only
- confidence and review gating

### 3. UI state instability

Mitigation:

- guided capture
- multiple named states
- capture artifacts persisted for replay and debugging

### 4. Review fatigue

Mitigation:

- only ask humans about low-confidence fields
- always present a recommended option first

## MVP Recommendation

Implement the following sequence:

1. Guided capture for three Android states
2. Rule-based candidate extraction
3. Draft profile generation without LLM dependency
4. Review item UI for uncertain fields
5. Connectivity test integration
6. Optional LLM enhancement behind configuration

This yields a useful builder quickly while keeping the architecture ready for more advanced automation later.

## Open Follow-Ups

- whether to expose profile builder from Profiles page, Devices page, or both
- whether review UI should allow direct YAML editing in MVP or only structured confirmations
- whether response-state capture should be fully manual in MVP or use a guided sample send
- whether to store successful builder sessions for future training or heuristic tuning
