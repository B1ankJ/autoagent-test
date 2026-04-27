# Profile Builder Candidate Expansion Design

## Context

The Android Profile Builder now preserves rich `latest_bubble_match` review candidates, but the other review-driven fields still apply aggressive filtering:

- `input_locator` only keeps `EditText` nodes and idle placeholder text nodes
- `input_focus_action` is derived from the narrow `input_locator` set plus a single idle placeholder
- `send_action` only keeps bottom-right clickable controls that survive strict size and position heuristics

This causes frequent review failures where the correct runtime choice never appears in the candidate list.

Separately, response extraction has moved toward structural anchors. In many generated YAMLs the saved `latest_bubble_match` value is effectively a stable response anchor such as a recycler view resource id. Some apps also render one assistant reply as multiple `TextView` fragments within the same message block, so treating a reply as a single `TextView` is no longer sufficient.

## Goals

- Expand `input_focus_action`, `input_locator`, and `send_action` review candidate pools so the builder preserves raw plausible controls instead of discarding them early.
- Keep review user-driven: preserve all plausible candidates and rely on ranking rather than destructive filtering.
- Reduce unnecessary `latest_bubble_match` review prompts when response anchoring is structurally stable.
- Support assistant replies that are rendered as multiple `TextView` fragments within one visible message block.

## Non-Goals

- Renaming the YAML field `latest_bubble_match`
- Redesigning the Builder UI flow
- Adding OCR-based response extraction in this iteration

## Design

### 1. Input candidate expansion

`input_locator` candidate generation will expand from the current `EditText + placeholder` rule set to a broader input-region model.

Candidate sources:

- direct editable nodes such as `android.widget.EditText`
- focusable or clickable parent/ancestor containers around editable nodes
- idle and editing placeholder text nodes near the composer region
- clickable/focusable siblings inside the same bottom composer cluster
- stable resource-id or class-based locators when available, with bounds retained as review evidence

The builder will keep all plausible candidates, deduplicate them by normalized locator, and rank them rather than trimming them to a tiny set.

### 2. Input focus action expansion

`input_focus_action` will no longer be assembled from only one placeholder plus the chosen input locator set. Instead, it will be derived from the full expanded input-region candidates.

For every plausible focus target the builder will preserve both:

- `tap_xy` based on evidence bounds
- `click_locator` when a locator exists

This keeps proxy entry regions, wrappers, and direct input controls available for manual review.

### 3. Send action expansion

`send_action` will move from a strict "bottom-right clickable control" heuristic to a broader composer-action search.

Candidate sources:

- clickable nodes in the composer region
- icon wrappers and clickable ancestors near the right edge of the composer
- small clickable controls previously dropped by width/height thresholds
- send-adjacent controls found in the same composer cluster, still preserving evidence so the user can reject false positives

The builder will continue ranking likely send controls first, but it will no longer discard plausible controls purely because they are small, wrapped, or slightly outside the current threshold window.

### 4. Response block semantics

The YAML field name `latest_bubble_match` stays unchanged for compatibility, but its operational meaning shifts from "single latest text node" to "latest response block rule".

Builder behavior:

- keep rich review evidence for response candidates
- detect when a candidate block contains multiple `TextView` fragments
- store the structural container anchor plus a resolved block-matching rule

Runtime behavior:

- locate the response container structurally
- group nearby `TextView` fragments into a single response block when they share layout and parent/container context
- aggregate block text in visual order
- choose the latest valid response block instead of the last individual `TextView`

### 5. Review gating for latest_bubble_match

`latest_bubble_match` review should become conditional rather than routine.

Review is required only when:

- multiple response containers remain similarly plausible
- multiple response blocks inside the same container are similarly plausible
- block aggregation is ambiguous or confidence is low

Review is skipped when:

- the container anchor is structurally stable
- the latest response block is unambiguous after block grouping

## Testing

- add unit tests for expanded `input_locator`, `input_focus_action`, and `send_action` candidate generation
- add a unit test proving multi-`TextView` replies are grouped into one response block
- keep existing response extraction tests passing
- update endpoint/integration tests only where review item counts or candidate structures intentionally change

## Risks

- broader candidate preservation may produce noisier review lists; ranking and deduplication must keep them usable
- over-aggressive block grouping could merge unrelated texts such as helper chips or footers; grouping must stay inside the chosen response container and use layout proximity rules
- apps rendered in WebView may expose limited semantics, so the implementation must degrade gracefully to evidence-rich review rather than pretending confidence

## Rollout

1. Add failing tests for candidate expansion and multi-fragment response grouping.
2. Implement expanded candidate collection and deduplication.
3. Implement response block grouping and conditional review gating.
4. Update builder docs to match the new semantics.
