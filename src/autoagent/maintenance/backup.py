"""Periodic backup of the SQLite DB + profile YAMLs.

Scoped deliberately narrow: the DB (queryable state backing the whole
API/UI) and profiles/ (hand-authored YAML, expensive to recreate) are the
small, critical, hard-to-regenerate core. Results JSONL/logs/
browser_profiles/profile_builder artifacts are excluded — results are
largely a queryable subset of what's already in the DB, and logs/archived
batches already have their own retention+archive-before-delete story
(maintenance/batch_retention.py); backing them up again here would just
duplicate that at real disk cost.

The DB is copied via sqlite3's online backup API (Connection.backup), not
a raw file copy — this project runs SQLite in WAL mode, so a plain copy of
db.sqlite could miss committed data still sitting in the -wal file and
produce a torn/inconsistent snapshot.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass
class BackupReport:
    path: str | None = None
    bytes_written: int = 0
    pruned: int = 0


def _backup_sqlite_db(db_path: Path, dest_path: Path) -> None:
    source = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(dest_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _prune_old_backups(backups_dir: Path, retention_days: int) -> int:
    if retention_days <= 0 or not backups_dir.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pruned = 0
    for zip_path in backups_dir.glob("*.zip"):
        try:
            mtime = datetime.fromtimestamp(zip_path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                zip_path.unlink(missing_ok=True)
                pruned += 1
        except OSError:
            continue
    return pruned


def _prune_excess_backups(backups_dir: Path, max_count: int) -> int:
    """Keep only the newest `max_count` zips; delete the rest.

    Run *after* a fresh backup is written so the new one counts toward the
    cap. `max_count <= 0` disables the count cap entirely.
    """
    if max_count <= 0 or not backups_dir.exists():
        return 0
    zips: list[tuple[float, Path]] = []
    for zip_path in backups_dir.glob("*.zip"):
        try:
            zips.append((zip_path.stat().st_mtime, zip_path))
        except OSError:
            continue
    if len(zips) <= max_count:
        return 0
    zips.sort(key=lambda t: t[0], reverse=True)  # newest first
    pruned = 0
    for _, zip_path in zips[max_count:]:
        try:
            zip_path.unlink(missing_ok=True)
            pruned += 1
        except OSError:
            continue
    return pruned


def resolve_backup_path(data_root: Path, name: str) -> Path | None:
    """Resolve `name` to a backup zip inside data_root/backups.

    Returns None if it doesn't exist or (guarding against path traversal —
    `name` comes straight from a URL path segment) doesn't actually resolve
    to a direct child of the backups dir.
    """
    backups_dir = (data_root / "backups").resolve()
    candidate = (backups_dir / Path(name).name).resolve()
    if candidate.parent != backups_dir or not candidate.is_file():
        return None
    return candidate


def delete_backup(data_root: Path, name: str) -> bool:
    path = resolve_backup_path(data_root, name)
    if path is None:
        return False
    path.unlink(missing_ok=True)
    return True


def list_backups(data_root: Path) -> list[dict]:
    backups_dir = data_root / "backups"
    if not backups_dir.exists():
        return []
    out = []
    for zip_path in sorted(backups_dir.glob("*.zip"), reverse=True):
        try:
            stat = zip_path.stat()
        except OSError:
            continue
        out.append(
            {
                "name": zip_path.name,
                "bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            }
        )
    return out


def _run_backup_sync(*, data_root: Path, retention_days: int, max_count: int) -> BackupReport:
    db_path = data_root / "db.sqlite"
    backups_dir = data_root / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    pruned = _prune_old_backups(backups_dir, retention_days)

    if not db_path.exists():
        pruned += _prune_excess_backups(backups_dir, max_count)
        return BackupReport(pruned=pruned)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zip_path = backups_dir / f"{timestamp}.zip"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "db.sqlite"
        _backup_sqlite_db(db_path, tmp_db)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, arcname="db.sqlite")
            profiles_dir = data_root / "profiles"
            if profiles_dir.is_dir():
                for f in sorted(profiles_dir.glob("*.yaml")):
                    zf.write(f, arcname=f"profiles/{f.name}")

    # Count cap runs *after* the new zip is written so it counts toward the
    # newest-N kept (it never prunes the fresh backup itself).
    pruned += _prune_excess_backups(backups_dir, max_count)

    return BackupReport(path=str(zip_path), bytes_written=zip_path.stat().st_size, pruned=pruned)


async def run_backup(
    *, data_root: Path, retention_days: int, max_count: int = 0
) -> BackupReport:
    return await asyncio.to_thread(
        _run_backup_sync,
        data_root=data_root,
        retention_days=retention_days,
        max_count=max_count,
    )
