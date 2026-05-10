# Static API Key Authentication Design

**Date:** 2026-05-10
**Status:** Approved

## Motivation

Current bearer authentication is JWT-only. That works for the web UI and short-lived scripted access, but it is inconvenient for stable automation because the caller must first log in and then refresh an expiring token. The goal of this change is to add one optional, long-lived static bearer key that can be configured in the environment and accepted by every existing bearer-protected backend endpoint.

This is intentionally not a token-management system. The first version is a single global key configured by environment variable, validated server-side, and treated as the admin identity when presented.

## Scope

- Add one optional static bearer key via environment variable
- Accept that key on all existing bearer-protected endpoints
- Keep existing JWT bearer authentication fully working
- Treat the static key as authenticated user `admin`
- Reuse one shared bearer-resolution implementation across `/api/v1/*` and `/v1/*`
- Preserve current endpoint-specific error shapes

## Out Of Scope

- Multiple API keys
- API-key creation, rotation, or revocation endpoints
- Database persistence of API keys
- Per-key metadata, scopes, or audit trails
- Replacing JWT entirely
- UI for managing the key

## High-Level Approach

Introduce a shared bearer-resolution layer that accepts either:

1. the configured static key
2. a valid JWT

The shared layer returns the authenticated subject string. Route adapters continue to own response formatting:

- `/api/v1/*` keeps existing `HTTPException` shapes
- `/v1/chat/completions` keeps OpenAI-style `{"error": ...}` shapes

This keeps the authentication source consistent without duplicating JWT and static-key logic across multiple route modules.

## Authentication Contract

### Configuration

Add a new optional setting:

- `STATIC_API_KEY: str | None`

Behavior:

- If not configured, system behavior is unchanged
- If configured, any request with `Authorization: Bearer <STATIC_API_KEY>` is authenticated as `admin`

### Bearer Resolution Order

All bearer-protected endpoints should resolve credentials in this order:

1. Missing bearer token -> authentication failure
2. Bearer token matches configured static key -> authenticated subject is `admin`
3. Otherwise try JWT decode
4. Valid JWT with string `sub` -> authenticated subject is `sub`
5. Invalid JWT -> authentication failure

### Identity Mapping

When the static key is used successfully:

- authenticated subject = `admin`

This is intentionally simple. It avoids introducing a second principal type or configurable subject mapping in the first version.

## Code Boundaries

### Shared Bearer Resolver

Recommended new module:

- `src/autoagent/auth/bearer.py`

Responsibilities:

- Read the configured static key
- Compare the presented bearer token against it
- Fall back to JWT decoding
- Return the authenticated subject
- Raise domain-level auth exceptions rather than route-specific HTTP errors

This module should not know about FastAPI route response formatting.

### Existing FastAPI Dependency

File:

- `src/autoagent/auth/deps.py`

Responsibilities after the change:

- parse `HTTPBearer` credentials
- call the shared bearer resolver
- translate resolver failures into existing `HTTPException` responses for `/api/v1/*`

### OpenAI Compatibility Route

File:

- `src/autoagent/api/openai_compat.py`

Responsibilities after the change:

- reuse the same shared bearer resolver
- translate auth failures into OpenAI-style `invalid_api_key` responses

This avoids having `/api/v1/*` and `/v1/*` drift on which credentials they accept.

## Security Notes

- Compare the configured static key using `hmac.compare_digest(...)`
- Never log the configured static key
- Never echo the configured static key in any response
- If the key is leaked, the operational recovery path is:
  - change `STATIC_API_KEY`
  - restart the service

This design intentionally makes the key long-lived, so it must be treated as a high-sensitivity secret equivalent to admin credentials.

## Error Behavior

### `/api/v1/*`

Preserve current error shapes:

- missing bearer -> `401 Missing bearer token`
- invalid JWT and static key mismatch -> `401 Invalid or expired token`
- malformed authenticated identity -> `401 Malformed token`

Even though the static key is not a JWT, callers should still see the existing route-family error surface.

### `/v1/chat/completions`

Preserve OpenAI-style auth failures:

```json
{
  "error": {
    "message": "Invalid or expired token",
    "type": "invalid_request_error",
    "code": "invalid_api_key"
  }
}
```

The route may vary the message text slightly for missing vs invalid credentials, but `code` should remain `invalid_api_key`.

## Compatibility Impact

- Existing web login flow continues to work unchanged
- Existing JWT-based scripts continue to work unchanged
- New static-key-based scripts can call:
  - `/api/v1/tests/sync`
  - `/api/v1/batches`
  - `/api/v1/profiles`
  - `/v1/chat/completions`
  - and any other bearer-protected endpoint

No endpoint request schema changes are required. The change is purely in bearer validation.

## Verification Plan

Minimum verification set:

1. `STATIC_API_KEY` not configured
   - existing JWT-authenticated `/api/v1/*` requests still work

2. `STATIC_API_KEY` configured
   - `Authorization: Bearer <STATIC_API_KEY>` succeeds on `/api/v1/tests/sync`

3. `STATIC_API_KEY` configured
   - `Authorization: Bearer <STATIC_API_KEY>` succeeds on `/v1/chat/completions`

4. Wrong key
   - `/api/v1/*` returns the existing 401 shape
   - `/v1/*` returns OpenAI-style `invalid_api_key`

5. JWT still works while static key is configured

## Example Usage

With `STATIC_API_KEY` configured in the environment:

```bash
curl -s -X POST 'http://localhost:8000/api/v1/tests/sync' \
  -H "Authorization: Bearer $STATIC_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"id":"t1","prompts":["你好，介绍一下自己"],"mode":"gui_android","target_profile":"nxb","new_session":false}'
```

And for OpenAI-compatible callers:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="<STATIC_API_KEY>",
)
```
