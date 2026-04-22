# CLAUDE.md — AutoAgent Test

Guidance for Claude Code when working in this repo. Keep this file updated whenever plan status, architecture, or project conventions change.

## Project

AutoAgent Test — backend service for batch testing conversational AI products via OpenAI-compatible APIs. Python 3.10+, FastAPI, async SQLAlchemy (SQLite + aiosqlite), JWT auth, per-batch JSONL result files, YAML profile registry, webhook callbacks.

## Development status

Source of truth: `docs/superpowers/plans/` and `docs/superpowers/specs/`. Update this section when a plan completes or a new one starts.

- **Plan 1 — Backend MVP:** ✅ complete (tag `backend-mvp-v0.1.0`, 2026-04-22). All 25 tasks done. 66 tests passing, ruff clean.
- **Plan 2 — React Web UI:** ✅ complete (tag `web-ui-v0.2.0`, 2026-04-22). Single-binary deploy (FastAPI serves built SPA from `src/autoagent/static/` with SPA fallback). 2s polling via TanStack Query for batch progress (WebSocket deferred to Plan 3). 68 backend tests + 8 frontend tests green; browser smoke (login → profiles → dry_run batch → download → config → logout) passed.
  Important runtime note: this repo uses a `src/` layout. In a git worktree, run uvicorn with `--app-dir src` (or equivalent `PYTHONPATH=src`) so the current checkout is imported instead of an older editable install from another checkout.
- **Plan 3 — Web GUI Executor (Playwright):** feature-complete and in release-candidate verification. Playwright-backed `WebExecutor`, in-process event bus + SSE, screenshot APIs, web connectivity testing, `BatchDetail` SSE streaming, and `SampleDetail` screenshot/action-log UI are in the repo. Verification status: backend full suite `128 passed` when run outside the sandbox so Chromium can launch; backend fast suite `123 passed, 5 deselected`; frontend `pnpm test`, `pnpm lint`, `pnpm format:check`, and `pnpm build` all green. Remaining work is manual browser smoke, final doc pass, and release tagging.
- **Plan 4 — Android Executor (uiautomator2 + OCR):** not started.
- **Plan 5 — Polish (packaging, backups, Docker, security hardening):** not started. Has pre-accumulated task backlog — see "Deferred work" below.

## Deferred work for Plan 5

Recorded in auto-memory (`project_plan5_security.md`). Summary:

1. Migrate `admin_password` / `jwt_secret` in `src/autoagent/config/settings.py` to `pydantic.SecretStr`; update callsites in `auth/jwt.py` `_secret()` and `main.py` `lifespan()`.
2. Flip `default_verbose_logs` default from `True` → `False`.
3. JWT hardening in `auth/deps.py` + `auth/jwt.py`: narrow `except Exception` → `jwt.PyJWTError`; add `audience`/`issuer` claims; add `leeway=` for clock skew.
4. Login endpoint (`api/auth.py`) timing side-channel: always run dummy `verify_password` on unknown-user path to prevent username enumeration.

## Layout

```
src/autoagent/
  api/          FastAPI routers: auth, profiles, tests, batches, config, devices
  auth/         JWT + password hashing + FastAPI deps
  config/       Pydantic Settings (env-backed)
  executors/    base Executor + API (OpenAI-compatible) executor
  loaders/      JSONL/JSON/CSV batch file loaders
  models/       Pydantic API schemas + SQLAlchemy ORM
  profiles/     profile Pydantic discriminated union + YAML registry
  results/      per-batch JSONL result writer (thread-safe)
  scheduler/    async BatchScheduler with per-batch concurrency
  storage/      async SQLAlchemy CRUD (batches, samples, users, kv config)
  webhooks/     async webhook sender with exponential backoff
  main.py       FastAPI app + lifespan (DB init + admin bootstrap + CORS)
tests/
  unit/         14 unit test files
  integration/  7 integration test files (httpx AsyncClient against the app)
docs/superpowers/{specs,plans}/   Design specs and implementation plans
```

## Frontend (Plan 2)

- `web/` — Vite + React + TypeScript + AntD 5. Built into `src/autoagent/static/`.
- State: TanStack Query v5. Batch detail pages now use `useBatchStream` over SSE for live progress; some older list views still use standard query polling where streaming is not needed. Token storage: `localStorage["autoagent_token"]`.
- Dev: `cd web && pnpm dev` (port 5173, proxies `/api/v1` to 8000).
- Build: `cd web && pnpm build` (writes to `src/autoagent/static/`).
- Test: `cd web && pnpm test` (Vitest + RTL).

## Conventions

- **Python interpreter:** always use `python3.11` (not `python3`). Only 3.11 has the project's dependencies installed. This applies to `pytest`, `ruff`, `uvicorn`, and anything importing `autoagent`.
- **Tests:** `pytest-asyncio` in `asyncio_mode = "auto"`. Tests live under `tests/unit/` and `tests/integration/`. `pythonpath = ["src"]` is set in `pyproject.toml`.
- **Lint/format:** `ruff` with `line-length=100`, rules `E F I W B UP`. FastAPI routers have per-file-ignore for B008 (`Depends`/`Form`/`File` in defaults are idiomatic). Run `python3.11 -m ruff check .` and `python3.11 -m ruff format .`.
- **Exception chaining:** use `raise HTTPException(...) from e` when re-raising inside `except` (B904). Don't broaden handlers just to silence lint — narrow the `except` type instead.
- **Secrets in configs:** pending Plan 5 migration to `SecretStr`. Do NOT log or `repr(settings)` until then.
- **Result format:** one JSONL file per batch at `<data_dir>/results/<batch_id>.jsonl`. Writer is append-only and thread-safe.
- **Profiles:** YAML files under `<data_dir>/profiles/<name>.yaml`. Names restricted by allowlist regex in `profiles/registry.py::_path`.
- **Playwright verification:** in this environment, real-browser pytest cases may need to run outside the sandbox because Chromium launch is blocked inside the sandbox. When verifying Plan 3 locally, use `python3.11 -m pytest -v` outside the sandbox for the full suite, or `python3.11 -m pytest -q -m "not playwright"` for the fast subset.

## Common commands

```bash
python3.11 -m pytest -q                # run all tests
python3.11 -m pytest -q -m "not playwright"   # skip real-browser tests
python3.11 -m pytest tests/unit -v     # unit only
python3.11 -m ruff check .             # lint
python3.11 -m ruff format .            # format
python3.11 -m playwright install chromium     # one-time: download Chromium
python3.11 -m uvicorn --app-dir src autoagent.main:app --reload   # run dev server
cd web && pnpm dev                     # frontend dev server (5173)
cd web && pnpm build                   # build UI into src/autoagent/static/
cd web && pnpm test                    # frontend unit tests
cd web && pnpm lint                    # frontend lint
```

Required env for running: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `JWT_SECRET` (>=32 chars). See `.env.example`.

Optional env: `CORS_ORIGINS` (comma-separated). Default empty → `CORSMiddleware` not mounted (SPA ships same-origin). Set only for cross-origin dev setups, e.g. `CORS_ORIGINS=http://localhost:5173`.

## When starting a new task in this repo

1. Check the plan file for the plan currently in progress (see "Development status").
2. Consult `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md` for architecture intent.
3. Match existing code style — most modules are small and single-purpose; prefer adding a new module over growing an existing one past ~200 lines.
4. Plan 5 work should start with the "secrets + auth hardening" task (see "Deferred work").
5. Plan 2 is complete and tagged `web-ui-v0.2.0`; the next active plan is Plan 3 (Web GUI Executor).
