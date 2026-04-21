# AutoAgent Test — Backend MVP

Backend service for batch testing of conversational AI products via OpenAI-compatible APIs.

## Status

**Backend only (Plan 1/5).** Web UI (Plan 2), Web GUI executor (Plan 3), and Android executor (Plan 4) are separate plans. API mode is the only executor currently wired.

## Requirements

- Python 3.10+
- Optional: Docker (later plan)

## Setup

```bash
cp .env.example .env
# Edit .env: set ADMIN_PASSWORD and JWT_SECRET (at least 32 chars)

pip install -e ".[dev]"
```

## Run

```bash
uvicorn autoagent.main:app --host 0.0.0.0 --port 8000 --reload
```

The admin user is bootstrapped on first start from `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

Health check: `curl http://localhost:8000/health`

## Quick start — run one prompt

```bash
# 1. Log in
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your_password"}' | jq -r .token)

# 2. Create a profile (YAML string inside a JSON body)
curl -X POST http://localhost:8000/api/v1/profiles/openai_gpt4 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"yaml": "name: openai_gpt4\nplatform: api\napi:\n  base_url: https://api.openai.com/v1\n  model: gpt-4o\n  api_key_env: OPENAI_KEY\n"}'

# 3. Set env var before running the service: export OPENAI_KEY=sk-...
# 4. Run a single-prompt sync test
curl -X POST http://localhost:8000/api/v1/tests/sync \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"id":"t1","prompts":["hello"],"mode":"api","target_profile":"openai_gpt4"}'
```

## Batch file formats

**JSONL** (recommended):

```jsonl
{"id": "t1", "prompts": ["hello"], "mode": "api", "target_profile": "openai_gpt4"}
{"id": "t2", "prompts": ["hi", "再说"], "mode": "api", "target_profile": "openai_gpt4", "new_session": false}
```

**JSON** — list of the same sample objects, or `{"samples": [...]}`

**CSV** — columns: `id,prompts,mode,target_profile,new_session,metadata`. Multi-turn prompts are joined by the Unicode Unit Separator `\u241f`.

## API reference

Auto-generated OpenAPI: `http://localhost:8000/docs`

Key endpoints:
- `POST /api/v1/auth/login` — get JWT
- `POST /api/v1/tests/sync` — single test, blocking
- `POST /api/v1/tests` — single test, async (returns `task_id`)
- `GET  /api/v1/tests/{task_id}` — poll async result
- `POST /api/v1/batches` — batch via JSON body
- `POST /api/v1/batches/upload` — batch via file upload (JSONL/JSON/CSV)
- `GET  /api/v1/batches/{id}` — batch detail + samples
- `GET  /api/v1/batches/{id}/results` — download JSONL
- `POST /api/v1/batches/{id}/cancel`
- `GET/POST/PUT/DELETE /api/v1/profiles/...`
- `POST /api/v1/profiles/validate`
- `GET/PUT /api/v1/config/vlm`, `/api/v1/config/defaults`

## Development

```bash
pytest              # run all tests
pytest -v           # verbose
pytest tests/unit   # unit only
ruff check .        # lint
ruff format .       # format
```

## Architecture

See:
- `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md`
- `docs/superpowers/plans/2026-04-21-plan-1-backend-mvp.md`

## Next plans

- Plan 2: React Web UI
- Plan 3: Web GUI Executor (Playwright)
- Plan 4: Android Executor (uiautomator2 + OCR)
- Plan 5: Packaging, monthly backups, Docker
