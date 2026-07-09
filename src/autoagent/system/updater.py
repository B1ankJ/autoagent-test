"""Self-update: pull the latest code from origin/main and restart in place.

The service runs as a plain backgrounded `nohup uvicorn` (see run.sh) with no
external supervisor, so a restart can't be `sys.exit()` + respawn. Instead we
do the git pull / dependency sync / SPA build *while the old process is still
serving* (so a broken update aborts with zero downtime), and only then spawn a
detached `run.sh restart --no-build` that kills us and brings up the new code.

This is remote-code-execution by design: whoever controls origin/main (or can
MITM the fetch) controls the server. It is gated behind DefaultsConfig
.self_update_enabled (off by default) + admin auth at the API layer.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger(__name__)

# repo root = .../src/autoagent/system/updater.py → parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]

_REMOTE = "origin"
_BRANCH = "main"
# A pull that touches any of these means the Python env may be stale.
_DEP_FILES = ("pyproject.toml", "uv.lock")
_CHANGELOG_LIMIT = 30


@dataclass
class CommandResult:
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return (self.stdout + self.stderr).strip()


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 300.0) -> CommandResult:
    """Run a subprocess capturing combined output. Never raises on non-zero."""
    # GIT_TERMINAL_PROMPT=0 makes git fail fast on missing credentials instead
    # of blocking on an interactive username/password prompt (which would hang
    # the request / the whole update).
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return CommandResult(cmd, proc.returncode, proc.stdout or "", proc.stderr or "")
    except FileNotFoundError as e:
        return CommandResult(cmd, 127, "", str(e))
    except subprocess.TimeoutExpired as e:
        return CommandResult(cmd, 124, "", f"timed out after {timeout}s: {e}")


@dataclass
class UpdateStatus:
    enabled: bool = False
    current_commit: str | None = None
    current_short: str | None = None
    remote_commit: str | None = None
    remote_short: str | None = None
    behind: int = 0
    up_to_date: bool = True
    changelog: list[str] = field(default_factory=list)
    fetch_ok: bool = True
    error: str | None = None


@dataclass
class ApplyResult:
    ok: bool
    restarting: bool
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    active_batches: int = 0


def _rev_parse(ref: str) -> str | None:
    r = _run(["git", "rev-parse", ref])
    return r.stdout.strip() if r.ok else None


def _short(commit: str | None) -> str | None:
    return commit[:8] if commit else None


def current_commit() -> str | None:
    return _rev_parse("HEAD")


def fetch() -> CommandResult:
    return _run(["git", "fetch", "--quiet", _REMOTE, _BRANCH])


def _changelog(local: str, remote: str) -> list[str]:
    r = _run(
        [
            "git",
            "log",
            "--no-merges",
            f"--max-count={_CHANGELOG_LIMIT}",
            "--pretty=format:%h %s",
            f"{local}..{remote}",
        ]
    )
    if not r.ok:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def check_for_update(*, enabled: bool, do_fetch: bool = True) -> UpdateStatus:
    """Compare local HEAD against origin/main. Fetches first unless do_fetch=False."""
    local = current_commit()
    status = UpdateStatus(
        enabled=enabled,
        current_commit=local,
        current_short=_short(local),
    )
    if do_fetch:
        f = fetch()
        status.fetch_ok = f.ok
        if not f.ok:
            status.error = f.output or "git fetch failed"
            return status
    remote = _rev_parse(f"{_REMOTE}/{_BRANCH}")
    status.remote_commit = remote
    status.remote_short = _short(remote)
    if local is None or remote is None:
        status.error = "could not resolve local/remote commit"
        return status
    if local == remote:
        status.up_to_date = True
        return status
    count = _run(["git", "rev-list", "--count", f"{local}..{remote}"])
    status.behind = int(count.stdout.strip()) if count.ok and count.stdout.strip() else 0
    status.up_to_date = status.behind == 0
    status.changelog = _changelog(local, remote)
    return status


def _deps_changed(old: str, new: str) -> bool:
    r = _run(["git", "diff", "--name-only", old, new])
    if not r.ok:
        # Can't tell → assume yes so we don't skip a needed sync.
        return True
    changed = set(r.stdout.split())
    return any(dep in changed for dep in _DEP_FILES)


@dataclass
class ToolCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class PreflightResult:
    ok: bool = False
    tools: list[ToolCheck] = field(default_factory=list)
    remote_ok: bool = False
    remote_detail: str = ""
    tree_clean: bool = False
    tree_detail: str = ""


def _tool_check(name: str) -> ToolCheck:
    r = _run([name, "--version"], timeout=20.0)
    if r.ok:
        first = r.output.splitlines()[0] if r.output else name
        return ToolCheck(name=name, ok=True, detail=first)
    return ToolCheck(name=name, ok=False, detail=r.output or "not found on PATH")


def preflight() -> PreflightResult:
    """Diagnose whether an update could run: tools reachable, remote pullable,
    working tree clean. Read-only — never fetches or mutates the checkout."""
    tools = [_tool_check("git"), _tool_check("uv"), _tool_check("pnpm")]

    # ls-remote proves network + non-interactive auth without changing anything.
    ls = _run(["git", "ls-remote", "--heads", _REMOTE, _BRANCH], timeout=30.0)
    remote_ok = ls.ok and bool(ls.stdout.strip())
    if remote_ok:
        remote_detail = ls.stdout.split()[0][:8]
    else:
        remote_detail = ls.output or "remote unreachable"

    # Uncommitted changes to *tracked* files would block `git pull --ff-only`
    # (untracked runtime files under data/ do not, so exclude them).
    st = _run(["git", "status", "--porcelain", "--untracked-files=no"])
    if not st.ok:
        tree_clean = False
        tree_detail = st.output or "git status failed"
    elif st.stdout.strip():
        tree_clean = False
        n = len(st.stdout.strip().splitlines())
        tree_detail = f"{n} 个未提交的改动(会阻止 --ff-only 拉取)"
    else:
        tree_clean = True
        tree_detail = "clean"

    ok = all(t.ok for t in tools) and remote_ok and tree_clean
    return PreflightResult(
        ok=ok,
        tools=tools,
        remote_ok=remote_ok,
        remote_detail=remote_detail,
        tree_clean=tree_clean,
        tree_detail=tree_detail,
    )


def _spawn_detached_restart() -> None:
    """Launch run.sh restart in a new session so it survives our imminent death.

    Sleeps briefly first so the triggering HTTP response flushes before this
    child kills the current uvicorn.
    """
    log_path = REPO_ROOT / "logs" / "self_update_restart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    script = "sleep 2; exec ./run.sh restart --no-build"
    with open(log_path, "a") as logf:
        subprocess.Popen(  # noqa: S603
            ["bash", "-c", script],
            cwd=str(REPO_ROOT),
            stdout=logf,
            stderr=logf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


def apply_update() -> ApplyResult:
    """Pull origin/main, sync deps if changed, rebuild SPA, then schedule restart.

    Runs every build step while the old process is still serving; only if all
    succeed do we spawn the detached restart. The caller is responsible for the
    enabled flag, admin auth, and the active-batch force gate.
    """
    steps: list[str] = []

    def record(label: str, r: CommandResult) -> bool:
        steps.append(f"$ {' '.join(r.cmd)}\n{r.output}".rstrip())
        if not r.ok:
            steps.append(f"[{label}] failed (exit {r.returncode})")
        return r.ok

    old = current_commit()

    pull = _run(["git", "pull", "--ff-only", _REMOTE, _BRANCH])
    if not record("git pull", pull):
        return ApplyResult(ok=False, restarting=False, steps=steps, error="git pull failed")

    new = current_commit()
    if old and new and old == new:
        steps.append("already up to date; nothing to apply")
        return ApplyResult(ok=True, restarting=False, steps=steps)

    if old and new and _deps_changed(old, new):
        sync = _run(["uv", "sync"], timeout=600.0)
        if not record("uv sync", sync):
            return ApplyResult(ok=False, restarting=False, steps=steps, error="uv sync failed")
    else:
        steps.append("dependencies unchanged; skipping uv sync")

    build = _run(["pnpm", "build"], cwd=REPO_ROOT / "web", timeout=600.0)
    if not record("pnpm build", build):
        return ApplyResult(ok=False, restarting=False, steps=steps, error="pnpm build failed")

    try:
        _spawn_detached_restart()
    except Exception as e:  # noqa: BLE001
        _log.exception("failed to spawn restart")
        steps.append(f"failed to spawn restart: {e}")
        return ApplyResult(ok=False, restarting=False, steps=steps, error="restart spawn failed")

    steps.append("update staged; restarting service (run.sh restart)")
    return ApplyResult(ok=True, restarting=True, steps=steps)
