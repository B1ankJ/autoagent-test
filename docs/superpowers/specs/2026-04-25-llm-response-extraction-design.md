# LLM Response Extraction — Design

- Date: 2026-04-25
- Status: approved (pending implementation plan)
- Scope: Android executor only (first release). Web/API executors unchanged.

## 1. Goal

Augment every Android test round with an LLM-based extractor that reads the final `after_result_<n>.xml` and produces the assistant's latest reply, running **alongside** the existing static rule-based extractor. Each sample result carries two parallel response lists so users can compare and fall back.

LLM extraction is **opt-in per profile**:
- Profile YAML contains `base_url` + `model` + `api_key` → enabled.
- Any field missing → disabled, and results still contain two (empty) lists for shape consistency.

## 2. Credential model

### 2.1 One unified "LLM config"

We consolidate the three credential slots that previously existed into one:

- **Global `VLMConfig`** (KV store, edited on Config page): serves as the default source for Profile Builder (draft enrichment + YAML injection). Not read at runtime.
- **Profile YAML** (`base_url` / `model` / `api_key`): the **single source of truth at runtime**.
- **`PROFILE_BUILDER_LLM_*` env vars**: **removed**. Profile Builder migrates to reading `VLMConfig` from KV.

### 2.2 `VLMConfig` schema change

`models/api.py`:

```python
class VLMConfig(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None          # literal key; replaces api_key_env
    extra_headers: dict[str, str] = {}
```

- Old field `api_key_env` is dropped; no backward-compat shim (repo not yet in production).
- All-empty = "LLM disabled globally". Any non-empty but incomplete triple is rejected by the save endpoint.

### 2.3 `AndroidProfile` schema change

`profiles/schemas.py`, add three optional fields and a helper:

```python
class AndroidProfile(BaseModel):
    ...
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    ...

    def llm_response_enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)
```

Field order in serialized YAML: after `serial`, before `input_method`.

### 2.4 Security note

Profile YAMLs may now contain plaintext API keys. Implications rolled into Plan 5:

- `data/profiles/*.yaml` becomes sensitive; must be excluded from public git and unencrypted backups.
- Plan 5 `SecretStr` migration scope extends to `AndroidProfile` credential fields.
- CLAUDE.md gains an explicit note about profile directory sensitivity.

## 3. Config page (Config.tsx + api/config.py)

### 3.1 Connectivity checker

New module `executors/llm_checker.py`. HTTP-only (uses existing `httpx`, no `openai` SDK).

```python
@dataclass
class CheckResult:
    ok: bool
    stage: Literal["connect","auth","model_not_found","response_shape","ok"]
    message: str
    latency_ms: int

async def check_llm_api(
    base_url: str, model: str, api_key: str, timeout_sec: float = 30.0,
) -> CheckResult:
    # POST {base_url}/chat/completions
    # messages=[{"role":"user","content":"Hi"}], max_tokens=5, temperature=0
    # Map httpx errors / status codes / body shape to stage enum.
```

### 3.2 Endpoints

`api/config.py`:

- `POST /api/v1/config/vlm/test` — body `{base_url, model, api_key}`, returns `CheckResult`. Never writes KV.
- `PUT /api/v1/config/vlm` — runs `check_llm_api` before writing. Failure → `400` + `CheckResult` body. All-empty triple → skip check, write (disables LLM).
- `GET /api/v1/config/vlm` — unchanged; frontend uses this to decide whether the Builder toggle is enabled.

### 3.3 Frontend (`web/src/pages/Config.tsx`)

- Three existing inputs unchanged in placement.
- Add **"测试连通性"** button beside them. Click → call `/vlm/test`, render result. Stage mapped to localized message:
  - `connect` → "无法连接到该地址"
  - `auth` → "认证失败，检查 API key"
  - `model_not_found` → "模型不存在"
  - `response_shape` → "返回格式异常"
  - `ok` → "连通正常（latency_ms=…）"
- **"保存"** button unchanged in position; call `PUT`. Failure response mapped with the same localization.
- Save button is not locked by test state; backend is the final gate.

## 4. Profile Builder (inject LLM creds into generated YAML)

### 4.1 Frontend (`web/src/pages/Profiles/Builder.tsx`)

- Add a `Checkbox` **"生成时注入 LLM 响应抽取配置"** in the Generate Draft area.
- Enabled iff `useVLM()` returns a complete triple (`base_url && model && api_key`).
- When disabled: `Tooltip` "先在 Config 页面配置并通过连通性测试后才能启用"; include a "去配置" link to `/config`.
- Default: unchecked. State is session-local (not persisted).

### 4.2 Backend (`api/profile_builder.py`)

- `POST /api/v1/profile-builder/sessions/{id}/draft` gains `inject_llm: bool = False` in the request body.
- In `generate_draft()`:
  1. Run rule draft + optional LLM draft enrichment (existing).
  2. If `inject_llm=True`: load `VLMConfig` from KV; if triple is complete, copy into draft fields `base_url` / `model` / `api_key`. If incomplete → `400 {"error":"llm_config_incomplete"}` (defense in depth; UI already gates).
  3. Serialize YAML with the three fields inserted between `serial` and `input_method`.

Snapshot semantics: injected values are the KV state **at injection time**. Later changes to global config do not retroactively update existing profile YAMLs.

### 4.3 Draft enrichment migration

`executors/profile_builder_generator.py`:

- `_has_llm_config(settings)` → `_has_llm_config(vlm: VLMConfig)`.
- `maybe_generate_llm_draft(...)` signature now takes an async accessor for `VLMConfig` instead of `Settings`.
- `Settings.profile_builder_llm_base_url` / `_model` / `_api_key` / `_timeout_sec` removed.
- `.env.example` section removed.
- Timeout constant moves to module-level `LLM_DRAFT_TIMEOUT_SEC = 30.0` (was configurable; YAGNI for now).

## 5. Runtime LLM extraction

### 5.1 New module

`executors/response_llm_extractor.py`:

```python
@dataclass
class LLMExtractionResult:
    text: str            # assistant reply extracted from XML; "" on failure
    error: str | None    # short failure reason; None on success
    latency_ms: int

async def extract_response_via_llm(
    *,
    prompt: str,
    xml: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
    max_xml_chars: int = 120_000,
) -> LLMExtractionResult:
    ...
```

- XML truncation: if `len(xml) > max_xml_chars`, keep first 40k + middle 40k + last 40k with `<!-- truncated -->` separators. Truncation is recorded in `error` as `"truncated"` but `text` is still returned; truncation alone is not a hard failure.
- Failure `stage` enum shared with `llm_checker`: `connect` / `auth` / `timeout` / `response_shape` / `empty`.
- **No retries** in first release.

### 5.2 Call site (`executors/android_executor.py`)

In the per-prompt loop, after the rule-based extractor has appended to `responses` and the XML has been persisted to `after_result_<i>.xml`:

```python
if profile.llm_response_enabled():
    llm_res = await extract_response_via_llm(
        prompt=prompt, xml=xml_text,
        base_url=profile.base_url,
        model=profile.model,
        api_key=profile.api_key,
    )
    llm_responses.append(llm_res.text)
    llm_errors.append(llm_res.error)
# else: leave both lists empty for the whole sample
```

Semantics:

- **Per-round 1:1 alignment** with rule extraction.
- **Serial** after rule extraction (not parallel).
- **No cross-feed**: LLM does not see the rule result, and the rule extractor does not see LLM output.
- **Failure is soft**: sample `status` is unaffected by LLM failure.

### 5.3 Logging

Append two entries to `logs/<batch>/<sample>/actions.jsonl` per round: `llm_extract_start` (with model name) and `llm_extract_done` (with latency_ms, error). No XML duplication — it is already on disk as `after_result_<i>.xml`.

## 6. Prompt & response schema

### 6.1 System prompt (constant, Chinese)

```
你是一个 Android 聊天 App 响应抽取器。用户会给你：
1) 本轮用户输入的 prompt 文本；
2) 本轮执行结束时 App 的 UI 层级 XML（Android uiautomator dump 格式，
   只读，代表页面当前可见节点树）。

你的唯一任务：从 XML 中定位助手（assistant/bot）对用户 prompt 的最新一条回复，
把该回复的纯文本内容原样抽取出来。

规则：
- 只返回助手最新一条回复的文本，不要包含用户自己的 prompt、历史消息、
  UI 提示、按钮文案、占位符、输入建议、底部功能栏、Toast 等无关内容。
- 多个 TextView 组成的同一条回复要按 XML 中出现顺序拼接成一段文本，
  段落之间用换行分隔。
- 若 XML 中找不到可识别的助手回复，返回空字符串。
- 不做改写、不做总结、不加前后缀、不输出解释。
- 严格按给定 JSON schema 返回。
```

### 6.2 User message

Single user message whose content is a JSON string:

```json
{"prompt": "<本轮用户输入>", "xml": "<XML 原文或截断后内容>"}
```

### 6.3 Request body

```json
{
  "model": "<profile.model>",
  "temperature": 0,
  "messages": [
    {"role":"system","content":"<system prompt>"},
    {"role":"user","content":"<JSON string>"}
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "android_response_extraction",
      "strict": true,
      "schema": {
        "type": "object",
        "additionalProperties": false,
        "properties": {"response": {"type": "string"}},
        "required": ["response"]
      }
    }
  }
}
```

### 6.4 Output parsing

- Success: `choices[0].message.content` → `json.loads` → take `response` field.
- Empty string `""` is valid (means "no assistant reply found in this XML"); not an error.
- Parse failure / missing field / non-string → `error="response_shape"`, `text=""`.
- No auto-fallback to free-form text output in v1. Users switch models if endpoint does not support `json_schema`.

## 7. Result model & UI

### 7.1 `SampleResult`

`models/api.py`, additive:

```python
class SampleResult(BaseModel):
    ...
    responses: list[str] = []
    llm_responses: list[str] = []            # new
    llm_errors: list[str | None] = []        # new; same length as llm_responses
```

Invariants:
- If profile disables LLM: both new lists are `[]`.
- If enabled: `len(llm_responses) == len(llm_errors) == len(responses)`.

JSONL writer requires no change (Pydantic dump already picks up the new fields).

### 7.2 SampleDetail page (`web/src/pages/Batches/SampleDetail.tsx`)

- Response area becomes two columns per round: left "规则抽取" (`responses[i]`), right "LLM 抽取" (`llm_responses[i]`).
- If `llm_errors[i]` is non-null, render the stage string in small grey text below the LLM cell.
- If `llm_responses.length === 0`: collapse to single column (unchanged legacy layout).

Webhook payload: same additive change, no contract bump.

## 8. Removal list (breaking, accepted)

- `Settings.profile_builder_llm_base_url`, `_model`, `_api_key`, `_timeout_sec`.
- `.env.example` corresponding lines.
- `VLMConfig.api_key_env` (renamed to `api_key`). Existing KV values for VLM must be manually re-entered in dev; no migration script.

## 9. Testing

Unit:
- `tests/unit/test_llm_checker.py` — every `stage` branch (mock httpx: 200, 401, 404, timeout, empty body, malformed body).
- `tests/unit/test_response_llm_extractor.py` — success, XML truncation path, `response_shape` failure, empty-string-is-not-error.
- Updated `tests/unit/test_profile_builder_generator.py` — reads KV instead of Settings.

Integration:
- `tests/integration/test_config_vlm_endpoints.py` — `POST /vlm/test` branches; `PUT` gate; clear-triple bypass.
- Updated `tests/integration/test_profile_builder_endpoints.py` — `inject_llm=True` success; `inject_llm=True` with incomplete global → 400; default (unchecked) still works.
- `tests/integration/test_android_executor_llm.py` — profile with / without triple produces expected `SampleResult` shapes (mock LLM endpoint + stub XML).

Frontend (Vitest + RTL):
- `Config.test.tsx` — test-button stages; save rejection surfacing.
- `Builder.test.tsx` — toggle disabled when `VLMConfig` incomplete; `inject_llm` param wired on Generate.
- `SampleDetail.test.tsx` — two-column rendering; single-column fallback.

Android real-device smoke (updates to `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`):
1. No LLM configured — batch runs; JSONL shows `llm_responses=[]`, `llm_errors=[]`.
2. Config bad key → test button returns `auth` → save rejected.
3. Config good key → test passes → save ok.
4. Builder toggle ON → generated YAML contains the triple.
5. Run batch with that YAML → both response columns populated in SampleDetail.
6. Break YAML `api_key` → sample still `success`, `llm_responses[i]=""`, `llm_errors[i]="auth"`.

## 10. Non-goals (v1)

- Web/API executors. Their extraction path is different (Playwright DOM vs XML) and can be added later under a separate spec.
- Retry / backoff on LLM calls.
- Parallel rule + LLM extraction.
- Feeding rule result to LLM or vice versa.
- Auto-fallback to free-form output when `json_schema` is not supported.
- `SecretStr` migration (Plan 5).
- A `llm_strict` profile flag that fails the sample on LLM failure (Plan 5 candidate).

## 11. CLAUDE.md updates

- Remove mentions of `PROFILE_BUILDER_LLM_*` env vars.
- Add entry: "Profile YAMLs may contain plaintext `base_url` / `model` / `api_key`; treat the profile directory as sensitive (no public git, no unencrypted backups)."
- Add entry under conventions: "Runtime LLM response extraction reads credentials from profile YAML only; global VLMConfig is only a default source for Profile Builder."
- Update "When starting a new task" pointer list to reference this spec.
