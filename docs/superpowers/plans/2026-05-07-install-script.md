# Install Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single `install.sh` that installs all system dependencies on macOS/Linux, then calls `scripts/setup.py` to install Python deps, build the frontend, configure Playwright, and generate a `.env` with secrets.

**Architecture:** `install.sh` handles OS detection and system-level packages (Homebrew/apt/dnf, uv, pnpm). `scripts/setup.py` handles everything Python-level: `uv sync`, `pnpm build`, `playwright install chromium`, and interactive `.env` generation. Shell does only what must be shell; Python does the rest.

**Tech Stack:** bash, Python 3.11 stdlib (`subprocess`, `getpass`, `secrets`, `pathlib`), uv, pnpm, Homebrew (macOS), apt/dnf (Linux).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `install.sh` | Create | OS detection, system dep installation, calls setup.py |
| `scripts/setup.py` | Create | uv sync, pnpm build, playwright, .env generation, startup message |

---

### Task 1: `scripts/setup.py` — uv sync + pnpm build

**Files:**
- Create: `scripts/setup.py`

- [ ] **Step 1: Create `scripts/setup.py` with the run-step helper and uv + pnpm steps**

```python
#!/usr/bin/env python3.11
"""Post-system-install setup: Python deps, frontend build, Playwright, .env."""
from __future__ import annotations

import getpass
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _run(label: str, cmd: list[str], *, cwd: Path = ROOT, fatal: bool = True) -> bool:
    """Run a subprocess step, print label, return success."""
    print(f"  → {label}...")
    result = subprocess.run(cmd, cwd=cwd, capture_output=False)
    if result.returncode != 0:
        if fatal:
            print(f"\n✗ {label} failed (exit {result.returncode})", file=sys.stderr)
            sys.exit(result.returncode)
        else:
            print(f"  ⚠ {label} failed — continuing (non-fatal)", file=sys.stderr)
            return False
    print(f"  ✓ {label}")
    return True


def install_python_deps() -> None:
    _run("Python deps (uv sync)", ["uv", "sync"], cwd=ROOT)


def build_frontend() -> None:
    web = ROOT / "web"
    _run("Frontend install (pnpm install)", ["pnpm", "install"], cwd=web)
    _run("Frontend build (pnpm build)", ["pnpm", "build"], cwd=web)


def install_playwright() -> None:
    _run(
        "Playwright Chromium",
        [sys.executable, "-m", "playwright", "install", "chromium"],
        cwd=ROOT,
        fatal=False,
    )
```

- [ ] **Step 2: Add `.env` generation and `main()` to `scripts/setup.py`**

Append to `scripts/setup.py`:

```python

def generate_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        answer = input("\n.env already exists. Overwrite? [y/N]: ").strip().lower()
        if answer != "y":
            print("  ✓ Keeping existing .env")
            return

    password = getpass.getpass("\nAdmin password [Enter to generate random]: ").strip()
    if not password:
        password = secrets.token_urlsafe(16)
        print("  (random password generated)")

    jwt_secret = secrets.token_hex(32)
    assert len(jwt_secret) >= 32

    env_path.write_text(
        f"ADMIN_USERNAME=admin\n"
        f"ADMIN_PASSWORD={password}\n"
        f"JWT_SECRET={jwt_secret}\n"
        f"DATA_ROOT=./data\n"
        f"LOGS_ROOT=./logs\n",
        encoding="utf-8",
    )
    print("  ✓ .env written")


def print_next_steps() -> None:
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Setup complete. Start the server with:

    source .venv/bin/activate
    python3.11 -m uvicorn --app-dir src autoagent.main:app --host 0.0.0.0 --port 8000

  Then open http://localhost:8000
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


def main() -> None:
    print("\n[AutoAgent] Running setup...\n")
    install_python_deps()
    build_frontend()
    install_playwright()
    generate_env()
    print_next_steps()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Make the script executable**

```bash
chmod +x scripts/setup.py
```

- [ ] **Step 4: Smoke-test setup.py in isolation (skip .env overwrite prompt)**

```bash
# Verify it imports and the helper works without errors
python3.11 -c "import scripts.setup; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 5: Commit**

```bash
git add scripts/setup.py
git commit -m "feat: add scripts/setup.py for post-install Python setup"
```

---

### Task 2: `install.sh` — version checker helper + macOS deps

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Create `install.sh` with header, helpers, and macOS system dep installation**

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── colours ─────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ── version helpers ──────────────────────────────────────────────────────────
version_gte() {
    # version_gte "3.11.0" "3.11.9" → true if installed >= required
    local required="$1" installed="$2"
    printf '%s\n%s\n' "$required" "$installed" | sort -V -C
}

check_or_install_brew() {
    if command -v brew &>/dev/null; then
        ok "Homebrew already installed"
        return
    fi
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for the rest of this session
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
    ok "Homebrew installed"
}

brew_install() {
    local pkg="$1"
    if brew list --formula "$pkg" &>/dev/null; then
        ok "$pkg already installed"
    else
        echo "Installing $pkg via Homebrew..."
        brew install "$pkg"
        ok "$pkg installed"
    fi
}

# ── macOS system deps ────────────────────────────────────────────────────────
install_macos() {
    echo -e "\n[macOS] Installing system dependencies...\n"
    check_or_install_brew
    brew_install python@3.11
    brew_install node
    brew_install android-platform-tools

    # Ensure python3.11 is on PATH (brew links may vary)
    if ! command -v python3.11 &>/dev/null; then
        export PATH="$(brew --prefix python@3.11)/bin:$PATH"
    fi
}
```

- [ ] **Step 2: Add Linux dep installation to `install.sh`**

Append to `install.sh`:

```bash
# ── Linux system deps ────────────────────────────────────────────────────────
install_linux() {
    echo -e "\n[Linux] Installing system dependencies...\n"

    # Check sudo
    if ! sudo -n true 2>/dev/null && ! sudo -v 2>/dev/null; then
        fail "sudo access required to install system packages. Aborting."
    fi

    if command -v apt-get &>/dev/null; then
        echo "Detected Debian/Ubuntu — using apt"
        sudo apt-get update -qq
        sudo apt-get install -y python3.11 python3.11-venv nodejs npm adb
        ok "apt packages installed"
    elif command -v dnf &>/dev/null; then
        echo "Detected RHEL/Fedora — using dnf"
        sudo dnf install -y python3.11 nodejs npm android-tools
        ok "dnf packages installed"
    elif command -v yum &>/dev/null; then
        echo "Detected older RHEL — using yum"
        sudo yum install -y python3.11 nodejs npm android-tools
        ok "yum packages installed"
    else
        fail "Unsupported Linux distribution. Install python3.11, nodejs, npm, and adb manually, then re-run."
    fi
}
```

- [ ] **Step 3: Add uv, pnpm installation, and main entry to `install.sh`**

Append to `install.sh`:

```bash
# ── uv ───────────────────────────────────────────────────────────────────────
install_uv() {
    if command -v uv &>/dev/null; then
        ok "uv already installed ($(uv --version))"
        return
    fi
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for this session
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    ok "uv installed"
}

# ── pnpm ─────────────────────────────────────────────────────────────────────
install_pnpm() {
    if command -v pnpm &>/dev/null; then
        ok "pnpm already installed ($(pnpm --version))"
        return
    fi
    echo "Installing pnpm..."
    npm install -g pnpm
    ok "pnpm installed"
}

# ── main ─────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "╔══════════════════════════════════╗"
    echo "║   AutoAgent Test — Installer     ║"
    echo "╚══════════════════════════════════╝"
    echo ""

    OS="$(uname -s)"
    case "$OS" in
        Darwin) install_macos ;;
        Linux)  install_linux ;;
        *)      fail "Unsupported OS: $OS" ;;
    esac

    install_uv
    install_pnpm

    echo -e "\n[Python setup]\n"
    python3.11 scripts/setup.py
}

main "$@"
```

- [ ] **Step 4: Make `install.sh` executable**

```bash
chmod +x install.sh
```

- [ ] **Step 5: Verify shell syntax is valid**

```bash
bash -n install.sh && echo "syntax ok"
```

Expected: `syntax ok`

- [ ] **Step 6: Commit**

```bash
git add install.sh
git commit -m "feat: add install.sh for macOS/Linux one-command setup"
```

---

### Task 3: End-to-end smoke test on current machine

This task verifies the script works on the developer's machine without actually re-installing already-present tools.

- [ ] **Step 1: Run the full script in dry-run mode (check only, skip installs)**

```bash
bash -n install.sh && echo "shell syntax OK"
python3.11 -c "
import scripts.setup as s
print('generate_env function:', s.generate_env)
print('install_python_deps function:', s.install_python_deps)
print('build_frontend function:', s.build_frontend)
print('All symbols present')
"
```

Expected: all four lines printed without error.

- [ ] **Step 2: Run setup.py directly (skipping .env prompt if .env already exists)**

```bash
# Set AUTO_SKIP_ENV=1 is not implemented — manually type 'N' at the .env prompt
# Or if no .env exists, type a test password.
# Verify it completes the uv sync + pnpm build steps:
python3.11 scripts/setup.py
```

Expected output includes:
```
✓ Python deps (uv sync)
✓ Frontend install (pnpm install)
✓ Frontend build (pnpm build)
```

- [ ] **Step 3: Verify `.env` is gitignored**

```bash
grep -q "^\.env$" .gitignore && echo ".env is gitignored"
```

Expected: `.env is gitignored`

- [ ] **Step 4: Commit smoke-test results note (no code change needed if all pass)**

```bash
git commit --allow-empty -m "chore: verify install script smoke test passes on macOS"
```

---

### Task 4: Update README with install instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read current README**

```bash
cat README.md
```

- [ ] **Step 2: Add Quick Start section near the top of `README.md`**

Insert after the first heading (before any existing content):

```markdown
## Quick Start

**Requirements:** git, curl, internet access. Everything else is installed automatically.

```bash
git clone <repo-url>
cd AutoAgentTest
bash install.sh
```

The script will:
1. Install Python 3.11, Node.js, ADB, uv, and pnpm (if not already present)
2. Install Python and frontend dependencies
3. Download Playwright Chromium
4. Prompt for an admin password and generate a `.env` with a random JWT secret

Then start the server with the command printed at the end of the install.

**Platforms:** macOS (Homebrew), Ubuntu/Debian (apt), RHEL/Fedora (dnf).
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add Quick Start install instructions to README"
```
