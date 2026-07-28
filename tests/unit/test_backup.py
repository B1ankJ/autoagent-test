from __future__ import annotations

import os
import sqlite3
import time
import zipfile
from pathlib import Path

from autoagent.maintenance.backup import (
    delete_backup,
    list_backups,
    resolve_backup_path,
    run_backup,
)


def _make_db(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(data_root / "db.sqlite"))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()


async def test_backup_writes_restorable_db_and_profiles(tmp_path):
    data_root = tmp_path
    _make_db(data_root)
    (data_root / "profiles").mkdir()
    (data_root / "profiles" / "p1.yaml").write_text("name: p1\n")
    # Non-yaml files under profiles/ shouldn't be swept in.
    (data_root / "profiles" / "notes.txt").write_text("ignore me\n")

    report = await run_backup(data_root=data_root, retention_days=14)

    assert report.path is not None
    assert report.bytes_written > 0
    with zipfile.ZipFile(report.path) as zf:
        names = zf.namelist()
        assert "db.sqlite" in names
        assert "profiles/p1.yaml" in names
        assert "profiles/notes.txt" not in names

        zf.extract("db.sqlite", str(tmp_path / "restore"))
    restored = sqlite3.connect(str(tmp_path / "restore" / "db.sqlite"))
    assert restored.execute("SELECT v FROM t").fetchall() == [("hello",)]


async def test_backup_noop_when_db_missing(tmp_path):
    report = await run_backup(data_root=tmp_path, retention_days=14)
    assert report.path is None
    assert report.bytes_written == 0


async def test_backup_prunes_old_backups_past_retention(tmp_path):
    _make_db(tmp_path)
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    stale = backups_dir / "stale.zip"
    stale.write_bytes(b"x")
    old = time.time() - 3600 * 24 * 30  # 30 days old
    os.utime(stale, (old, old))

    report = await run_backup(data_root=tmp_path, retention_days=14)

    assert report.pruned == 1
    assert not stale.exists()


async def test_backup_zero_retention_skips_pruning(tmp_path):
    _make_db(tmp_path)
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    stale = backups_dir / "stale.zip"
    stale.write_bytes(b"x")
    old = time.time() - 3600 * 24 * 365
    os.utime(stale, (old, old))

    report = await run_backup(data_root=tmp_path, retention_days=0)

    assert report.pruned == 0
    assert stale.exists()
    # A backup is still written — retention_days=0 governs pruning of old
    # backups, not whether "run backup" itself does anything.
    assert report.path is not None


async def test_list_backups_returns_newest_first(tmp_path):
    assert list_backups(tmp_path) == []

    _make_db(tmp_path)
    first = await run_backup(data_root=tmp_path, retention_days=14)
    time.sleep(1.1)  # ensure a distinct mtime/filename second bucket
    second = await run_backup(data_root=tmp_path, retention_days=14)

    listed = list_backups(tmp_path)
    assert [b["name"] for b in listed] == [
        Path(second.path).name,
        Path(first.path).name,
    ]
    assert listed[0]["bytes"] == second.bytes_written


async def test_resolve_backup_path_finds_existing_backup(tmp_path):
    _make_db(tmp_path)
    report = await run_backup(data_root=tmp_path, retention_days=14)
    name = Path(report.path).name

    resolved = resolve_backup_path(tmp_path, name)

    assert resolved == Path(report.path).resolve()


def test_resolve_backup_path_none_for_missing_file(tmp_path):
    assert resolve_backup_path(tmp_path, "nope.zip") is None


def test_resolve_backup_path_rejects_traversal(tmp_path):
    (tmp_path / "backups").mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("shh")

    assert resolve_backup_path(tmp_path, "../secret.txt") is None
    assert resolve_backup_path(tmp_path, "..%2Fsecret.txt") is None


async def test_delete_backup_removes_file(tmp_path):
    _make_db(tmp_path)
    report = await run_backup(data_root=tmp_path, retention_days=14)
    name = Path(report.path).name

    assert delete_backup(tmp_path, name) is True
    assert not Path(report.path).exists()
    assert list_backups(tmp_path) == []


def test_delete_backup_false_for_missing_file(tmp_path):
    assert delete_backup(tmp_path, "nope.zip") is False
