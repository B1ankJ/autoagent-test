# CLAUDE.md — AutoAgent Test

Guidance for Claude Code when working in this repo. Keep this file updated whenever plan status, architecture, or project conventions change.

## Project

AutoAgent Test — backend service for batch testing conversational AI products via OpenAI-compatible APIs. Python 3.10+, FastAPI, async SQLAlchemy (SQLite + aiosqlite), JWT auth, per-batch JSONL result files, YAML profile registry, webhook callbacks.

## Development status

Source of truth: `docs/superpowers/plans/` and `docs/superpowers/specs/`. Update this section when a plan completes or a new one starts.

- **Plan 1 — Backend MVP:** ✅ complete (tag `backend-mvp-v0.1.0`, 2026-04-22). All 25 tasks done. 66 tests passing, ruff clean.
- **Plan 2 — React Web UI:** ✅ complete (tag `web-ui-v0.2.0`, 2026-04-22). Single-binary deploy (FastAPI serves built SPA from `src/autoagent/static/` with SPA fallback). 2s polling via TanStack Query for batch progress (WebSocket deferred to Plan 3). 68 backend tests + 8 frontend tests green; browser smoke (login → profiles → dry_run batch → download → config → logout) passed.
  Important runtime note: this repo uses a `src/` layout. In a git worktree, run uvicorn with `--app-dir src` (or equivalent `PYTHONPATH=src`) so the current checkout is imported instead of an older editable install from another checkout.
- **Plan 3 — Web GUI Executor (Playwright):** ✅ complete (tag `web-gui-executor-v0.3.0`, 2026-04-22). Playwright-backed `WebExecutor`, in-process event bus + SSE, screenshot APIs, web connectivity testing, `BatchDetail` SSE streaming, and `SampleDetail` screenshot/action-log UI are in the repo. Verification status: backend full suite `128 passed` when run outside the sandbox so Chromium can launch; backend fast suite `123 passed, 5 deselected`; frontend `pnpm test`, `pnpm lint`, `pnpm format:check`, and `pnpm build` all green; manual browser smoke passed end-to-end.
- **Plan 4 — Android Executor (uiautomator2 + OCR):** in progress. Tier 1 and Tier 2 implementation are in the repo: backend/device discovery, `/devices` API + page with IME enable/disable buttons, `gui_android` scheduling, Android profile connectivity, Android Profile Builder MVP, SampleDetail device/replay metadata, OCR extraction, long-response stitching, and `pixel_stable`. Current status is code-complete pending final manual verification on a real device + real app, then release tagging. Read `docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md` before changing Android/Profile Builder behavior; it records the latest Qwen/Tongyi progress, fixes, and blockers.
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
- **Android verification:** real-device cases will be marked `@pytest.mark.android`; keep them out of the fast suite with `-m "not android"`.
- **ADB Keyboard:** bundled at `src/autoagent/fixtures/ADBKeyboard.apk`. The `/devices` page shows:
  - **Install** button (if not yet installed on device)
  - **Enable/Disable IME** toggles (if installed)
  - Status tags: `installed`/`not installed`, `ime enabled`/`ime disabled`
  Android execution auto-switches to `com.android.adbkeyboard/.AdbIME` for non-ASCII prompts and restores the previous IME when done.
- **Fake chat fixture APK:** source lives in `tests/fixtures/fake_chat_apk/`; build `fake_chat-debug.apk` with Android Studio or set `AUTOAGENT_FAKE_CHAT_APK` to an externally built artifact before running `pytest -m android`. This fixture is optional; Plan 4 can also be validated manually against a real device + real target app.
- **Android/Profile Builder handoff:** read `docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md` first when resuming Plan 4. It is the active status note for recent Qwen/Tongyi debugging, ADB Keyboard input fixes, and remaining verification blockers.
- **Android profile semantics:** `new_session_action` is for starting a clean conversation. Input focusing belongs in `input_focus_action`. Send triggering can live in `send_action` when runtime behavior is better represented by `tap_xy` or `click_locator` actions than by a static locator. Do not overload `new_session_action` with "tap the input box" unless the product truly uses that step to create a new conversation.
- **Profile Builder capture/runtime alignment:** `Start Builder Session` enables ADB Keyboard once for the builder session and `Generate Draft` restores the previous IME. `Capture Editing State` is manual-only: the user must focus the input first, and the backend should not auto-tap into editing or run an extra runtime probe during draft generation. Builder-generated review items gate connectivity validation; assume users must confirm review choices before treating a draft as runnable.
- **Profile Builder review completeness:** do not collapse plausible Android builder candidates away before review. Preserve broad raw candidate boxes for `input_locator`, `input_focus_action`, and `send_action`, and keep `latest_bubble_match` review conditional on real ambiguity rather than always forcing the user through it.
- **Android response extraction:** runtime UI-tree extraction must honor `response_container_locator` before applying `latest_bubble_match`. Do not scan the whole page by class alone when the profile already contains a reviewed response container.
- **Profile Builder response ranking:** keep all `latest_bubble_match` candidates visible in review, but rank likely assistant replies ahead of UI chrome, placeholders, and bottom feature chips so the default recommendation tracks the latest visible assistant message.
- **Response anchors:** treat `response_container_locator` as a structural anchor, not a frozen frame. Runtime extraction should rank matching containers, group multi-`TextView` reply fragments into a single latest response block, prefer the latest valid block inside the best container, and persist `after_result_<n>.xml` plus container-matching logs for device regressions.
- **Final manual smoke doc:** use `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md` for the final real-device verification run and result-report template.
- **Tier 2 OCR runtime:** `rapidocr_onnxruntime` runs on CPU in this repo. OCR/stitching paths are marked `@pytest.mark.slow` and stay out of the fast suite.
- **Tier 2 Android smoke:** 1. run a long-response app/profile with `method: ocr_only` or `ui_tree_then_ocr`; 2. verify stitched text spans more than one screen; 3. verify `pixel_stable` or `ui_tree_stable` completes without false positives.
- **Profile Builder artifacts:** stored under `<data_root>/profile_builder/<session_id>/`.
- **Profile Builder rule mode:** draft generation must keep working with no LLM config at all.
- **Profile Builder connectivity:** reuse the existing `/api/v1/tests/sync` execution path (via shared backend helper), not a duplicate executor path.
- **Screenshots:** Web executor screenshots are stored under `<logs_root>/<batch_id>/<sample_id>/NNN_<label>.png`. Milestone screenshots are always captured; intermediate per-action screenshots depend on `verbose_logs`.
- **SSE progress:** `GET /api/v1/batches/{id}/events` is the live progress stream. Frontend `useBatchStream` reconciles updates via `seq`; WebSocket is not used.

## Common commands

```bash
python3.11 -m pytest -q                # run all tests
python3.11 -m pytest -q -m "not playwright"   # skip real-browser tests
python3.11 -m pytest -q -m "not playwright and not android and not slow"   # fast backend suite
python3.11 -m pytest -v -m android     # android real-device suite
python3.11 -m pytest tests/unit -v     # unit only
python3.11 -m ruff check .             # lint
python3.11 -m ruff format .            # format
python3.11 -m playwright install chromium     # one-time: download Chromium
adb devices -l                         # verify adb sees local devices
python3.11 -m uvicorn --app-dir src autoagent.main:app --reload   # run dev server
cd web && pnpm dev                     # frontend dev server (5173)
cd web && pnpm build                   # build UI into src/autoagent/static/
cd web && pnpm test                    # frontend unit tests
cd web && pnpm lint                    # frontend lint
```

Environment for running:
- **Defaults** (dev): `ADMIN_USERNAME=admin`, `ADMIN_PASSWORD=admin123456`, `JWT_SECRET=dev-secret-key-32-chars-minimum-length`. These are built into `src/autoagent/config/settings.py` for convenience; override via `.env` or env vars in production.
- **Optional**: `CORS_ORIGINS` (comma-separated). Default empty → `CORSMiddleware` not mounted (SPA ships same-origin). Set only for cross-origin dev setups, e.g. `CORS_ORIGINS=http://localhost:5173`.

ADB Keyboard APK is bundled at `src/autoagent/fixtures/ADBKeyboard.apk` (17 KB). The `/devices` page has one-click "Install ADB Keyboard" and toggle "Enable/Disable IME" buttons.

## When starting a new task in this repo

1. Check the plan file for the plan currently in progress (see "Development status").
2. Consult `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md` for architecture intent.
3. Match existing code style — most modules are small and single-purpose; prefer adding a new module over growing an existing one past ~200 lines.
4. Plan 5 work should start with the "secrets + auth hardening" task (see "Deferred work").
5. If working on Plan 4 Android/Profile Builder, read `docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md` before debugging or retesting.
6. Plan 2 is complete and tagged `web-ui-v0.2.0`; the active implementation branch is Plan 4 until final Android verification and tagging complete.
