# Install Script Design

**Date:** 2026-05-07  
**Scope:** One-command deployment to macOS and Linux (Plan 5)

## Goal

A single `install.sh` entry point that detects the OS, installs all system dependencies, then delegates complex setup to `scripts/setup.py`. After running, the user gets a ready-to-launch environment and startup instructions.

## Architecture

```
install.sh
  ├── detect OS (macOS / Linux)
  ├── install system deps
  │   ├── macOS: Homebrew → python@3.11, node, android-platform-tools
  │   └── Linux: apt / dnf → python3.11, nodejs, npm, adb
  ├── install uv  (curl https://astral.sh/uv/install.sh | sh)
  ├── install pnpm  (npm install -g pnpm)
  └── exec python3.11 scripts/setup.py
        ├── uv sync
        ├── pnpm install && pnpm build  (cwd: web/)
        ├── playwright install chromium
        ├── interactive .env generation
        └── print startup command
```

## install.sh — System Dependency Installation

### Detection strategy

Each tool is checked with `command -v` first. If present, the version is compared against the minimum requirement. Satisfied → print `✓ already installed`, skip. Unsatisfied → install/upgrade.

### macOS

1. Check for Homebrew; if absent install via the official installer.
2. `brew install python@3.11` (min 3.11.0)
3. `brew install node` (min 18.0)
4. `brew install android-platform-tools` (provides `adb`)
5. `curl -LsSf https://astral.sh/uv/install.sh | sh`
6. `npm install -g pnpm`

### Linux — Debian/Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv nodejs npm adb
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g pnpm
```

### Linux — RHEL/Fedora

```bash
sudo dnf install -y python3.11 nodejs npm android-tools
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g pnpm
```

### Permissions

The script checks for `sudo` access at startup on Linux. If unavailable, it exits with a clear error before attempting any installation.

### Progress output format

```
[1/6] Checking Python 3.11...   ✓ already installed (3.11.9)
[2/6] Installing uv...          ✓ done
...
```

## scripts/setup.py — Python Setup Helper

Runs after `install.sh` has confirmed all system tools are present.

### Steps (in order)

1. `uv sync` — install Python deps into `.venv`
2. `pnpm install && pnpm build` — build frontend into `src/autoagent/static/`
3. `python3.11 -m playwright install chromium`
4. `.env` generation (see below)
5. Print startup command

Each `subprocess.run` uses `check=True`; on failure the step name and stderr are printed and the script exits non-zero.

### .env generation

```python
import secrets, getpass
from pathlib import Path

if Path(".env").exists():
    overwrite = input(".env already exists. Overwrite? [y/N]: ")
    if overwrite.lower() != "y":
        print("Keeping existing .env")
        return

password = getpass.getpass("Admin password [Enter to generate random]: ")
if not password:
    password = secrets.token_urlsafe(16)

jwt_secret = secrets.token_hex(32)   # always auto-generated
assert len(jwt_secret) >= 32         # sanity check

Path(".env").write_text(f"""\
ADMIN_USERNAME=admin
ADMIN_PASSWORD={password}
JWT_SECRET={jwt_secret}
DATA_ROOT=./data
LOGS_ROOT=./logs
""")
print("✓ .env written")
```

### Final output

```
✓ Python deps installed
✓ Frontend built
✓ Chromium installed
✓ .env written

Run the server:
  source .venv/bin/activate
  python3.11 -m uvicorn --app-dir src autoagent.main:app --host 0.0.0.0 --port 8000
```

## Error Handling

| Failure point | Behaviour |
|---|---|
| No sudo on Linux | Exit immediately with explanation |
| brew install fails | Print brew error, exit non-zero |
| uv sync fails | Print step name + stderr, exit non-zero |
| pnpm build fails | Print step name + stderr, exit non-zero |
| playwright install fails | Warn (non-fatal if user won't use gui_pc_web mode) |
| .env write fails | Print OS error, exit non-zero |

`playwright install chromium` is the only non-fatal failure: the script warns and continues because the tool is not needed for API/Android modes.

## Files Produced

| File | Description |
|---|---|
| `install.sh` | Entry point, placed at repo root |
| `scripts/setup.py` | Python helper, called by install.sh |
| `.env` | Generated secrets, gitignored |

## Out of Scope

- Docker / container packaging
- systemd / launchd service registration
- Windows support
- Automated upgrades of an existing installation
