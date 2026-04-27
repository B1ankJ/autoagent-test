import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.cleanup_runtime_artifacts import (
    CleanupEntry,
    apply_cleanup,
    collect_cleanup_entries,
    main,
)


def _set_mtime(path: Path, *, days_old: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
    os.utime(path, (ts, ts))


def _write_file(path: Path, *, days_old: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    _set_mtime(path, days_old=days_old)


def _make_session(path: Path, *, days_old: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _write_file(path / "draft_profile.yaml", days_old=days_old)
    _set_mtime(path, days_old=days_old)


def test_collect_cleanup_entries_finds_old_logs_and_profile_builder_sessions(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    _write_file(tmp_path / "logs" / "old.log", days_old=10)
    _write_file(tmp_path / "logs" / "recent.log", days_old=1)
    _write_file(tmp_path / "nested" / "logs" / "batch" / "run.txt", days_old=12)
    _make_session(tmp_path / "data" / "profile_builder" / "pb_old", days_old=15)
    _make_session(tmp_path / "data" / "profile_builder" / "pb_new", days_old=2)

    entries = collect_cleanup_entries(repo_root=tmp_path, days=7, now=now)

    assert CleanupEntry(tmp_path / "logs" / "old.log", "logs_file") in entries
    assert CleanupEntry(tmp_path / "nested" / "logs" / "batch" / "run.txt", "logs_file") in entries
    assert CleanupEntry(tmp_path / "nested" / "logs" / "batch", "logs_dir") in entries
    assert (
        CleanupEntry(
            tmp_path / "data" / "profile_builder" / "pb_old",
            "profile_builder_session",
        )
        in entries
    )
    assert CleanupEntry(tmp_path / "logs" / "recent.log", "logs_file") not in entries
    assert (
        CleanupEntry(
            tmp_path / "data" / "profile_builder" / "pb_new",
            "profile_builder_session",
        )
        not in entries
    )


def test_apply_cleanup_removes_old_targets_only(tmp_path: Path) -> None:
    _write_file(tmp_path / "logs" / "old.log", days_old=10)
    _write_file(tmp_path / "logs" / "recent.log", days_old=1)
    _make_session(tmp_path / "data" / "profile_builder" / "pb_old", days_old=15)

    deleted = apply_cleanup(
        collect_cleanup_entries(repo_root=tmp_path, days=7, now=datetime.now(timezone.utc)),
        repo_root=tmp_path,
    )

    assert not (tmp_path / "logs" / "old.log").exists()
    assert (tmp_path / "logs" / "recent.log").exists()
    assert not (tmp_path / "data" / "profile_builder" / "pb_old").exists()
    assert [entry.path for entry in deleted] == [
        tmp_path / "data" / "profile_builder" / "pb_old",
        tmp_path / "logs" / "old.log",
    ]


def test_apply_cleanup_rejects_paths_outside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="outside repository root"):
        apply_cleanup([CleanupEntry(outside, "logs_file")], repo_root=repo_root)


def test_main_defaults_to_dry_run_and_prints_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_file(tmp_path / "logs" / "old.log", days_old=10)

    exit_code = main(["--days", "7"], repo_root=tmp_path)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "dry-run" in output
    assert "logs/old.log" in output
    assert (tmp_path / "logs" / "old.log").exists()


def test_main_all_apply_removes_all_target_contents_and_keeps_roots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_file(tmp_path / "logs" / "old.log", days_old=1)
    _write_file(tmp_path / "nested" / "logs" / "batch" / "run.txt", days_old=1)
    _make_session(tmp_path / "data" / "profile_builder" / "pb_any", days_old=1)

    exit_code = main(["--all", "--apply"], repo_root=tmp_path)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "apply: deleted" in output
    assert (tmp_path / "logs").exists()
    assert list((tmp_path / "logs").iterdir()) == []
    assert (tmp_path / "nested" / "logs").exists()
    assert list((tmp_path / "nested" / "logs").iterdir()) == []
    assert (tmp_path / "data" / "profile_builder").exists()
    assert list((tmp_path / "data" / "profile_builder").iterdir()) == []


def test_main_rejects_all_without_apply(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--all"], repo_root=tmp_path)
