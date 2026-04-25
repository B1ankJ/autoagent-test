# Smart Draft Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single "LLM optimization" toggle with two explicit Draft generation modes: a deterministic `rule` mode that still requires manual review before connectivity testing, and a `smart` mode where LLM both improves the draft and auto-selects review decisions so the draft can go directly into connectivity testing.

**Architecture:** Keep the current Builder capture and candidate pipeline as the source of truth. `rule` mode continues to generate `rule_draft + review_items` and blocks connectivity until required review fields are confirmed by the user. `smart` mode reuses the same candidate evidence but asks the LLM for two outputs: sparse draft overrides and review decisions; the backend applies those decisions into the generated YAML, returns the auto-applied review state to the frontend, and marks the draft as review-complete while still preserving the review panel for optional user override.

**Tech Stack:** Python 3.11 · FastAPI · Pydantic v2 · httpx · pytest-asyncio · React 18 · TanStack Query v5 · Ant Design.

**Prereq:** Existing Profile Builder flow on branch `plan4-android-executor`, including `use_llm_optimization`, `inject_llm`, Builder review items, and Connectivity Test runtime, is already green.

**Status (2026-04-25):** Smart Draft mode is complete. Backend contract, smart review-decision application, Builder mode selector/gating, Builder connectivity dual-view, automated verification, and targeted real-device smoke are all complete.

**Completed commits:** `a87e9e0`, `ef2538b`.

---

## File Structure

```text
src/autoagent/
  api/
    profile_builder.py                 # MODIFY: draft request/response shape; smart-mode orchestration
  executors/
    profile_builder_generator.py       # MODIFY: smart-mode LLM schema, review decision merge/apply
  models/
    api.py                             # MODIFY if shared response models are needed for draft metadata
tests/
  unit/
    test_profile_builder_generator.py  # MODIFY: smart-mode schema + decision-merge behavior
  integration/
    test_profile_builder_endpoints.py  # MODIFY: rule vs smart draft endpoint behavior
web/src/
  api/profileBuilder.ts                # MODIFY: send draft_mode, consume auto-review metadata
  pages/Profiles/Builder.tsx           # MODIFY: mode selector, review gating, smart-mode messaging
docs/
  superpowers/specs/
    2026-04-25-smart-draft-mode-design.md   # CREATE or backfill if design doc is desired later
  superpowers/plans/
    2026-04-25-smart-draft-mode.md     # THIS FILE
CLAUDE.md                              # MODIFY: note Builder now has rule/smart draft modes
```

---

## Task 1: Introduce explicit draft modes in the backend contract

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `tests/integration/test_profile_builder_endpoints.py`

- [x] **Step 1: Add a failing integration test for `draft_mode`**
  - Cover `draft_mode="rule"` returning a draft that still requires manual review.
  - Cover `draft_mode="smart"` returning a draft payload that includes auto-applied review metadata.
  - Cover invalid mode rejection.

- [x] **Step 2: Run the endpoint test and verify it fails**
  - Run: `python3.11 -m pytest .worktrees/plan4-android-executor/tests/integration/test_profile_builder_endpoints.py -q`
  - Expected: request validation or missing-field assertions fail.

- [x] **Step 3: Replace `use_llm_optimization` with `draft_mode` in the request model**
  - Add a `Literal["rule", "smart"]` field to `_GenerateDraftRequest`.
  - Keep `inject_llm` as an independent boolean.
  - Default to `rule` or `smart` explicitly; recommendation: default to `rule` to keep deterministic behavior unless the user intentionally asks for smart generation.

- [x] **Step 4: Extend the draft response shape**
  - Add metadata fields returned from `/draft`:
    - `draft_mode`
    - `requires_manual_review`
    - `applied_review_choices`
    - `auto_review_source` (`"manual"` or `"llm"`)
  - Keep existing `review_items` so the UI can still render and edit them.

- [x] **Step 5: Run the integration test and verify the new contract passes**

- [x] **Step 6: Commit**
  - `git add src/autoagent/api/profile_builder.py .worktrees/plan4-android-executor/tests/integration/test_profile_builder_endpoints.py`
  - `git commit -m "feat(profile_builder): add explicit rule and smart draft modes"`

---

## Task 2: Teach the LLM path to return review decisions, not only draft overrides

**Files:**
- Modify: `src/autoagent/executors/profile_builder_generator.py`
- Modify: `tests/unit/test_profile_builder_generator.py`

- [x] **Step 1: Add failing unit tests for smart-mode LLM output**
  - One test for a valid LLM response containing both sparse `draft_overrides` and `review_decisions`.
  - One test proving unknown review fields or invalid option indexes are rejected and fall back safely.
  - One test proving `rule` mode never calls the LLM.

- [x] **Step 2: Run the unit test and verify it fails**

- [x] **Step 3: Extend the LLM JSON schema**
  - Change the current schema from "draft overrides only" to:
    - `draft_overrides`
    - `review_decisions`
  - `review_decisions` should be grounded in existing `review_items`, preferably by field name plus selected option index.

- [x] **Step 4: Update the LLM prompt payload**
  - Include:
    - current `rule_draft`
    - top candidate summary
    - full `review_items`
    - explicit instruction that the model must only choose among provided review options
  - Keep output sparse and schema-constrained.

- [x] **Step 5: Implement safe merge/apply helpers**
  - Helper 1: merge `draft_overrides` into `rule_draft`
  - Helper 2: apply `review_decisions` to produce a `resolved_draft`
  - Helper 3: validate that every auto-selected option exists before applying it
  - On any invalid decision, do not silently invent a selector; fall back to the rule draft and preserve the unresolved review item.

- [x] **Step 6: Return structured smart-mode generation output**
  - Return:
    - `final_draft`
    - `applied_review_choices`
    - `requires_manual_review`
    - `auto_review_source`

- [x] **Step 7: Run the generator unit tests and verify they pass**

- [x] **Step 8: Commit**
  - `git add src/autoagent/executors/profile_builder_generator.py .worktrees/plan4-android-executor/tests/unit/test_profile_builder_generator.py`
  - `git commit -m "feat(profile_builder): auto-apply review decisions in smart draft mode"`

---

## Task 3: Split Builder runtime behavior between blocking review mode and direct-connectivity smart mode

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `tests/integration/test_profile_builder_endpoints.py`

- [x] **Step 1: Add failing integration tests for connectivity gating**
  - `rule` mode: connectivity remains blocked until required review items are manually confirmed.
  - `smart` mode: connectivity is allowed immediately when all required review fields were auto-resolved by LLM.
  - `smart` mode fallback: if some review decisions are invalid or missing, `requires_manual_review` remains true and connectivity stays blocked.

- [x] **Step 2: Run the tests and verify they fail**

- [x] **Step 3: Encode gating rules in the backend response**
  - Do not leave this entirely to frontend heuristics.
  - Return enough state for the UI to know whether connectivity can start:
    - `requires_manual_review`
    - `resolved_required_review_fields`
    - `pending_required_review_fields`

- [x] **Step 4: Ensure saved artifacts reflect smart-mode decisions**
  - `draft_profile.yaml` should already contain the auto-applied choices.
  - `review_items.json` should keep the original options plus which choice was auto-applied.
  - Add an artifact such as `draft_generation_result.json` if needed for observability.

- [x] **Step 5: Run integration tests and verify gating behavior passes**

- [x] **Step 6: Commit**
  - `git add src/autoagent/api/profile_builder.py .worktrees/plan4-android-executor/tests/integration/test_profile_builder_endpoints.py`
  - `git commit -m "feat(profile_builder): gate connectivity by draft mode and review resolution"`

---

## Task 4: Replace the Builder checkbox with an explicit Draft Mode selector in the frontend

**Files:**
- Modify: `web/src/api/profileBuilder.ts`
- Modify: `web/src/pages/Profiles/Builder.tsx`
- Test: `web/src/pages/Profiles/Builder.test.tsx`

- [x] **Step 1: Add failing frontend tests for mode selection**
  - One test that `Generate Draft` sends `draft_mode: "rule"` and keeps manual review blocking.
  - One test that `Generate Draft` sends `draft_mode: "smart"` and enables connectivity when the backend says review is resolved.
  - One test that `inject_llm` stays independent from draft mode.

- [x] **Step 2: Run the frontend test and verify it fails**

- [x] **Step 3: Replace `useLlmOptimization` UI with a mode selector**
  - Recommended copy:
    - `规则 Draft（需人工确认 Review）`
    - `智能 Draft（LLM 自动选择 Review）`
  - Keep `生成时注入 LLM 响应抽取配置` as a separate checkbox.

- [x] **Step 4: Update request wiring**
  - `useGenerateProfileBuilderDraft()` should post `draft_mode` and `inject_llm`.
  - Remove the old `use_llm_optimization` parameter from the request body and state.

- [x] **Step 5: Update Builder page state and review UX**
  - Rule mode:
    - show pending-review state
    - keep `Run Connectivity Test` disabled until manual review is complete
  - Smart mode:
    - show that LLM has already chosen review options
    - leave review controls editable
    - allow direct connectivity when backend says `requires_manual_review=false`

- [x] **Step 6: Add review provenance cues**
  - Show whether each selected review item came from:
    - `manual`
    - `llm`
    - `default rule recommendation`
  - Keep the UI readable; do not hide the candidate list.

- [x] **Step 7: Run frontend tests and verify they pass**
  - `cd .worktrees/plan4-android-executor/web && pnpm test -- Builder`

- [x] **Step 8: Commit**
  - `git add web/src/api/profileBuilder.ts web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx`
  - `git commit -m "feat(web): add rule and smart draft modes to profile builder"`

---

## Task 5: Improve connectivity result presentation in Builder for smart mode

**Files:**
- Modify: `web/src/pages/Profiles/Builder.tsx`
- Test: `web/src/pages/Profiles/Builder.test.tsx`

- [x] **Step 1: Add failing UI tests for connectivity result summary**
  - Ensure Builder connectivity result no longer only shows `responses[0]`.
  - Ensure smart-mode runs show separate `规则提取` and `LLM 提取`, matching the rest of the product.

- [x] **Step 2: Run the frontend test and verify it fails**

- [x] **Step 3: Reuse the existing response comparison presentation**
  - Either embed `ResponseComparison` directly or extract a Builder-friendly wrapper.
  - Show:
    - rule extraction result
    - LLM extraction result
    - clear disabled/not-enabled state
    - llm error stage when present

- [x] **Step 4: Update Builder summary copy**
  - Rule mode: emphasize "connectivity passed after manual review"
  - Smart mode: emphasize "LLM auto-selected review items; you can still revise before saving"

- [x] **Step 5: Run frontend tests and verify they pass**

- [x] **Step 6: Commit**
  - `git add web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx`
  - `git commit -m "feat(web): clarify builder connectivity results for rule and smart modes"`

---

## Task 6: Verification, smoke, and docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`
- Modify: `docs/superpowers/plans/2026-04-25-smart-draft-mode.md`

- [x] **Step 1: Update docs**
  - In `CLAUDE.md`, explain Builder now has two Draft modes and what each mode guarantees.
  - In the Android smoke checklist, add:
    - rule mode path requiring manual review
    - smart mode path allowing immediate connectivity if LLM resolved all required fields

- [x] **Step 2: Run backend verification**
  - `python3.11 -m pytest -q -m "not playwright and not android and not slow"`

- [x] **Step 3: Run frontend verification**
  - `cd .worktrees/plan4-android-executor/web && pnpm test && pnpm lint && pnpm build`

- [x] **Step 4: Run targeted Builder real-device smoke**
  - Rule mode:
    - Generate Draft
    - verify review is mandatory
    - verify connectivity is blocked until review is complete
  - Smart mode:
    - Generate Draft
    - verify review items are preselected
    - verify connectivity is immediately available when backend resolved all required fields
    - manually override one review item and confirm regenerated/saved YAML reflects the override

Result: completed on a real Android device on 2026-04-25; both rule-mode and smart-mode flows passed with no blocking issues found.

- [x] **Step 5: Commit docs and verification follow-up**
  - `git add CLAUDE.md docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md docs/superpowers/plans/2026-04-25-smart-draft-mode.md`
  - `git commit -m "docs: record smart draft mode behavior and verification"`

---

## Risks to watch

- LLM may choose a syntactically valid but semantically bad review option; do not let smart mode hide review provenance.
- If `smart` mode falls back partially, the UI must not pretend the draft is direct-connectivity-ready.
- Do not couple `inject_llm` to `draft_mode`; they solve different problems.
- Avoid a second, duplicated source of truth for review resolution in the frontend. The backend should declare whether manual review is still required.

## Recommended execution order

1. Backend contract (`draft_mode`, response metadata)
2. LLM review-decision schema and safe apply logic
3. Backend connectivity gating and artifact persistence
4. Frontend mode selector and review UX
5. Builder connectivity result display
6. Docs + verification + real-device smoke
