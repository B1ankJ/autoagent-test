# Builder Review Layout Design

## Goal

Improve the `Build Profile` page when `Review Items` are numerous and evidence screenshots are large, without changing backend contracts, review semantics, or runtime behavior.

The current pain points are:

- The left `Review Items` column becomes very tall, forcing repeated page scrolling just to find the next unresolved item.
- The right `Key Screens` card introduces a second scroll container via card-level `overflowY: auto`, so users must manage both page scroll and preview scroll.
- The current layout does not keep a strong notion of "active review item", so users have to manually correlate the left item with the right screenshot.

This work is **frontend-only**. It must not modify:

- Builder API requests or responses
- Review item generation logic
- Review apply semantics
- Connectivity test behavior
- Draft generation behavior

## Recommended Approach

Keep the existing two-column desktop layout, but convert it from two independent long panels into a synchronized review workspace:

- The left column remains the primary review list.
- The right column becomes a single active evidence panel for the currently selected review item.
- The page uses one main browser scroll instead of nested scrolling inside the screenshot card.

This preserves the mental model of the current page while removing the worst usability issues.

## Layout Changes

### Left Column

`Review Items` becomes a compact working list.

Each review item should default to a summary row or compact alert showing:

- field name
- reason
- status badge:
  - unresolved
  - applied
  - smart preselected

Each item can still be expanded to show the existing controls:

- `Apply Recommended`
- `Apply Alternative N`
- `查看推荐定位`
- `查看全部证据`

Only the currently selected item should normally be expanded. Other items should stay compact unless manually opened.

Add a lightweight toolbar above the list:

- `仅看未完成`
- `全部收起`
- optional count summary such as `3 / 7 未完成`

### Right Column

`Key Screens` should stop being its own scroll container.

Remove the card-level nested scroll behavior:

- no `overflowY: auto`
- no fixed internal scrolling region

Keep the panel `sticky` on desktop so it remains visible while the page scrolls.

The right side should focus on the currently selected review item:

- current item title
- current evidence label
- main screenshot preview
- overlay bounds for the selected evidence refs
- a compact strip or selector for alternate evidence screenshots related to the current item

The right panel should not try to show every screenshot equally at once. It should prioritize the evidence connected to the active item.

## Interaction Model

Introduce an explicit `active review item` in front-end state.

Behavior:

- Clicking a review item summary makes it the active item.
- Clicking `查看推荐定位` or `查看全部证据` also makes that item active and focuses the related evidence.
- The right preview updates automatically to the first relevant evidence screenshot for the active item.
- If the active item has multiple evidence screenshots, the user can switch between them in the right panel without hunting through the whole screen history.

This keeps left and right aligned around one task at a time.

## Scroll Behavior

Desktop:

- Browser page scroll remains the only primary scroll.
- Left column grows naturally with content.
- Right column stays sticky but does not create another vertical scroll area.

Mobile:

- Preserve stacked single-column behavior.
- `Key Screens` stays below `Review Items`.
- No sticky behavior on small screens if it causes awkward viewport compression.

## State and Data Constraints

Allowed front-end state additions:

- active review item key
- expanded review item keys
- `only unresolved` filter
- active evidence screenshot selection within the active item

Not allowed:

- synthesizing new review semantics
- changing when review is considered complete
- changing backend payloads
- mutating applied review choices outside current explicit actions

## Testing

Update page tests to cover:

- review items can be selected and expanded independently
- active item changes the right-side preview focus
- unresolved-only filter hides resolved items from the list
- screenshot card no longer depends on nested internal scrolling behavior

Manual smoke should confirm:

- large review lists remain usable without left/right desynchronization
- switching items updates screenshot context predictably
- the right panel stays readable while the user scrolls the page

## Out of Scope

This change does not include:

- backend changes
- new builder APIs
- changing evidence generation
- wizard-style one-item-at-a-time flows
- redesigning the whole Builder into a brand new information architecture

## Implementation Notes

Recommended implementation order:

1. Add active item state and unresolved filter state.
2. Refactor `Review Items` rendering into compact summary + expanded details.
3. Bind right-side preview to active review item evidence first, with fallback to current manual selection behavior.
4. Remove nested `overflowY` from `Key Screens` and verify sticky behavior.
5. Update tests and run frontend verification.
