# Profile Builder Candidate Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand Android Builder review candidates for input and send controls, and support multi-`TextView` response blocks without unnecessary `latest_bubble_match` review prompts.

**Architecture:** Extend candidate generation in `profile_builder_candidates.py` from narrow heuristic filters to broader region-based collection plus deduped ranking. Update runtime extraction to aggregate response blocks rather than single `TextView` nodes, then gate review creation on ambiguity rather than always reviewing structurally stable cases.

**Tech Stack:** Python 3.11, FastAPI backend, pytest unit/integration tests

---

### Task 1: Lock candidate-expansion behavior with failing tests

**Files:**
- Modify: `tests/unit/test_profile_builder_candidates.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_android_candidates_keeps_focus_proxies_and_composer_controls():
    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    input_review = next(item for item in draft.review_items if item["field"] == "input_locator")
    focus_review = next(item for item in draft.review_items if item["field"] == "input_focus_action")
    send_review = next(item for item in draft.review_items if item["field"] == "send_action")

    assert len(input_review["alternative_candidates"]) >= 4
    assert len(focus_review["alternative_candidates"]) >= 5
    assert len(send_review["alternative_candidates"]) >= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest .worktrees/plan4-android-executor/tests/unit/test_profile_builder_candidates.py -q`
Expected: FAIL because the current heuristics drop proxy input targets and send wrappers.

- [ ] **Step 3: Write minimal test coverage for multi-fragment responses**

```python
def test_build_android_candidates_groups_multi_textview_response_block():
    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    candidate = draft.response_candidates[0]

    assert candidate["bubble_preview"] == "第一段 第二段 第三段"
    review = [item for item in draft.review_items if item["field"] == "latest_bubble_match"]
    assert review == []
```

- [ ] **Step 4: Run tests to verify they fail for the intended reason**

Run: `python3.11 -m pytest .worktrees/plan4-android-executor/tests/unit/test_profile_builder_candidates.py -q`
Expected: FAIL because the builder still treats fragmented replies as separate `TextView` bubbles and still over-reviews.

### Task 2: Expand input and send candidate collection

**Files:**
- Modify: `src/autoagent/executors/profile_builder_candidates.py`
- Test: `tests/unit/test_profile_builder_candidates.py`

- [ ] **Step 1: Implement broader input-region candidate collection**

```python
def _build_input_candidates(editing_nodes: list[dict[str, str]], idle_nodes: list[dict[str, str]]) -> list[dict]:
    raw_candidates = []
    raw_candidates.extend(_editable_input_candidates(editing_nodes))
    raw_candidates.extend(_composer_placeholder_candidates(editing_nodes, source="editing_xml"))
    raw_candidates.extend(_composer_placeholder_candidates(idle_nodes, source="idle_xml"))
    raw_candidates.extend(_composer_proxy_candidates(editing_nodes))
    raw_candidates.extend(_composer_proxy_candidates(idle_nodes))
    return _dedupe_ranked_candidates(raw_candidates)
```

- [ ] **Step 2: Implement broader send candidate collection**

```python
def _build_send_candidates_from_nodes(editing_nodes: list[dict[str, str]], *, source: str) -> list[dict]:
    raw_candidates = []
    raw_candidates.extend(_composer_clickable_candidates(editing_nodes, source=source))
    raw_candidates.extend(_composer_ancestor_candidates(editing_nodes, source=source))
    return _dedupe_ranked_candidates(raw_candidates)
```

- [ ] **Step 3: Expand input focus action generation to use the full candidate pool**

```python
def _input_focus_action_review_item(idle_xml: str, input_candidates: list[dict]) -> dict | None:
    options = _focus_options_from_input_candidates(input_candidates)
    options.extend(_focus_options_from_idle_placeholder(idle_xml))
    return _review_item_from_options(...)
```

- [ ] **Step 4: Run targeted tests**

Run: `python3.11 -m pytest .worktrees/plan4-android-executor/tests/unit/test_profile_builder_candidates.py -q`
Expected: PASS for the new candidate-expansion tests and existing candidate tests.

- [ ] **Step 5: Commit**

```bash
git -C .worktrees/plan4-android-executor add src/autoagent/executors/profile_builder_candidates.py src/autoagent/api/profile_builder.py tests/unit/test_profile_builder_candidates.py
git -C .worktrees/plan4-android-executor commit -m "fix(profile-builder): expand input and send review candidates"
```

### Task 3: Add response-block aggregation and conditional review gating

**Files:**
- Modify: `src/autoagent/executors/profile_builder_candidates.py`
- Modify: `src/autoagent/executors/response_extractor.py`
- Modify: `tests/unit/test_profile_builder_candidates.py`
- Modify: `tests/unit/test_response_extractor_ui_tree.py`

- [ ] **Step 1: Write failing runtime/block tests**

```python
def test_extract_from_xml_aggregates_latest_response_block():
    result = UiTreeExtractor.extract_from_xml(
        xml_text=xml_text,
        response_container_locator=response_container,
        latest_bubble_locator=latest_rule,
    )
    assert result.text == "第一段 第二段 第三段"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest .worktrees/plan4-android-executor/tests/unit/test_response_extractor_ui_tree.py .worktrees/plan4-android-executor/tests/unit/test_profile_builder_candidates.py -q`
Expected: FAIL because extraction still chooses a single `TextView`.

- [ ] **Step 3: Implement response block grouping in candidate generation and runtime extraction**

```python
def _group_response_blocks(container: ElementTree.Element) -> list[list[ElementTree.Element]]:
    ...

def _aggregate_block_text(block: list[ElementTree.Element]) -> str:
    return " ".join(part for part in ordered_parts if part)
```

- [ ] **Step 4: Gate `latest_bubble_match` review on ambiguity**

```python
if _needs_latest_bubble_review(response_candidates):
    review_items.append(...)
```

- [ ] **Step 5: Run targeted tests**

Run: `python3.11 -m pytest .worktrees/plan4-android-executor/tests/unit/test_profile_builder_candidates.py .worktrees/plan4-android-executor/tests/unit/test_response_extractor_ui_tree.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git -C .worktrees/plan4-android-executor add src/autoagent/executors/profile_builder_candidates.py src/autoagent/executors/response_extractor.py tests/unit/test_profile_builder_candidates.py tests/unit/test_response_extractor_ui_tree.py
git -C .worktrees/plan4-android-executor commit -m "fix(android): extract latest response blocks structurally"
```

### Task 4: Verify API behavior, sync docs, and finalize

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md`
- Modify: `tests/integration/test_profile_builder_endpoints.py`

- [ ] **Step 1: Update integration tests for new review behavior**

```python
def test_generate_draft_skips_latest_bubble_review_when_structurally_unambiguous():
    ...
    assert "latest_bubble_match" not in {item["field"] for item in payload["review_items"]}
```

- [ ] **Step 2: Update docs to reflect broader raw candidates and response-block semantics**

```md
- input/send review now preserves broader raw candidates and relies on ranking
- latest_bubble_match review is conditional when structural response anchors are stable
- multi-TextView assistant replies are aggregated into one response block
```

- [ ] **Step 3: Run verification**

Run: `python3.11 -m pytest .worktrees/plan4-android-executor/tests/unit/test_profile_builder_candidates.py .worktrees/plan4-android-executor/tests/unit/test_response_extractor_ui_tree.py .worktrees/plan4-android-executor/tests/unit/test_android_executor_unit.py .worktrees/plan4-android-executor/tests/integration/test_profile_builder_endpoints.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git -C .worktrees/plan4-android-executor add README.md CLAUDE.md docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md tests/integration/test_profile_builder_endpoints.py
git -C .worktrees/plan4-android-executor commit -m "docs(profile-builder): document candidate expansion behavior"
```
