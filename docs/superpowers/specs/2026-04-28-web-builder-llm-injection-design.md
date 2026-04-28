# Web Builder LLM Credential Injection — Design

**Date:** 2026-04-28  
**Status:** Approved

## Motivation

Web profile builder currently generates YAML without LLM extraction credentials. Users who want LLM-assisted response extraction must manually add `base_url`, `model`, and `api_key` to the generated YAML. This mirrors an existing gap that Android builder already solves with an "inject LLM config" checkbox. This feature adds the same capability to the web builder.

## Scope

- `src/autoagent/api/web_profile_builder.py` — add `inject_llm` to `GenerateRequest`; inject VLMConfig fields into profile dict
- `web/src/api/webProfileBuilder.ts` — add `inject_llm` to generate request type and mutation
- `web/src/pages/Profiles/WebBuilder.tsx` — add `injectLlm` state, `vlmReady` check, and checkbox UI

**Out of scope:** Changes to VLMConfig storage, global Config page, Android builder, or profile schema (already has the fields).

## 1. Backend

`GenerateRequest` in `web_profile_builder.py` gains one optional field:

```python
class GenerateRequest(BaseModel):
    name: str
    profile_url: str | None = None
    stable_sec: float = 3.0
    ready_timeout_sec: float = 15.0
    inject_llm: bool = False
```

In `generate_yaml()`, after the profile dict is assembled and before returning the YAML string, inject LLM credentials when requested:

```python
if req.inject_llm:
    vlm = await get_vlm_config(db)
    if not (vlm.base_url and vlm.model and vlm.api_key):
        raise HTTPException(status_code=400, detail={"error": "llm_config_incomplete"})
    profile["base_url"] = vlm.base_url
    profile["model"] = vlm.model
    profile["api_key"] = vlm.api_key
```

Fields are appended at the end of the profile dict. The `get_vlm_config` helper and `db` dependency are already present in the file (used by other endpoints).

**Error behaviour:** If `inject_llm=True` but VLMConfig is incomplete (any of the three fields missing), return HTTP 400 with `{"error": "llm_config_incomplete"}`. Frontend prevents this by disabling the checkbox when VLM is not configured.

## 2. Frontend API Layer

`web/src/api/webProfileBuilder.ts` — extend the generate request interface and mutation:

```typescript
interface GenerateRequest {
  name: string;
  profile_url?: string;
  stable_sec?: number;
  ready_timeout_sec?: number;
  inject_llm?: boolean;   // new
}
```

The `useGenerateWebProfile` mutation passes `inject_llm` through to the backend unchanged. No other API layer changes needed.

## 3. Frontend UI

`web/src/pages/Profiles/WebBuilder.tsx`:

**State and computed flag:**

```tsx
const { data: vlmConfig } = useVLMConfig();
const vlmReady = !!(vlmConfig?.base_url && vlmConfig?.model && vlmConfig?.api_key);
const [injectLlm, setInjectLlm] = useState(false);
```

**Checkbox placement:** Below the `stable_sec` slider, above the "生成 YAML" button:

```tsx
<Form.Item>
  <Checkbox
    checked={injectLlm}
    disabled={!vlmReady}
    onChange={(e) => setInjectLlm(e.target.checked)}
  >
    生成时注入 LLM 响应抽取配置
  </Checkbox>
  {!vlmReady && (
    <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
      请先在「配置」页填写 VLM 配置
    </div>
  )}
</Form.Item>
```

**Generate call:**

```tsx
generateProfile.mutateAsync({
  name,
  stable_sec: stableSec,
  ready_timeout_sec: readyTimeoutSec,
  inject_llm: injectLlm,
})
```

**`useVLMConfig` hook:** Already exists in the codebase (used by Android Builder and Config page). Import path: `../../api/config` or equivalent — verify before implementing.

## 4. Testing

**Backend unit test** (`tests/unit/test_web_profile_builder.py` or new file):
- `inject_llm=False` → YAML has no `base_url/model/api_key`
- `inject_llm=True` with complete VLMConfig → YAML contains all three fields
- `inject_llm=True` with incomplete VLMConfig → 400 `llm_config_incomplete`

**Frontend:** No new Vitest tests required — the checkbox is a thin UI wrapper over existing patterns already tested in the Android builder.

## Data Flow

```
WebBuilder UI
  └─ injectLlm checkbox (disabled if !vlmReady)
       └─ POST /web-profile-builder/sessions/{id}/generate
            body: { name, stable_sec, ready_timeout_sec, inject_llm }
                 └─ backend reads VLMConfig from KV store
                      └─ if inject_llm: appends base_url/model/api_key to profile dict
                           └─ returns YAML string
                                └─ WebBuilder displays in editable textarea
                                     └─ user saves via PUT /profiles/{name}
```
