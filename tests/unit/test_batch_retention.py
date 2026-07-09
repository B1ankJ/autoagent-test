from __future__ import annotations

import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoagent.maintenance import batch_retention
from autoagent.maintenance.batch_retention import prune_old_batches
from autoagent.models.api import SampleResult
from autoagent.storage.batches import create_batch, get_batch, update_batch_status
from autoagent.storage.database import get_sessionmaker, init_db
from autoagent.storage.samples import upsert_sample


async def _make_batch(batch_id: str, *, status: str, age_days: int) -> None:
    await create_batch(
        batch_id=batch_id,
        name=batch_id,
        mode="api",
        concurrency=1,
        total=1,
        target_profile_default=None,
    )
    await upsert_sample(
        batch_id,
        SampleResult(id="s1", status="done", mode="api", target_profile="p"),
    )
    if status != "queued":
        await update_batch_status(batch_id, status)
    # Backdate created_at so the age cutoff catches it.
    sm = get_sessionmaker()
    from autoagent.models.db import Batch

    async with sm() as s:
        b = await s.get(Batch, batch_id)
        b.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
        await s.commit()


@pytest.mark.asyncio
async def test_prune_only_old_finished(tmp_path: Path):
    await init_db()
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    (data / "results").mkdir(parents=True)

    await _make_batch("old_done", status="done", age_days=30)
    await _make_batch("recent_done", status="done", age_days=1)
    await _make_batch("old_running", status="running", age_days=30)

    # Seed result files + log dirs.
    for bid in ("old_done", "recent_done", "old_running"):
        (data / "results" / f"{bid}.jsonl").write_text("{}\n")
        (logs / bid).mkdir(parents=True)
        (logs / bid / "x.jpg").write_bytes(b"x")

    # Dry-run counts only the old terminal batch.
    dry = await prune_old_batches(
        logs_root=logs, data_root=data, retention_days=7, dry_run=True
    )
    assert dry.batches == 1

    report = await prune_old_batches(
        logs_root=logs, data_root=data, retention_days=7, dry_run=False
    )
    assert report.batches == 1

    # old_done gone (row + files); the others survive.
    assert await get_batch("old_done") is None
    assert not (data / "results" / "old_done.jsonl").exists()
    assert not (logs / "old_done").exists()
    assert await get_batch("recent_done") is not None
    assert await get_batch("old_running") is not None
    assert (data / "results" / "recent_done.jsonl").exists()


@pytest.mark.asyncio
async def test_prune_noop_when_disabled(tmp_path: Path):
    await init_db()
    r = await prune_old_batches(
        logs_root=tmp_path, data_root=tmp_path, retention_days=0, dry_run=False
    )
    assert r.batches == 0


@pytest.mark.asyncio
async def test_archive_written_before_delete(tmp_path: Path):
    await init_db()
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    (data / "results").mkdir(parents=True)

    await _make_batch("old_done", status="done", age_days=30)
    (data / "results" / "old_done.jsonl").write_text('{"id": "s1"}\n')
    (logs / "old_done").mkdir(parents=True)
    (logs / "old_done" / "x.jpg").write_bytes(b"x")

    report = await prune_old_batches(
        logs_root=logs,
        data_root=data,
        retention_days=7,
        archive_retention_days=30,
        dry_run=False,
    )
    assert report.batches == 1
    assert report.archived == 1

    # Row + live files gone, but a restorable archive remains.
    assert await get_batch("old_done") is None
    assert not (data / "results" / "old_done.jsonl").exists()
    zip_path = data / "archive" / "old_done.zip"
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "batch.json" in names
        assert "results.jsonl" in names
        assert "logs/x.jpg" in names


@pytest.mark.asyncio
async def test_delete_skipped_when_archive_fails(tmp_path: Path, monkeypatch):
    await init_db()
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    (data / "results").mkdir(parents=True)

    await _make_batch("old_done", status="done", age_days=30)
    (data / "results" / "old_done.jsonl").write_text("{}\n")

    async def _fail(*_a, **_k):
        return False

    monkeypatch.setattr(batch_retention, "_archive_batch", _fail)

    report = await prune_old_batches(
        logs_root=logs,
        data_root=data,
        retention_days=7,
        archive_retention_days=30,
        dry_run=False,
    )
    assert report.batches == 0
    assert report.archived == 0
    # Nothing was deleted because the archive step failed.
    assert await get_batch("old_done") is not None
    assert (data / "results" / "old_done.jsonl").exists()


@pytest.mark.asyncio
async def test_old_archives_pruned(tmp_path: Path):
    await init_db()
    data = tmp_path / "data"
    archive = data / "archive"
    archive.mkdir(parents=True)

    old_zip = archive / "old.zip"
    fresh_zip = archive / "fresh.zip"
    old_zip.write_bytes(b"PK")
    fresh_zip.write_bytes(b"PK")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    os.utime(old_zip, (old_ts, old_ts))

    # retention_days=0 disables batch pruning but archives are still swept.
    report = await prune_old_batches(
        logs_root=tmp_path / "logs",
        data_root=data,
        retention_days=0,
        archive_retention_days=30,
        dry_run=False,
    )
    assert report.archives_pruned == 1
    assert not old_zip.exists()
    assert fresh_zip.exists()
