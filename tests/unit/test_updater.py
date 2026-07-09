from __future__ import annotations

import os

import pytest

from autoagent.system import updater
from autoagent.system.updater import CommandResult


class FakeGit:
    """Scriptable stand-in for updater._run. Simulates a repo where HEAD moves
    from `old` to `new` once `git pull` runs."""

    def __init__(
        self,
        *,
        old: str,
        remote: str,
        pull_ok: bool = True,
        diff_files: str = "",
        sync_ok: bool = True,
        build_ok: bool = True,
    ):
        self.old = old
        self.new = old
        self.remote = remote
        self.pull_ok = pull_ok
        self.diff_files = diff_files
        self.sync_ok = sync_ok
        self.build_ok = build_ok
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *, cwd=None, timeout=300.0) -> CommandResult:
        self.calls.append(cmd)

        def r(code=0, out="", err=""):
            return CommandResult(cmd, code, out, err)

        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[2]
            if ref == "HEAD":
                return r(out=self.new)
            return r(out=self.remote)  # origin/main
        if cmd[:2] == ["git", "fetch"]:
            return r()
        if cmd[:3] == ["git", "pull", "--ff-only"]:
            if not self.pull_ok:
                return r(1, err="Not possible to fast-forward")
            self.new = self.remote
            return r(out="Updating...")
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return r(out="2")
        if cmd[:2] == ["git", "log"]:
            return r(out="abc123 feat: a\ndef456 fix: b")
        if cmd[:3] == ["git", "diff", "--name-only"]:
            return r(out=self.diff_files)
        if cmd[:2] == ["uv", "sync"]:
            return r(0 if self.sync_ok else 1, out="synced" if self.sync_ok else "boom")
        if cmd[:2] == ["pnpm", "build"]:
            return r(0 if self.build_ok else 1, out="built" if self.build_ok else "boom")
        return r()


def test_check_up_to_date(monkeypatch):
    fake = FakeGit(old="aaaa", remote="aaaa")
    monkeypatch.setattr(updater, "_run", fake)
    status = updater.check_for_update(enabled=True, do_fetch=True)
    assert status.up_to_date is True
    assert status.behind == 0
    assert status.changelog == []


def test_check_behind_reports_changelog(monkeypatch):
    fake = FakeGit(old="aaaa", remote="bbbb")
    monkeypatch.setattr(updater, "_run", fake)
    status = updater.check_for_update(enabled=True, do_fetch=True)
    assert status.up_to_date is False
    assert status.behind == 2
    assert len(status.changelog) == 2
    assert status.current_short == "aaaa"
    assert status.remote_short == "bbbb"


def test_check_no_fetch_skips_network(monkeypatch):
    fake = FakeGit(old="aaaa", remote="aaaa")
    monkeypatch.setattr(updater, "_run", fake)
    updater.check_for_update(enabled=True, do_fetch=False)
    assert ["git", "fetch", "--quiet", "origin", "main"] not in fake.calls


def test_apply_aborts_when_pull_fails(monkeypatch):
    fake = FakeGit(old="aaaa", remote="bbbb", pull_ok=False)
    spawned = []
    monkeypatch.setattr(updater, "_run", fake)
    monkeypatch.setattr(updater, "_spawn_detached_restart", lambda: spawned.append(True))
    result = updater.apply_update()
    assert result.ok is False
    assert result.restarting is False
    assert spawned == []  # never touched the running service


def test_apply_skips_uv_sync_when_deps_unchanged(monkeypatch):
    fake = FakeGit(old="aaaa", remote="bbbb", diff_files="src/autoagent/main.py")
    monkeypatch.setattr(updater, "_run", fake)
    monkeypatch.setattr(updater, "_spawn_detached_restart", lambda: None)
    result = updater.apply_update()
    assert result.ok is True
    assert result.restarting is True
    assert ["uv", "sync"] not in fake.calls
    assert ["pnpm", "build"] in fake.calls


def test_apply_runs_uv_sync_when_deps_changed(monkeypatch):
    fake = FakeGit(old="aaaa", remote="bbbb", diff_files="pyproject.toml\nuv.lock")
    monkeypatch.setattr(updater, "_run", fake)
    monkeypatch.setattr(updater, "_spawn_detached_restart", lambda: None)
    result = updater.apply_update()
    assert result.ok is True
    assert ["uv", "sync"] in fake.calls


def test_apply_aborts_when_build_fails(monkeypatch):
    fake = FakeGit(old="aaaa", remote="bbbb", build_ok=False)
    spawned = []
    monkeypatch.setattr(updater, "_run", fake)
    monkeypatch.setattr(updater, "_spawn_detached_restart", lambda: spawned.append(True))
    result = updater.apply_update()
    assert result.ok is False
    assert result.error == "pnpm build failed"
    assert spawned == []


def test_apply_noop_when_already_current(monkeypatch):
    # pull succeeds but HEAD == remote already (no new commits).
    fake = FakeGit(old="aaaa", remote="aaaa")
    monkeypatch.setattr(updater, "_run", fake)
    monkeypatch.setattr(updater, "_spawn_detached_restart", lambda: None)
    result = updater.apply_update()
    assert result.ok is True
    assert result.restarting is False
    assert ["pnpm", "build"] not in fake.calls


@pytest.mark.parametrize(
    "diff,expected",
    [("pyproject.toml", True), ("uv.lock", True), ("src/x.py\nweb/y.ts", False)],
)
def test_deps_changed(monkeypatch, diff, expected):
    monkeypatch.setattr(updater, "_run", lambda cmd, **k: CommandResult(cmd, 0, diff, ""))
    assert updater._deps_changed("a", "b") is expected


def _preflight_runner(*, tools_ok=True, remote_ok=True, tree_dirty=False):
    def run(cmd, **k) -> CommandResult:
        if cmd[1:2] == ["--version"]:  # git/uv/pnpm --version
            return CommandResult(cmd, 0 if tools_ok else 127, f"{cmd[0]} 1.0", "")
        if cmd[:2] == ["git", "ls-remote"]:
            if remote_ok:
                return CommandResult(cmd, 0, "deadbeef123\trefs/heads/main", "")
            return CommandResult(cmd, 128, "", "Authentication failed")
        if cmd[:2] == ["git", "status"]:
            return CommandResult(cmd, 0, " M src/x.py\n" if tree_dirty else "", "")
        return CommandResult(cmd, 0, "", "")

    return run


def test_preflight_all_green(monkeypatch):
    monkeypatch.setattr(updater, "_run", _preflight_runner())
    r = updater.preflight()
    assert r.ok is True
    assert [t.name for t in r.tools] == ["git", "uv", "pnpm"]
    assert all(t.ok for t in r.tools)
    assert r.remote_ok is True
    assert r.remote_detail == "deadbeef"
    assert r.tree_clean is True


def test_preflight_fails_on_missing_tool(monkeypatch):
    monkeypatch.setattr(updater, "_run", _preflight_runner(tools_ok=False))
    r = updater.preflight()
    assert r.ok is False
    assert all(not t.ok for t in r.tools)


def test_preflight_fails_on_unreachable_remote(monkeypatch):
    monkeypatch.setattr(updater, "_run", _preflight_runner(remote_ok=False))
    r = updater.preflight()
    assert r.ok is False
    assert r.remote_ok is False


def test_preflight_fails_on_dirty_tree(monkeypatch):
    monkeypatch.setattr(updater, "_run", _preflight_runner(tree_dirty=True))
    r = updater.preflight()
    assert r.ok is False
    assert r.tree_clean is False
    # the offending file is named so the user can act on it
    assert "src/x.py" in r.tree_detail


def test_augmented_path_appends_user_tool_dirs(monkeypatch, tmp_path):
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    monkeypatch.setattr(updater, "_EXTRA_PATH_DIRS", (str(local_bin), "/does/not/exist"))
    monkeypatch.setenv("PATH", "/usr/bin")
    result = updater._augmented_path()
    assert str(local_bin) in result.split(os.pathsep)
    assert "/does/not/exist" not in result  # skipped: not a real dir
    assert "/usr/bin" in result.split(os.pathsep)
