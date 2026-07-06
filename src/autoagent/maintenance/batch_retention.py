"""Prune old finished batches: DB rows + results JSONL + logs dir.

The file-only cleanup (maintenance.cleanup) trims logs by mtime but leaves
data/results/<id>.jsonl and the batches/samples DB rows to grow forever.
This removes terminal (done/failed/cancelled) batches older than the
retention window wholesale — the same thing the UI "delete batch" does,
batched over an age cutoff.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autoagent.storage.batches import delete_batch_rows, list_finished_batch_ids_before

_log = logging.getLogger(__name__)


@dataclass
class BatchPruneReport:
    batches: int = 0
    dry_run: bool = False


def _purge_batch_files(batch_id: str, *, logs_root: Path, data_root: Path) -> None:
    result_path = data_root / "results" / f"{batch_id}.jsonl"
    logs_dir = logs_root / batch_id
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass
    shutil.rmtree(logs_dir, ignore_errors=True)


async def prune_old_batches(
    *,
    logs_root: Path,
    data_root: Path,
    retention_days: int,
    dry_run: bool = False,
) -> BatchPruneReport:
    """Delete terminal batches (DB rows + results + logs) older than N days."""
    if retention_days <= 0:
        return BatchPruneReport(dry_run=dry_run)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    ids = await list_finished_batch_ids_before(cutoff)
    if dry_run:
        return BatchPruneReport(batches=len(ids), dry_run=True)

    deleted = 0
    for batch_id in ids:
        try:
            if await delete_batch_rows(batch_id):
                _purge_batch_files(batch_id, logs_root=logs_root, data_root=data_root)
                deleted += 1
        except Exception:  # noqa: BLE001
            _log.exception("batch retention: failed to prune %s", batch_id)
    return BatchPruneReport(batches=deleted, dry_run=False)
