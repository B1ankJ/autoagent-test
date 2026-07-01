"""Purpose-built runtime-artifact cleanup for the retention job.

Distinct from scripts/cleanup_runtime_artifacts.py (the CLI) so it can
target settings.logs_root / settings.data_root directly rather than
guessing which "logs" dirs sit under the repo root.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    files_deleted: int = 0
    dirs_deleted: int = 0
    bytes_freed: int = 0
    # Whether this was a real run or a dry preview.
    dry_run: bool = False

    def __add__(self, other: CleanupReport) -> CleanupReport:
        return CleanupReport(
            files_deleted=self.files_deleted + other.files_deleted,
            dirs_deleted=self.dirs_deleted + other.dirs_deleted,
            bytes_freed=self.bytes_freed + other.bytes_freed,
            dry_run=self.dry_run or other.dry_run,
        )


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _cleanup_logs_root(logs_root: Path, cutoff: datetime, dry_run: bool) -> CleanupReport:
    """Delete files under logs_root older than cutoff, plus emptied dirs."""
    report = CleanupReport(dry_run=dry_run)
    if not logs_root.exists():
        return report

    # Delete stale files bottom-up so dir emptiness checks after are accurate.
    for entry in sorted(logs_root.rglob("*"), key=lambda p: -len(p.parts)):
        if entry.is_file():
            try:
                if _mtime(entry) < cutoff:
                    size = entry.stat().st_size
                    if not dry_run:
                        entry.unlink()
                    report.files_deleted += 1
                    report.bytes_freed += size
            except OSError as e:
                _log.warning("cleanup: skip %s: %s", entry, e)

    # Sweep empty dirs deepest-first (excluding logs_root itself).
    for entry in sorted(logs_root.rglob("*"), key=lambda p: -len(p.parts)):
        if entry.is_dir() and entry != logs_root:
            try:
                # rmdir only succeeds on empty dirs — exactly what we want.
                if not any(entry.iterdir()):
                    if not dry_run:
                        entry.rmdir()
                    report.dirs_deleted += 1
            except OSError:
                # Non-empty or in-use — skip silently.
                continue

    return report


def _cleanup_profile_builder(root: Path, cutoff: datetime, dry_run: bool) -> CleanupReport:
    """Delete entire per-session dirs whose mtime is older than cutoff."""
    report = CleanupReport(dry_run=dry_run)
    if not root.exists():
        return report
    for session_dir in root.iterdir():
        if not session_dir.is_dir():
            continue
        try:
            if _mtime(session_dir) >= cutoff:
                continue
            total_bytes = sum(f.stat().st_size for f in session_dir.rglob("*") if f.is_file())
            file_count = sum(1 for f in session_dir.rglob("*") if f.is_file())
            if not dry_run:
                shutil.rmtree(session_dir, ignore_errors=True)
            report.files_deleted += file_count
            report.dirs_deleted += 1
            report.bytes_freed += total_bytes
        except OSError as e:
            _log.warning("cleanup: skip profile_builder session %s: %s", session_dir, e)
    return report


def run_cleanup(
    *,
    logs_root: Path,
    data_root: Path,
    retention_days: int,
    dry_run: bool = False,
) -> CleanupReport:
    """Sweep artifacts older than N days out of logs and data/profile_builder.

    Returns aggregated counts. Safe to call at any time; dry_run=True
    reports what would be deleted without touching disk.
    """
    if retention_days <= 0:
        return CleanupReport(dry_run=dry_run)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    logs_report = _cleanup_logs_root(logs_root, cutoff, dry_run)
    pb_report = _cleanup_profile_builder(data_root / "profile_builder", cutoff, dry_run)
    return logs_report + pb_report
