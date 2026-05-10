# Static API Key Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one optional environment-configured static bearer API key that works across all bearer-protected endpoints while preserving existing JWT authentication and existing route-specific error shapes.

**Architecture:** Introduce a shared bearer-resolution layer that authenticates either the configured static key or a JWT and returns the authenticated subject. Existing route families continue to own their own error formatting: `/api/v1/*` keeps `HTTPException` behavior and `/v1/chat/completions` keeps OpenAI-style `{"error": ...}` behavior.

**Tech Stack:** FastAPI, Pydantic settings, existing JWT helpers, `hmac.compare_digest`, pytest, pytest-httpx, ruff.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/autoagent/config/settings.py` | Modify | Add optional `static_api_key` setting |
| `src/autoagent/auth/bearer.py` | Create | Shared bearer-resolution logic and domain auth errors |
| `src/autoagent/auth/deps.py` | Modify | Reuse shared bearer resolver for `/api/v1/*` dependencies |
| `src/autoagent/api/openai_compat.py` | Modify | Reuse shared bearer resolver for OpenAI-style auth failures |
| `tests/unit/test_bearer_auth.py` | Create | Unit tests for static key/JWT resolution rules |
| `tests/integration/test_auth_static_api_key.py` | Create | Integration tests for `/api/v1/*` with static key |
| `tests/integration/test_openai_chat_completions.py` | Modify | Add OpenAI compat auth coverage with static key |
| `README.md` | Modify | Document `STATIC_API_KEY` usage |

---

### Task 1: Settings + Shared Bearer Resolver

**Files:**
- Modify: `src/autoagent/config/settings.py`
- Create: `src/autoagent/auth/bearer.py`
- Test: `tests/unit/test_bearer_auth.py`

- [ ] **Step 1: Write failing unit tests for static key, JWT fallback, and invalid credentials**

```python
# tests/unit/test_bearer_auth.py
from __future__ import annotations

import pytest

from autoagent.auth import bearer as mod


def test_resolve_bearer_subject_accepts_static_api_key(monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: type("S", (), {"static_api_key": "permanent-key"})())

    subject = mod.resolve_bearer_subject("permanent-key")

    assert subject == "admin"


def test_resolve_bearer_subject_falls_back_to_jwt(monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: type("S", (), {"static_api_key": "permanent-key"})())
    monkeypatch.setattr(mod, "decode_token", lambda token: {"sub": "alice"} if token == "jwt-token" else {})

    subject = mod.resolve_bearer_subject("jwt-token")

    assert subject == "alice"


def test_resolve_bearer_subject_rejects_missing_subject(monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: type("S", (), {"static_api_key": None})())
    monkeypatch.setattr(mod, "decode_token", lambda token: {})

    with pytest.raises(mod.BearerAuthError) as exc:
        mod.resolve_bearer_subject("jwt-token")

    assert exc.value.reason == "malformed"


def test_resolve_bearer_subject_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(mod, "get_settings", lambda: type("S", (), {"static_api_key": "permanent-key"})())

    def _raise(_token: str):
        raise RuntimeError("bad jwt")

    monkeypatch.setattr(mod, "decode_token", _raise)

    with pytest.raises(mod.BearerAuthError) as exc:
        mod.resolve_bearer_subject("wrong-token")

    assert exc.value.reason == "invalid"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.11 -m pytest tests/unit/test_bearer_auth.py -q`

Expected: FAIL because `autoagent.auth.bearer` and `static_api_key` do not exist yet.

- [ ] **Step 3: Add the setting and shared bearer resolver**

```python
# src/autoagent/config/settings.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_username: str = Field(default="admin", min_length=1)
    admin_password: str = Field(default="admin123456")
    jwt_secret: str = Field(default="dev-secret-key-32-chars-minimum-length", min_length=32)
    jwt_expires_hours: int = 24
    static_api_key: str | None = None
```

```python
# src/autoagent/auth/bearer.py
from __future__ import annotations

import hmac
from dataclasses import dataclass

from autoagent.auth.jwt import decode_token
from autoagent.config.settings import get_settings


@dataclass(frozen=True)
class BearerAuthError(Exception):
    reason: str  # "missing" | "invalid" | "malformed"


def resolve_bearer_subject(token: str) -> str:
    settings = get_settings()
    static_api_key = settings.static_api_key
    if static_api_key and hmac.compare_digest(token, static_api_key):
        return settings.admin_username

    try:
        payload = decode_token(token)
    except Exception as exc:  # noqa: BLE001
        raise BearerAuthError("invalid") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise BearerAuthError("malformed")
    return subject
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `python3.11 -m pytest tests/unit/test_bearer_auth.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/config/settings.py src/autoagent/auth/bearer.py tests/unit/test_bearer_auth.py
git commit -m "feat: add shared static api key bearer resolver"
```

---

### Task 2: `/api/v1/*` Dependency Integration

**Files:**
- Modify: `src/autoagent/auth/deps.py`
- Test: `tests/integration/test_auth_static_api_key.py`

- [ ] **Step 1: Write failing integration tests for static key on existing API routes**

```python
# tests/integration/test_auth_static_api_key.py
from __future__ import annotations

import yaml
import pytest
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("STATIC_API_KEY", "permanent-key")
    from autoagent.config.settings import get_settings

    get_settings.cache_clear()
    await init_db()
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    get_settings.cache_clear()


async def test_static_api_key_can_call_tests_sync(client: AsyncClient, httpx_mock: HTTPXMock) -> None:
    save_profile_yaml(
        "p_api",
        yaml.safe_dump(
            {
                "name": "p_api",
                "platform": "api",
                "api": {
                    "base_url": "https://api.example.com/v1",
                    "model": "m",
                    "api_key": "OPENAI_TEST_KEY",
                },
            }
        ),
    )
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "hi!"}}]},
    )

    response = await client.post(
        "/api/v1/tests/sync",
        headers={"Authorization": "Bearer permanent-key"},
        json={
            "id": "t1",
            "prompts": ["hello"],
            "mode": "api",
            "target_profile": "p_api",
        },
    )

    assert response.status_code == 200
    assert response.json()["responses"] == ["hi!"]


async def test_wrong_static_api_key_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/profiles",
        headers={"Authorization": "Bearer wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.11 -m pytest tests/integration/test_auth_static_api_key.py -q`

Expected: FAIL because `/api/v1/*` does not accept the static key yet.

- [ ] **Step 3: Wire the shared resolver into `require_user()`**

```python
# src/autoagent/auth/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from autoagent.auth.bearer import BearerAuthError, resolve_bearer_subject

_bearer = HTTPBearer(auto_error=False)


async def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        return resolve_bearer_subject(creds.credentials)
    except BearerAuthError as exc:
        if exc.reason == "malformed":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
```

- [ ] **Step 4: Run the integration tests to verify they pass**

Run: `python3.11 -m pytest tests/integration/test_auth_static_api_key.py tests/integration/test_tests_endpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/auth/deps.py tests/integration/test_auth_static_api_key.py
git commit -m "feat: accept static api key on api routes"
```

---

### Task 3: OpenAI Compatibility Auth Integration

**Files:**
- Modify: `src/autoagent/api/openai_compat.py`
- Modify: `tests/integration/test_openai_chat_completions.py`

- [ ] **Step 1: Write failing integration coverage for static key on `/v1/chat/completions`**

```python
# add to tests/integration/test_openai_chat_completions.py
async def test_chat_completions_accepts_static_api_key(client: AsyncClient, httpx_mock: HTTPXMock, monkeypatch) -> None:
    monkeypatch.setenv("STATIC_API_KEY", "permanent-key")
    from autoagent.config.settings import get_settings

    get_settings.cache_clear()
    save_profile_yaml(
        "p_api",
        yaml.safe_dump(
            {
                "name": "p_api",
                "platform": "api",
                "api": {
                    "base_url": "https://api.example.com/v1",
                    "model": "m",
                    "api_key": "OPENAI_TEST_KEY",
                },
            }
        ),
    )
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "hi!"}}]},
    )

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer permanent-key"},
        json={"model": "p_api", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hi!"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.11 -m pytest tests/integration/test_openai_chat_completions.py -q`

Expected: FAIL because `/v1/chat/completions` still only accepts JWT.

- [ ] **Step 3: Reuse the shared bearer resolver in the OpenAI route**

```python
# src/autoagent/api/openai_compat.py
from autoagent.auth.bearer import BearerAuthError, resolve_bearer_subject


def _require_openai_bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise OpenAICompatError(
            status_code=401,
            message="Missing bearer token",
            error_type="invalid_request_error",
            code="invalid_api_key",
        )
    try:
        return resolve_bearer_subject(token)
    except BearerAuthError as exc:
        message = "Malformed token" if exc.reason == "malformed" else "Invalid or expired token"
        raise OpenAICompatError(
            status_code=401,
            message=message,
            error_type="invalid_request_error",
            code="invalid_api_key",
        ) from exc
```

- [ ] **Step 4: Run integration tests to verify static key and JWT both work**

Run: `python3.11 -m pytest tests/integration/test_openai_chat_completions.py tests/integration/test_auth_endpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/api/openai_compat.py tests/integration/test_openai_chat_completions.py
git commit -m "feat: accept static api key on openai compat route"
```

---

### Task 4: Documentation And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with `STATIC_API_KEY` configuration and usage**

Add a section like:

```md
## Static API key

You can configure a long-lived bearer key for automation:

```bash
export STATIC_API_KEY='your-long-lived-key'
```

Once configured and the service is restarted, the key can be used on any bearer-protected endpoint:

```bash
curl -s -X POST 'http://localhost:8000/api/v1/tests/sync' \
  -H "Authorization: Bearer $STATIC_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"id":"t1","prompts":["你好，介绍一下自己"],"mode":"gui_android","target_profile":"nxb","new_session":false}'
```

It also works with the OpenAI-compatible endpoint:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-long-lived-key",
)
```

Notes:

- the static key is authenticated as `admin`
- JWT login still works and remains supported
- to rotate the key, change `STATIC_API_KEY` and restart the service
```

- [ ] **Step 2: Run targeted backend verification**

Run: `python3.11 -m pytest tests/unit/test_bearer_auth.py tests/integration/test_auth_static_api_key.py tests/integration/test_openai_chat_completions.py tests/integration/test_tests_endpoints.py tests/integration/test_auth_endpoints.py -q`

Expected: PASS.

- [ ] **Step 3: Run fast backend regression suite**

Run: `python3.11 -m pytest -q -m "not playwright and not android and not slow"`

Expected: PASS.

- [ ] **Step 4: Run lint on changed files**

Run: `python3.11 -m ruff check src/autoagent/auth/bearer.py src/autoagent/auth/deps.py src/autoagent/api/openai_compat.py src/autoagent/config/settings.py tests/unit/test_bearer_auth.py tests/integration/test_auth_static_api_key.py tests/integration/test_openai_chat_completions.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add static api key usage"
```
