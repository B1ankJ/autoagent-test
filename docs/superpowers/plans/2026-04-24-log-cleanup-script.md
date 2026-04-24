# Log Cleanup Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repository-local script that previews or deletes old runtime artifacts under repository `logs/` directories and `data/profile_builder/` using an `N`-day retention policy.

**Architecture:** Add one focused CLI script under `scripts/` that discovers cleanup targets relative to the repository root, computes stale entries from filesystem mtimes, and either previews or deletes them. Cover the behavior with unit tests that build temporary directory trees and verify dry-run, apply, safety, and profile-builder session cleanup rules.

**Tech Stack:** Python 3.11, argparse, pathlib, shutil, pytest

---

### Task 1: Add the cleanup script test coverage

**Files:**
- Create: `tests/unit/test_cleanup_runtime_artifacts.py`
- Test: `tests/unit/test_cleanup_runtime_artifacts.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.cleanup_runtime_artifacts import CleanupEntry, collect_cleanup_entries


def _touch_with_age(path: Path, days_old: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
    path.chmod(0o644)
    Path(path).touch()
    import os
    os.utime(path, (ts, ts))


def test_collect_cleanup_entries_finds_old_logs_and_profile_builder_sessions(tmp_path: Path) -> None:
    repo_root = tmp_path
    _touch_with_age(repo_root / "logs" / "old.log", days_old=10)
    _touch_with_age(repo_root / "logs" / "recent.log", days_old=1)
    _touch_with_age(repo_root / "nested" / "logs" / "batch" / "run.txt", days_old=12)
    _touch_with_age(repo_root / "data" / "profile_builder" / "pb_old" / "draft.yaml", days_old=15)
    _touch_with_age(repo_root / "data" / "profile_builder" / "pb_new" / "draft.yaml", days_old=2)

    entries = collect_cleanup_entries(repo_root=repo_root, days=7, now=datetime.now(timezone.utc))

    assert CleanupEntry(repo_root / "logs" / "old.log", "logs_file") in entries
    assert CleanupEntry(repo_root / "nested" / "logs" / "batch" / "run.txt", "logs_file") in entries
    assert CleanupEntry(repo_root / "data" / "profile_builder" / "pb_old", "profile_builder_session") in entries
    assert CleanupEntry(repo_root / "logs" / "recent.log", "logs_file") not in entries
    assert CleanupEntry(repo_root / "data" / "profile_builder" / "pb_new", "profile_builder_session") not in entries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest tests/unit/test_cleanup_runtime_artifacts.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing symbol errors because the script does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class CleanupEntry:
    path: Path
    kind: str


def collect_cleanup_entries(repo_root: Path, days: int, now: datetime | None = None) -> list[CleanupEntry]:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3.11 -m pytest tests/unit/test_cleanup_runtime_artifacts.py::test_collect_cleanup_entries_finds_old_logs_and_profile_builder_sessions -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cleanup_runtime_artifacts.py scripts/cleanup_runtime_artifacts.py
git commit -m "feat: add cleanup artifact discovery"
```

### Task 2: Add apply-mode deletion and path safety checks

**Files:**
- Modify: `tests/unit/test_cleanup_runtime_artifacts.py`
- Modify: `scripts/cleanup_runtime_artifacts.py`
- Test: `tests/unit/test_cleanup_runtime_artifacts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_apply_cleanup_removes_old_targets_only(tmp_path: Path) -> None:
    repo_root = tmp_path
    _touch_with_age(repo_root / "logs" / "old.log", days_old=10)
    _touch_with_age(repo_root / "logs" / "recent.log", days_old=1)
    _touch_with_age(repo_root / "data" / "profile_builder" / "pb_old" / "draft.yaml", days_old=15)

    deleted = apply_cleanup(
        collect_cleanup_entries(repo_root=repo_root, days=7, now=datetime.now(timezone.utc)),
        repo_root=repo_root,
    )

    assert repo_root.joinpath("logs", "old.log").exists() is False
    assert repo_root.joinpath("logs", "recent.log").exists() is True
    assert repo_root.joinpath("data", "profile_builder", "pb_old").exists() is False
    assert [entry.path for entry in deleted] == [
        repo_root / "data" / "profile_builder" / "pb_old",
        repo_root / "logs" / "old.log",
    ]


def test_apply_cleanup_rejects_paths_outside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="outside repository root"):
        apply_cleanup([CleanupEntry(outside, "logs_file")], repo_root=repo_root)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.11 -m pytest tests/unit/test_cleanup_runtime_artifacts.py -q`
Expected: FAIL because `apply_cleanup` is missing or behavior is incomplete.

- [ ] **Step 3: Write minimal implementation**

```python
def apply_cleanup(entries: list[CleanupEntry], repo_root: Path) -> list[CleanupEntry]:
    deleted: list[CleanupEntry] = []
    for entry in sorted(entries, key=_cleanup_sort_key):
        resolved = entry.path.resolve()
        if repo_root.resolve() not in resolved.parents and resolved != repo_root.resolve():
            raise ValueError(f"path outside repository root: {resolved}")
        if entry.kind == "profile_builder_session":
            shutil.rmtree(resolved)
        elif entry.kind == "logs_file":
            resolved.unlink(missing_ok=True)
        elif entry.kind == "logs_dir" and resolved.exists():
            resolved.rmdir()
        deleted.append(entry)
    return deleted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/unit/test_cleanup_runtime_artifacts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cleanup_runtime_artifacts.py scripts/cleanup_runtime_artifacts.py
git commit -m "feat: add cleanup apply mode and safety guards"
```

### Task 3: Add the CLI and document usage

**Files:**
- Modify: `scripts/cleanup_runtime_artifacts.py`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Test: `tests/unit/test_cleanup_runtime_artifacts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_main_defaults_to_dry_run_and_prints_matches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = tmp_path
    _touch_with_age(repo_root / "logs" / "old.log", days_old=10)

    exit_code = main(["--days", "7"], repo_root=repo_root)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "dry-run" in output
    assert "logs/old.log" in output
    assert repo_root.joinpath("logs", "old.log").exists() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3.11 -m pytest tests/unit/test_cleanup_runtime_artifacts.py::test_main_defaults_to_dry_run_and_prints_matches -q`
Expected: FAIL because the CLI entrypoint does not exist or does not print the expected summary.

- [ ] **Step 3: Write minimal implementation**

```python
def main(argv: Sequence[str] | None = None, repo_root: Path | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    entries = collect_cleanup_entries(repo_root=root, days=args.days)
    if args.apply:
        deleted = apply_cleanup(entries, repo_root=root)
        print(f"apply: deleted {len(deleted)} entries")
    else:
        print(f"dry-run: matched {len(entries)} entries")
    ...
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.11 -m pytest tests/unit/test_cleanup_runtime_artifacts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cleanup_runtime_artifacts.py scripts/cleanup_runtime_artifacts.py README.md CLAUDE.md
git commit -m "feat: document runtime artifact cleanup script"
```
