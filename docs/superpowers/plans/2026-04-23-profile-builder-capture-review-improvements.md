# Profile Builder Capture And Review Improvements Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Android Profile Builder accuracy and operator usability by making repeated captures deterministic, reducing draft errors caused by manual-vs-runtime UI differences, and making review options understandable through image-backed evidence.

**Architecture:** Keep the existing guided capture flow, but add builder-side notion of active capture per step, supplement manual captures with runtime probe evidence during draft/validate, and enrich candidate/review artifacts with image-localizable evidence (artifact name + bounds + step). The frontend will show active/superseded captures and image overlays for recommended and alternative options.

**Tech Stack:** FastAPI, Pydantic, existing profile-builder backend modules, React, TypeScript, Ant Design, TanStack Query, Vitest, pytest, Ruff

---

## File Structure

- Modify: `src/autoagent/models/api.py`
  - Extend builder candidate/review evidence models if needed for step/artifact/bounds data.
- Modify: `src/autoagent/api/profile_builder.py`
  - Mark latest capture per step as active, persist superseded captures, and expose richer review/runtime payloads.
- Modify: `src/autoagent/executors/profile_builder_capture.py`
  - Ensure repeated captures overwrite active artifacts while optionally preserving historical metadata.
- Modify: `src/autoagent/executors/profile_builder_candidates.py`
  - Prefer active captures only, add runtime-probe-aware heuristics, and emit visual evidence references with bounds.
- Modify: `src/autoagent/executors/profile_builder_generator.py`
  - Optionally merge runtime probe signals into Android draft generation.
- Modify: `src/autoagent/executors/android_executor.py`
  - Persist probe screenshots/XML during validate so builder can reason about runtime state.
- Modify: `tests/unit/test_profile_builder_candidates.py`
  - Cover latest-only capture selection and review evidence generation.
- Modify: `tests/integration/test_profile_builder_endpoints.py`
  - Cover repeated capture replacement, draft generation from latest capture, and review artifact payloads.
- Modify: `web/src/types/api.ts`
  - Add active/superseded capture metadata and image evidence metadata.
- Modify: `web/src/pages/Profiles/Builder.tsx`
  - Show active capture selection, superseded history, and image overlay review panel.
- Modify: `web/src/pages/Profiles/Builder.test.tsx`
  - Verify latest capture selection and review-image behavior.

---

### Task 1: Make repeated captures latest-wins with explicit active/superseded semantics

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `src/autoagent/executors/profile_builder_capture.py`
- Modify: `tests/integration/test_profile_builder_endpoints.py`
- Modify: `web/src/types/api.ts`
- Modify: `web/src/pages/Profiles/Builder.tsx`

- [ ] **Step 1: Write failing backend test for repeated capture replacement**

Add integration coverage asserting:
- capturing `editing` twice keeps only the newest artifact pair active for draft generation
- session/runtime payload still exposes both attempts with latest marked active and prior marked superseded

- [ ] **Step 2: Add active capture semantics to persistence**

Implementation notes:
- session-level `captures` should keep most recent capture first-class for each step
- optionally persist prior attempts under a `capture_history`/artifact metadata structure
- runtime and draft generation should always read the latest capture for a given step

- [ ] **Step 3: Update Builder UI to show active vs superseded**

Implementation notes:
- `Capture Steps` should show latest artifact as active
- prior captures should remain discoverable in a compact history section
- operator should never have to guess which capture is used by draft generation

- [ ] **Step 4: Verify**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -k repeated -v
cd web && pnpm test -- Builder.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/api/profile_builder.py src/autoagent/executors/profile_builder_capture.py tests/integration/test_profile_builder_endpoints.py web/src/types/api.ts web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx
git commit -m "feat(profile-builder): prefer latest capture per step"
```

---

### Task 2: Add runtime-aware Android draft correction for manual-vs-ADB-keyboard mismatch

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `src/autoagent/executors/profile_builder_candidates.py`
- Modify: `src/autoagent/executors/profile_builder_generator.py`
- Modify: `src/autoagent/executors/android_executor.py`
- Modify: `tests/unit/test_profile_builder_candidates.py`
- Modify: `tests/integration/test_profile_builder_endpoints.py`

- [ ] **Step 1: Write failing tests for runtime probe correction**

Add tests covering:
- manual editing capture yields one send button
- runtime probe yields a different send button
- generated draft prefers runtime probe send locator while still using manual input evidence where appropriate

- [ ] **Step 2: Persist runtime probe artifacts**

Implementation notes:
- during validate or a dedicated probe route, save:
  - runtime editing XML
  - runtime editing screenshot
- treat these as builder artifacts associated with the session

- [ ] **Step 3: Update Android candidate heuristics**

Implementation notes:
- keep manual `editing` as baseline for input field discovery
- prefer runtime probe for `send_button_locator`
- if runtime and manual disagree, emit a review item explaining the mismatch
- continue excluding system UI / IME controls from send candidates

- [ ] **Step 4: Expose runtime-probe origin in draft/review payloads**

Implementation notes:
- evidence should indicate whether candidate came from `editing_capture` or `runtime_probe`
- this gives operators clear provenance during review

- [ ] **Step 5: Verify**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_candidates.py tests/integration/test_profile_builder_endpoints.py -k 'runtime or probe or send' -v
python3.11 -m ruff check src/autoagent/api/profile_builder.py src/autoagent/executors/profile_builder_candidates.py src/autoagent/executors/profile_builder_generator.py src/autoagent/executors/android_executor.py
```

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/profile_builder.py src/autoagent/executors/profile_builder_candidates.py src/autoagent/executors/profile_builder_generator.py src/autoagent/executors/android_executor.py tests/unit/test_profile_builder_candidates.py tests/integration/test_profile_builder_endpoints.py
git commit -m "feat(profile-builder): use runtime probes for android draft correction"
```

---

### Task 3: Make Review Items image-readable with overlay evidence

**Files:**
- Modify: `src/autoagent/models/api.py`
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `src/autoagent/executors/profile_builder_candidates.py`
- Modify: `web/src/types/api.ts`
- Modify: `web/src/pages/Profiles/Builder.tsx`
- Modify: `web/src/pages/Profiles/Builder.test.tsx`

- [ ] **Step 1: Write failing tests for review evidence overlays**

Frontend tests should assert:
- clicking a review option switches preview to the evidence artifact
- overlay metadata is present for recommended and alternative options
- user can tell which rectangle belongs to which option

- [ ] **Step 2: Enrich evidence payloads with image-localizable data**

Each evidence ref should include:
- `artifact`
- `step`
- `bounds`
- `label`
- optional `source_kind` such as `manual_capture`, `runtime_probe`, `response_capture`

- [ ] **Step 3: Build image overlay UI in Builder**

Implementation notes:
- when a review item is selected, right panel should switch to the relevant artifact
- draw rectangle overlays on the image
- distinguish recommended vs alternative candidates using different colors
- preserve existing stage screenshot browsing

- [ ] **Step 4: Simplify review language**

Implementation notes:
- replace raw locator-first phrasing with user-facing phrasing such as:
  - “推荐发送按钮”
  - “候选输入框”
  - “运行态发送按钮与手动编辑态不一致”
- keep raw locator text available in an expandable details block, not as the primary surface

- [ ] **Step 5: Verify**

Run:
```bash
cd web && pnpm test -- Builder.test.tsx
cd web && pnpm exec tsc --noEmit
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -k review -v
```

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/models/api.py src/autoagent/api/profile_builder.py src/autoagent/executors/profile_builder_candidates.py web/src/types/api.ts web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx tests/integration/test_profile_builder_endpoints.py
git commit -m "feat(profile-builder): visualize review evidence on screenshots"
```

---

### Task 4: Full verification and operator smoke

**Files:**
- No planned production files; use existing builder flow and docs as needed.

- [ ] **Step 1: Run targeted backend/frontend verification**

```bash
python3.11 -m pytest tests/unit/test_profile_builder_candidates.py tests/integration/test_profile_builder_endpoints.py -v
python3.11 -m ruff check src/autoagent/api/profile_builder.py src/autoagent/executors/profile_builder_capture.py src/autoagent/executors/profile_builder_candidates.py src/autoagent/executors/profile_builder_generator.py src/autoagent/executors/android_executor.py
cd web && pnpm test -- Builder.test.tsx profileBuilderRuntime.test.ts
cd web && pnpm exec tsc --noEmit
cd web && pnpm build
```

- [ ] **Step 2: Manual builder smoke on real Android device**

Checklist:
- capture the same stage multiple times and confirm latest is active
- generate draft and verify it uses the latest capture
- inspect review items and confirm overlays explain what each option maps to
- run connectivity validation and confirm runtime-aware send locator behaves as expected with `ADB Keyboard`

- [ ] **Step 3: Update docs if UI flow changed materially**

Targets:
- Builder usage notes
- Operator troubleshooting for runtime/manual mismatch

- [ ] **Step 4: Final commit if docs changed**

```bash
git add docs
git commit -m "docs(profile-builder): document improved capture and review workflow"
```

