# AutoAgent Test

Backend service for batch testing of conversational AI products via OpenAI-compatible APIs, with a React + TypeScript web UI built into the FastAPI binary.

## Status

**Plan 1 complete. Plan 2 complete. Plan 3 complete. Plan 4 in progress.** API mode is fully wired. Web GUI execution includes a Playwright-backed executor, SSE batch progress, screenshot endpoints, web connectivity testing, and SampleDetail screenshot/action-log UI. Android Tier 1 and Tier 2 code paths are now in the repo: persistent device discovery, `/devices` API + UI, `gui_android` scheduler/executor plumbing, Android profile connectivity support, action replay download, OCR extraction, scroll stitching, `pixel_stable`, and the Android Profile Builder MVP. Remaining work is final manual verification on a real device + real app, then release tagging.

Current Android/Profile Builder handoff, including the latest Qwen/Tongyi debugging status and open blockers, is tracked in `docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md`.

## Requirements

- Python 3.10+
- Optional: Docker (later plan)

## Setup

```bash
cp .env.example .env
# Edit .env: set ADMIN_PASSWORD and JWT_SECRET (at least 32 chars)

pip install -e ".[dev]"
```

### Web executor prerequisite (Plan 3)

Web mode uses Playwright. After `pip install`:

```bash
python3.11 -m playwright install chromium --with-deps
```

Run once per machine. `--with-deps` installs OS libs on Linux and is a no-op on macOS.

### Android executor prerequisite (Plan 4 Tier 1)

Android mode requires:

```bash
brew install android-platform-tools   # macOS
python3.11 -m pip install -e '.[dev]'
adb devices
```

Tier 1 uses `uiautomator2` plus a connected emulator or real device. If you plan to use
`input_method: adb_keyboard`, the repo now bundles `src/autoagent/fixtures/ADBKeyboard.apk` so the
Devices page can offer one-click installation by default. Set `ADB_KEYBOARD_APK_PATH` only if you
want to override that bundled APK. The executor auto-switches to
`com.android.adbkeyboard/.AdbIME` for non-ASCII input and restores the previous IME afterwards.

The optional Tier 1 fake-chat smoke target lives under `tests/fixtures/fake_chat_apk/`. Build its
debug APK in Android Studio and place it at `tests/fixtures/fake_chat_apk/fake_chat-debug.apk`, or
set `AUTOAGENT_FAKE_CHAT_APK=/abs/path/to/app-debug.apk` before running `pytest -m android`.
If you skip this fixture, final Android verification can be done directly on a real device + real
target app via the Web UI.

The current Android/Profile Builder handoff is tracked in
`docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md`. The final real-device
checklist is tracked in `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`.

### Profile Builder (Android MVP)

Use `Profiles -> Build Profile` in the web UI to generate a draft Android profile from guided
captures. The builder walks through idle and editing states, proposes candidate
locators, surfaces `review_items` when confidence is low, and can run a connectivity check against
the generated draft before you save anything as a normal profile.

Capture expectations:

- `idle`: manually send one short test message first, wait until the answer is visible, then stop on the target conversation page before the input is focused
- `editing`: manually focus the input so the real editing controls are visible, then capture exactly that screen

Builder behavior:

- `Start Builder Session` enables `ADB Keyboard` once for the whole builder session and restores the previous IME after `Generate Draft`
- `Capture Editing State` does not auto-tap into the input area and does not run an extra runtime probe; the draft is derived only from the manual `idle` and `editing` captures
- Review generation now keeps broader raw candidates instead of collapsing them away early; `input_locator`, `input_focus_action`, and `send_action` preserve plausible composer controls and rely on ranking rather than aggressive filtering
- `send_action` review now also keeps non-clickable visual send controls when the XML exposes a tappable-looking send icon or label without `clickable="true"`, so manual review can still choose the correct tap target
- `latest_bubble_match` review is now conditional: if the structural response anchor resolves to one clear latest response block, the builder can skip that review item; ambiguous containers or blocks still surface all evidence for manual choice
- Android response extraction now treats `response_container_locator` as a structural anchor, not a single frozen bounds box. Runtime extraction ranks matching containers, groups multi-`TextView` reply fragments into one response block, and selects the latest valid block inside the best match.

Builder artifacts are stored under `data/profile_builder/<session_id>/` and include
`capture_<step>.*`, `candidates.json`, `review_items.json`, `draft_profile.yaml`, and
`connectivity_result.json` after validation.

Optional LLM settings:

```bash
export PROFILE_BUILDER_LLM_BASE_URL=...
export PROFILE_BUILDER_LLM_MODEL=...
export PROFILE_BUILDER_LLM_API_KEY=...
export PROFILE_BUILDER_LLM_TIMEOUT_SEC=30
```

If those env vars are absent, the builder stays in deterministic rule-only mode.

### Android OCR notes (Plan 4 Tier 2)

- Tier 2 OCR uses `rapidocr_onnxruntime` on CPU.
- Long responses may take several seconds because multiple frames are OCR'd and stitched.
- `@pytest.mark.slow` covers OCR fixtures and is excluded from the fast suite.

## Run

```bash
python3.11 -m uvicorn --app-dir src autoagent.main:app --host 0.0.0.0 --port 8000 --reload
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

## Web UI

The web UI lives in `web/` and is built into `src/autoagent/static/` where FastAPI serves it.

### Dev

```bash
# Terminal 1 — backend
python3.11 -m uvicorn --app-dir src autoagent.main:app --reload

# Terminal 2 — frontend dev server with proxy
cd web
pnpm install
pnpm dev
# open http://localhost:5173
```

### Production build

```bash
cd web && pnpm build
# outputs to src/autoagent/static/
# now a single uvicorn serves both API and UI on :8000
```

### Web UI Smoke Test

```bash
cd web && pnpm build
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin_pw_1234
export JWT_SECRET=$(python3.11 -c "import secrets; print(secrets.token_hex(32))")
python3.11 -m uvicorn --app-dir src autoagent.main:app
```

Then:

1. Open `http://localhost:8000/`; unauthenticated access should land on `/login`.
2. Log in with the admin credentials above.
3. Go to Profiles, create `openai_gpt4`, and paste:

```yaml
name: openai_gpt4
platform: api
api:
  base_url: https://api.openai.com/v1
  model: gpt-4o
  api_key_env: OPENAI_KEY
```

4. Click `校验` and then `保存`.
5. Export `OPENAI_KEY=sk-...` in the backend shell, restart the backend, then run `连通性测试` with prompt `hello`.
6. Go to `Tests / Quick`, choose sync mode, and verify a response appears.
7. Go to `Batches / 新建批次`, upload a 3-line JSONL, and verify the batch reaches `done`.
8. Click `下载结果` and verify a `.jsonl` file is downloaded.
9. Go to `Config`, change a default, save, and reload to confirm persistence.
10. Click `登出`; revisiting `/` should redirect back to `/login`.

## Architecture

See:
- `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md`
- `docs/superpowers/plans/2026-04-21-plan-1-backend-mvp.md`

## Next plans

- Plan 3: Web GUI Executor (Playwright)
- Plan 4: Android Executor (uiautomator2 + OCR)
- Plan 5: Packaging, monthly backups, Docker
