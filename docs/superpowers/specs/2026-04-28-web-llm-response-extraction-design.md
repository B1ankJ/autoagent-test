# Web LLM Response Extraction — Design

**Date:** 2026-04-28  
**Status:** Approved

## Motivation

1. **Platform parity** — Android executor already supports optional LLM-assisted response extraction. Web executor should offer the same capability so test profiles can be configured consistently across platforms.
2. **Fallback for selector failures** — `response_container_selector` extraction can time out or return empty when the page DOM structure is complex or dynamic. When LLM extraction is enabled, the LLM result is always recorded alongside the rule result, giving operators a reliable fallback.

## Scope

- `src/autoagent/profiles/schemas.py` — add three credential fields to `WebProfile`
- `src/autoagent/executors/web_response_llm_extractor.py` — new module (web-specific system prompt + HTML content capture)
- `src/autoagent/executors/web_executor.py` — integrate LLM extraction after each rule extraction round
- `tests/unit/test_web_response_llm_extractor.py` — unit tests for new extractor
- `tests/integration/` — integration coverage for `WebProfile.llm_response_enabled()`

**Out of scope:** Web Profile Builder UI for LLM credential entry; frontend SampleDetail changes (already renders `llm_responses` from Android work).

## 1. Profile Schema

`WebProfile` gains three optional fields mirroring `AndroidProfile`:

```python
class WebProfile(BaseProfile):
    # ... existing fields unchanged ...
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None

    def llm_response_enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)
```

All three must be non-empty for LLM extraction to activate. Runtime reads credentials exclusively from the profile YAML — the global `VLMConfig` (Config page) is not consulted at runtime, consistent with Android behaviour.

## 2. New Module: `web_response_llm_extractor.py`

**Location:** `src/autoagent/executors/web_response_llm_extractor.py`

**Reused from Android path:**
- `LLMExtractionResult` dataclass (imported from `response_llm_extractor`)
- HTTP call structure (OpenAI-compatible `/chat/completions`, `json_schema` strict mode)
- Error code mapping: `connect`, `auth`, `model_not_found`, `response_shape`, `timeout`
- Three-segment truncation: first 40K + middle 40K + last 40K chars (120K total limit)

**Web-specific:**

*System prompt (Chinese, HTML context):*
> 你是一个网页内容提取助手。你会收到一段 HTML 片段和用户发送给 AI 产品的 prompt。你的任务是从 HTML 中找出 AI 助手对该 prompt 的最新回复文本，只返回回复内容本身，不要包含按钮文字、占位符、界面提示等 UI 元素的文字。

*Function signature:*
```python
async def extract_web_response_via_llm(
    prompt: str,
    html: str,
    base_url: str,
    model: str,
    api_key: str,
) -> LLMExtractionResult
```

The `html` argument is the HTML content string prepared by the caller (see §3).

## 3. Web Executor Integration

**HTML content capture** (inside `web_executor.py`, before calling the extractor):

1. Try `page.evaluate("document.querySelector(selector)?.outerHTML ?? null", selector)` — returns the matched container's outerHTML if the element exists.
2. If result is `None` (selector matched nothing), fallback to `page.evaluate("document.body.outerHTML")`.
3. Pass the result string to `extract_web_response_via_llm()`. Truncation is handled inside the extractor.

**Per-round flow** (each interaction turn within a sample):

```
1. Fill input → screenshot
2. Send → screenshot
3. Wait completion (CompleteDetection)
4. _collect_latest_text(page, selector) → rule_text
   ctx.responses.append(rule_text)
5. if profile.llm_response_enabled():
   a. html = await _capture_html(page, profile.response_container_selector)
   b. llm_result = await extract_web_response_via_llm(prompt, html, ...)
   c. ctx.llm_responses.append(llm_result.text)
   d. ctx.llm_errors.append(llm_result.error)
6. Screenshot final
```

**Alignment invariant:** When LLM is enabled, one entry is appended to each of `responses`, `llm_responses`, and `llm_errors` every round, keeping all three lists equal-length — identical to Android behaviour.

**Soft failure:** Any exception from the LLM call is caught; error code is written to `llm_errors[i]`, `llm_responses[i]` is set to `""`. Sample status is not affected.

**Latency:** Recorded in `LLMExtractionResult.latency_ms` and logged at DEBUG level with the same format as Android.

## 4. Testing

**Unit — `tests/unit/test_web_response_llm_extractor.py`:**
- Happy path: mock httpx response `{"response": "hello"}` → `LLMExtractionResult.text == "hello"`, `error is None`
- HTML truncation: input > 120K chars → `truncated_input == True`, content shortened to ≤120K
- Error mapping: 401 → `auth`, 404 → `model_not_found`, `ConnectError` → `connect`, timeout → `timeout`

**Integration:**
- `WebProfile` with all three credential fields → `llm_response_enabled()` returns `True`
- `WebProfile` with any credential field missing/empty → `llm_response_enabled()` returns `False`

## Data Flow Summary

```
WebProfile YAML
  └─ base_url / model / api_key
       └─ web_executor (per round)
            ├─ _collect_latest_text() → ctx.responses[i]
            └─ _capture_html() → extract_web_response_via_llm()
                 └─ LLMExtractionResult → ctx.llm_responses[i] / ctx.llm_errors[i]
                      └─ SampleResult.llm_responses / llm_errors (existing schema)
```

Frontend `SampleDetail` already renders `llm_responses` from the Android implementation — no frontend changes required.
