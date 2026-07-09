"""Prune old finished batches: DB rows + results JSONL + logs dir.

The file-only cleanup (maintenance.cleanup) trims logs by mtime but leaves
data/results/<id>.jsonl and the batches/samples DB rows to grow forever.
This removes terminal (done/failed/cancelled) batches older than the
retention window wholesale — the same thing the UI "delete batch" does,
batched over an age cutoff.

When archiving is enabled (archive_retention_days > 0), each batch is
zipped into data/archive/<batch>.zip (results + logs + a DB snapshot)
before it's deleted, so a mistaken retention window is recoverable. The
archives are pruned on their own, longer schedule.
"""
from __future__ import annotations

import json
import logging
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autoagent.storage.batches import delete_batch_rows, list_finished_batch_ids_before

_log = logging.getLogger(__name__)


@dataclass
class BatchPruneReport:
    batches: int = 0
    archived: int = 0
    archives_pruned: int = 0
    dry_run: bool = False


def _purge_batch_files(batch_id: str, *, logs_root: Path, data_root: Path) -> None:
    result_path = data_root / "results" / f"{batch_id}.jsonl"
    logs_dir = logs_root / batch_id
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass
    shutil.rmtree(logs_dir, ignore_errors=True)


async def _batch_snapshot_json(batch_id: str) -> str:
    """Serialize the batch row + its samples so an archive is restorable."""
    from autoagent.storage.batches import get_batch
    from autoagent.storage.samples import list_samples_for_batch

    batch = await get_batch(batch_id)
    samples = await list_samples_for_batch(batch_id)
    batch_dict = None
    if batch is not None:
        batch_dict = {
            c.name: getattr(batch, c.name) for c in batch.__table__.columns  # type: ignore[attr-defined]
        }
    return json.dumps(
        {"batch": batch_dict, "samples": [s.model_dump(mode="json") for s in samples]},
        ensure_ascii=False,
        default=str,
        indent=2,
    )


async def _archive_batch(
    batch_id: str, *, logs_root: Path, data_root: Path, archive_root: Path
) -> bool:
    """Zip a batch's results + logs + DB snapshot into archive_root. Best-effort."""
    archive_root.mkdir(parents=True, exist_ok=True)
    zip_path = archive_root / f"{batch_id}.zip"
    result_path = data_root / "results" / f"{batch_id}.jsonl"
    logs_dir = logs_root / batch_id
    try:
        snapshot = await _batch_snapshot_json(batch_id)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("batch.json", snapshot)
            if result_path.exists():
                zf.write(result_path, arcname="results.jsonl")
            if logs_dir.is_dir():
                for f in sorted(logs_dir.rglob("*")):
                    if f.is_file():
                        zf.write(f, arcname=f"logs/{f.relative_to(logs_dir)}")
        return True
    except Exception:  # noqa: BLE001
        _log.exception("batch retention: failed to archive %s", batch_id)
        zip_path.unlink(missing_ok=True)
        return False


def _prune_old_archives(archive_root: Path, archive_retention_days: int, dry_run: bool) -> int:
    if archive_retention_days <= 0 or not archive_root.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=archive_retention_days)
    pruned = 0
    for zip_path in archive_root.glob("*.zip"):
        try:
            mtime = datetime.fromtimestamp(zip_path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                if not dry_run:
                    zip_path.unlink(missing_ok=True)
                pruned += 1
        except OSError:
            continue
    return pruned


async def prune_old_batches(
    *,
    logs_root: Path,
    data_root: Path,
    retention_days: int,
    archive_retention_days: int = 0,
    dry_run: bool = False,
) -> BatchPruneReport:
    """Delete terminal batches older than N days, archiving first if enabled."""
    archive_root = data_root / "archive"
    archives_pruned = _prune_old_archives(archive_root, archive_retention_days, dry_run)
    if retention_days <= 0:
        return BatchPruneReport(dry_run=dry_run, archives_pruned=archives_pruned)

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    ids = await list_finished_batch_ids_before(cutoff)
    if dry_run:
        return BatchPruneReport(
            batches=len(ids),
            archived=len(ids) if archive_retention_days > 0 else 0,
            archives_pruned=archives_pruned,
            dry_run=True,
        )

    archive_on = archive_retention_days > 0
    deleted = 0
    archived = 0
    for batch_id in ids:
        try:
            # Archive first; if archiving fails, skip the delete so we never
            # lose data to a broken archive step.
            if archive_on:
                if await _archive_batch(
                    batch_id,
                    logs_root=logs_root,
                    data_root=data_root,
                    archive_root=archive_root,
                ):
                    archived += 1
                else:
                    continue
            if await delete_batch_rows(batch_id):
                _purge_batch_files(batch_id, logs_root=logs_root, data_root=data_root)
                deleted += 1
        except Exception:  # noqa: BLE001
            _log.exception("batch retention: failed to prune %s", batch_id)
    return BatchPruneReport(
        batches=deleted,
        archived=archived,
        archives_pruned=archives_pruned,
        dry_run=False,
    )
