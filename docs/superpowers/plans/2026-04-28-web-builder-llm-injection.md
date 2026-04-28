# Web Builder LLM Credential Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "inject LLM config" checkbox to the Web Profile Builder so that users can opt to include LLM response extraction credentials (`base_url`, `model`, `api_key`) from the global VLMConfig directly into the generated YAML.

**Architecture:** Three files change in parallel layers: (1) backend `GenerateRequest` gets `inject_llm: bool = False` and the endpoint reads VLMConfig from the KV store when true; (2) the frontend API hook (`webProfileBuilder.ts`) passes `inject_llm` through to the backend; (3) the frontend UI component (`WebBuilder.tsx`) adds `injectLlm` state, reads `useVLM()` to compute `vlmReady`, and renders a checkbox in the generate card. This mirrors the existing Android builder pattern exactly.

**Tech Stack:** Python 3.11, FastAPI, pydantic v2, React 18, TypeScript, Ant Design 5, TanStack Query v5, pytest-asyncio, httpx AsyncClient.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `src/autoagent/api/web_profile_builder.py` |
| Modify | `web/src/api/webProfileBuilder.ts` |
| Modify | `web/src/pages/Profiles/WebBuilder.tsx` |
| Create/modify | `tests/integration/test_web_profile_builder_endpoints.py` |

---

### Task 1: Backend — add `inject_llm` to `GenerateRequest` and `generate_yaml()`

**Files:**
- Modify: `src/autoagent/api/web_profile_builder.py:307-312` (GenerateRequest), `:416-469` (generate_yaml)
- Modify: `tests/integration/test_web_profile_builder_endpoints.py`

**Context:** `get_config` and `VLMConfig` are already imported in the Android builder (`src/autoagent/api/profile_builder.py` lines 42–45). We need to add the same imports to `web_profile_builder.py`. The `generate_yaml` endpoint builds a `profile` dict and returns `yaml.safe_dump(profile, ...)`. We append `base_url`, `model`, `api_key` to that dict when `inject_llm=True`.

- [ ] **Step 1: Write failing integration tests**

Open `tests/integration/test_web_profile_builder_endpoints.py`. Add these tests at the end of the file (or create the file if it doesn't exist — check first with `ls tests/integration/`):

```python
# ── inject_llm tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_inject_llm_false_omits_llm_fields(
    client: AsyncClient, auth_headers: dict
):
    """inject_llm=False (default) → YAML has no LLM fields."""
    # Store a VLMConfig so it's available
    await client.put(
        "/api/v1/config/vlm",
        json={"base_url": "https://api/v1", "model": "m", "api_key": "k"},
        headers=auth_headers,
    )

    # Create a minimal web builder session via the in-memory store directly
    from autoagent.api.web_profile_builder import _sessions
    import uuid
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = {
        "id": sid,
        "url": "https://example.com",
        "channel": "chromium",
        "headless": False,
        "user_data_dir": None,
        "pw": None,
        "context": None,
        "page": None,
        "selections": {
            "input": {"selector": "[role='textbox']", "info": {}},
            "send": {"selector": "[role='textbox']", "info": {}, "send_type": "keyboard", "keyboard_key": "Enter"},
            "response": {"selector": ".reply", "info": {}},
        },
    }

    try:
        resp = await client.post(
            f"/api/v1/web-profile-builder/sessions/{sid}/generate",
            json={"name": "test_profile", "inject_llm": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        import yaml as yaml_lib
        profile = yaml_lib.safe_load(resp.json()["yaml"])
        assert "base_url" not in profile
        assert "model" not in profile
        assert "api_key" not in profile
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_generate_inject_llm_true_includes_llm_fields(
    client: AsyncClient, auth_headers: dict
):
    """inject_llm=True with complete VLMConfig → YAML contains all three LLM fields."""
    await client.put(
        "/api/v1/config/vlm",
        json={"base_url": "https://api/v1", "model": "my-model", "api_key": "sk-test"},
        headers=auth_headers,
    )

    from autoagent.api.web_profile_builder import _sessions
    import uuid
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = {
        "id": sid,
        "url": "https://example.com",
        "channel": "chromium",
        "headless": False,
        "user_data_dir": None,
        "pw": None,
        "context": None,
        "page": None,
        "selections": {
            "input": {"selector": "[role='textbox']", "info": {}},
            "send": {"selector": "[role='textbox']", "info": {}, "send_type": "keyboard", "keyboard_key": "Enter"},
            "response": {"selector": ".reply", "info": {}},
        },
    }

    try:
        resp = await client.post(
            f"/api/v1/web-profile-builder/sessions/{sid}/generate",
            json={"name": "test_profile", "inject_llm": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        import yaml as yaml_lib
        profile = yaml_lib.safe_load(resp.json()["yaml"])
        assert profile["base_url"] == "https://api/v1"
        assert profile["model"] == "my-model"
        assert profile["api_key"] == "sk-test"
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_generate_inject_llm_true_incomplete_vlm_returns_400(
    client: AsyncClient, auth_headers: dict
):
    """inject_llm=True with missing VLMConfig → 400 llm_config_incomplete."""
    # Clear VLM config
    await client.put(
        "/api/v1/config/vlm",
        json={"base_url": None, "model": None, "api_key": None},
        headers=auth_headers,
    )

    from autoagent.api.web_profile_builder import _sessions
    import uuid
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = {
        "id": sid,
        "url": "https://example.com",
        "channel": "chromium",
        "headless": False,
        "user_data_dir": None,
        "pw": None,
        "context": None,
        "page": None,
        "selections": {
            "input": {"selector": "[role='textbox']", "info": {}},
            "send": {"selector": "[role='textbox']", "info": {}, "send_type": "keyboard", "keyboard_key": "Enter"},
            "response": {"selector": ".reply", "info": {}},
        },
    }

    try:
        resp = await client.post(
            f"/api/v1/web-profile-builder/sessions/{sid}/generate",
            json={"name": "test_profile", "inject_llm": True},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "llm_config_incomplete"
    finally:
        _sessions.pop(sid, None)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/integration/test_web_profile_builder_endpoints.py::test_generate_inject_llm_false_omits_llm_fields tests/integration/test_web_profile_builder_endpoints.py::test_generate_inject_llm_true_includes_llm_fields tests/integration/test_web_profile_builder_endpoints.py::test_generate_inject_llm_true_incomplete_vlm_returns_400 -v
```

Expected: FAIL — `inject_llm` field not recognised on `GenerateRequest`, or behaviour does not match.

- [ ] **Step 3: Update `web_profile_builder.py`**

**Add imports** at the top of `src/autoagent/api/web_profile_builder.py` (after the existing imports, before `_log = ...`):

```python
from autoagent.models.api import VLMConfig
from autoagent.storage.configs import get_config
```

**Update `GenerateRequest`** (replace lines 307-311):

```python
class GenerateRequest(BaseModel):
    name: str
    profile_url: str | None = None  # override if navigated away
    stable_sec: float = 3.0
    ready_timeout_sec: float = 15.0
    inject_llm: bool = False
```

**Update `generate_yaml()`** — add LLM injection block after the `if s["user_data_dir"]:` block (after line 467, before the `return` statement):

```python
    if req.inject_llm:
        raw_vlm = await get_config("vlm")
        vlm = VLMConfig.model_validate(raw_vlm) if raw_vlm else VLMConfig()
        if not (vlm.base_url and vlm.model and vlm.api_key):
            raise HTTPException(status_code=400, detail={"error": "llm_config_incomplete"})
        profile["base_url"] = vlm.base_url
        profile["model"] = vlm.model
        profile["api_key"] = vlm.api_key

    return {"yaml": yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)}
```

The full `generate_yaml` function should now look like this at its end:

```python
    if s["user_data_dir"]:
        profile["browser"]["user_data_dir"] = s["user_data_dir"]

    if req.inject_llm:
        raw_vlm = await get_config("vlm")
        vlm = VLMConfig.model_validate(raw_vlm) if raw_vlm else VLMConfig()
        if not (vlm.base_url and vlm.model and vlm.api_key):
            raise HTTPException(status_code=400, detail={"error": "llm_config_incomplete"})
        profile["base_url"] = vlm.base_url
        profile["model"] = vlm.model
        profile["api_key"] = vlm.api_key

    return {"yaml": yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3.11 -m pytest tests/integration/test_web_profile_builder_endpoints.py::test_generate_inject_llm_false_omits_llm_fields tests/integration/test_web_profile_builder_endpoints.py::test_generate_inject_llm_true_includes_llm_fields tests/integration/test_web_profile_builder_endpoints.py::test_generate_inject_llm_true_incomplete_vlm_returns_400 -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Run fast suite**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

Expected: all tests pass, no regressions.

- [ ] **Step 6: Lint**

```bash
python3.11 -m ruff check src/autoagent/api/web_profile_builder.py
python3.11 -m ruff format src/autoagent/api/web_profile_builder.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/api/web_profile_builder.py \
        tests/integration/test_web_profile_builder_endpoints.py
git commit -m "feat: add inject_llm to web profile builder generate endpoint"
```

---

### Task 2: Frontend API layer — add `inject_llm` to `useGenerateWebProfile`

**Files:**
- Modify: `web/src/api/webProfileBuilder.ts:98-113`

- [ ] **Step 1: Update `useGenerateWebProfile` mutation body type**

In `web/src/api/webProfileBuilder.ts`, replace the `useGenerateWebProfile` function (lines 98-113) with:

```typescript
export function useGenerateWebProfile(sessionId: string) {
  return useMutation({
    mutationFn: async (body: {
      name: string
      profile_url?: string
      stable_sec?: number
      ready_timeout_sec?: number
      inject_llm?: boolean
    }) =>
      (
        await client.post<{ yaml: string }>(
          `/web-profile-builder/sessions/${sessionId}/generate`,
          body,
        )
      ).data,
  })
}
```

- [ ] **Step 2: Run frontend type check and tests**

```bash
cd web && pnpm build 2>&1 | tail -20
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/api/webProfileBuilder.ts
git commit -m "feat: add inject_llm to useGenerateWebProfile hook"
```

---

### Task 3: Frontend UI — add VLM checkbox to WebBuilder

**Files:**
- Modify: `web/src/pages/Profiles/WebBuilder.tsx`

**Context:**
- `useVLM` is the hook at `web/src/api/config.ts:12`. Import path from WebBuilder.tsx: `'../../api/config'`.
- `Checkbox` is from `antd` — add it to the existing import list.
- The checkbox goes inside the "生成 YAML" Card, between the profile name `Input` and the "生成 YAML 草稿" `Button`.
- `vlmReady` is `!!(vlm?.base_url && vlm?.model && vlm?.api_key)` — same as Android Builder line 384.

- [ ] **Step 1: Add `Checkbox` to antd imports and `useVLM` import**

In `web/src/pages/Profiles/WebBuilder.tsx`, update the antd import (line 1) to add `Checkbox`:

```typescript
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  message,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
```

Add `useVLM` import after the existing `webProfileBuilder` imports (around line 29):

```typescript
import { useVLM } from '../../api/config'
```

- [ ] **Step 2: Add state and computed values inside `WebBuilder()`**

Inside the `WebBuilder` component function, after the existing `const closeSession = useCloseWebBuilderSession()` line (around line 75), add:

```typescript
  const { data: vlm } = useVLM()
  const vlmReady = !!(vlm?.base_url && vlm?.model && vlm?.api_key)
  const [injectLlm, setInjectLlm] = useState(false)
```

- [ ] **Step 3: Update `handleGenerate` to pass `inject_llm`**

Replace the `handleGenerate` function (lines 115-130):

```typescript
  async function handleGenerate() {
    if (!profileName.trim()) {
      message.warning('请先填写 Profile 名称')
      return
    }
    try {
      const result = await generateProfile.mutateAsync({
        name: profileName.trim(),
        stable_sec: 5,
        ready_timeout_sec: 15,
        inject_llm: injectLlm,
      })
      setGeneratedYaml(result.yaml)
    } catch (e: unknown) {
      message.error(`生成失败: ${(e as Error).message}`)
    }
  }
```

- [ ] **Step 4: Add checkbox UI to the generate Card**

In the "生成 YAML" Card (around line 319), replace the `<Space direction="vertical" ...>` content with:

```tsx
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input
                  placeholder="Profile 名称（如 my_site）"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                />
                <div>
                  <Tooltip title={vlmReady ? '' : '请先在「配置」页填写完整 VLM 凭据'}>
                    <Checkbox
                      checked={injectLlm}
                      disabled={!vlmReady}
                      onChange={(e) => setInjectLlm(e.target.checked)}
                    >
                      生成时注入 LLM 响应抽取配置
                    </Checkbox>
                  </Tooltip>
                </div>
                <Button
                  type="primary"
                  block
                  disabled={!requiredDone}
                  loading={generateProfile.isPending}
                  onClick={handleGenerate}
                >
                  生成 YAML 草稿
                </Button>
                {!requiredDone && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    需先选择：输入框、发送、回复容器
                  </Text>
                )}
              </Space>
```

- [ ] **Step 5: Build and verify**

```bash
cd web && pnpm build 2>&1 | tail -20
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 6: Run frontend tests and lint**

```bash
cd web && pnpm test && pnpm lint
```

Expected: all tests pass, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/Profiles/WebBuilder.tsx
git commit -m "feat: add LLM injection checkbox to web profile builder UI"
```

---

## Verification

After all tasks complete, run the full fast backend suite and frontend checks:

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
cd web && pnpm test && pnpm lint && pnpm build
```

Expected: all tests pass, build clean.

**Manual check:** Start the dev server (`python3.11 -m uvicorn --app-dir src autoagent.main:app --reload` + `cd web && pnpm dev`), go to Profiles → Web Builder, start a session, pick the required fields, and verify the checkbox appears (disabled if VLM not configured in Config page, enabled once configured). Generate a profile with the checkbox checked and confirm `base_url`, `model`, `api_key` appear in the generated YAML.
