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
