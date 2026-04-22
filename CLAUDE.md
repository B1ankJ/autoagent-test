# CLAUDE.md — AutoAgent Test

Guidance for Claude Code when working in this repo. Keep this file updated whenever plan status, architecture, or project conventions change.

## Project

AutoAgent Test — backend service for batch testing conversational AI products via OpenAI-compatible APIs. Python 3.10+, FastAPI, async SQLAlchemy (SQLite + aiosqlite), JWT auth, per-batch JSONL result files, YAML profile registry, webhook callbacks.

## Development status

Source of truth: `docs/superpowers/plans/` and `docs/superpowers/specs/`. Update this section when a plan completes or a new one starts.

- **Plan 1 — Backend MVP:** ✅ complete (tag `backend-mvp-v0.1.0`, 2026-04-22). All 25 tasks done. 66 tests passing, ruff clean.
- **Plan 2 — React Web UI:** in progress on branch/worktree `plan-2-web-ui` (`.worktrees/plan-2-web-ui`).
  Completed: Tasks 1-9 (scaffold, static mount, API client, auth/resource hooks, routing shell, login page, profiles list, profile edit, quick test page).
  Extra alignment completed: `/api/v1/profiles` now returns `[{name, platform}]`; frontend API types/hooks were corrected to match backend status enums and response shapes.
  Verification status: backend `python3.11 -m pytest -q` = 68 passed; frontend `cd web && pnpm test` = 7 passed; `pnpm build`, `pnpm lint`, and `pnpm format:check` passing.
  Next task: Task 10 (`StatusTag` + `Batches/List.tsx`), then Task 11 (`Batches/New.tsx`).
- **Plan 3 — Web GUI Executor (Playwright):** not started.
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

## Conventions

- **Python interpreter:** always use `python3.11` (not `python3`). Only 3.11 has the project's dependencies installed. This applies to `pytest`, `ruff`, `uvicorn`, and anything importing `autoagent`.
- **Tests:** `pytest-asyncio` in `asyncio_mode = "auto"`. Tests live under `tests/unit/` and `tests/integration/`. `pythonpath = ["src"]` is set in `pyproject.toml`.
- **Lint/format:** `ruff` with `line-length=100`, rules `E F I W B UP`. FastAPI routers have per-file-ignore for B008 (`Depends`/`Form`/`File` in defaults are idiomatic). Run `python3.11 -m ruff check .` and `python3.11 -m ruff format .`.
- **Exception chaining:** use `raise HTTPException(...) from e` when re-raising inside `except` (B904). Don't broaden handlers just to silence lint — narrow the `except` type instead.
- **Secrets in configs:** pending Plan 5 migration to `SecretStr`. Do NOT log or `repr(settings)` until then.
- **Result format:** one JSONL file per batch at `<data_dir>/results/<batch_id>.jsonl`. Writer is append-only and thread-safe.
- **Profiles:** YAML files under `<data_dir>/profiles/<name>.yaml`. Names restricted by allowlist regex in `profiles/registry.py::_path`.

## Common commands

```bash
python3.11 -m pytest -q                # run all tests
python3.11 -m pytest tests/unit -v     # unit only
python3.11 -m ruff check .             # lint
python3.11 -m ruff format .            # format
python3.11 -m uvicorn autoagent.main:app --reload   # run dev server
```

Required env for running: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `JWT_SECRET` (>=32 chars). See `.env.example`.

## When starting a new task in this repo

1. Check the plan file for the plan currently in progress (see "Development status").
2. Consult `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md` for architecture intent.
3. Match existing code style — most modules are small and single-purpose; prefer adding a new module over growing an existing one past ~200 lines.
4. Plan 5 work should start with the "secrets + auth hardening" task (see "Deferred work").
5. If continuing Plan 2, start in `.worktrees/plan-2-web-ui` and resume from Task 10 in `docs/superpowers/plans/2026-04-22-plan-2-web-ui.md`.
