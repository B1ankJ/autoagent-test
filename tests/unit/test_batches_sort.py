"""list_batches(sort_by=...): server-side sort on avg_duration_ms/started_at.

Sorting has to happen in the DB query, not client-side on the fetched page —
the app's own pagination pattern (see storage/batches.py's other filters)
would otherwise only reorder whatever page happened to come back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from autoagent.models.db import Batch
from autoagent.storage.batches import create_batch, list_batches, update_batch_progress
from autoagent.storage.database import get_sessionmaker, init_db


async def _batch(batch_id: str, *, avg_duration_ms: int | None, started_at: datetime) -> None:
    await create_batch(
        batch_id=batch_id, name=batch_id, mode="api", concurrency=1, total=1,
        target_profile_default=None,
    )
    await update_batch_progress(batch_id, done=1, failed=0, avg_duration_ms=avg_duration_ms)
    sm = get_sessionmaker()
    async with sm() as s:
        row = (await s.execute(select(Batch).where(Batch.id == batch_id))).scalar_one()
        row.started_at = started_at
        await s.commit()


async def test_sort_by_avg_duration_ms_desc():
    await init_db()
    base = datetime.now(timezone.utc)
    await _batch("b_slow", avg_duration_ms=5000, started_at=base)
    await _batch("b_fast", avg_duration_ms=100, started_at=base)
    await _batch("b_mid", avg_duration_ms=1000, started_at=base)

    rows = await list_batches(sort_by="avg_duration_ms", sort_dir="desc")
    ids = [r.id for r in rows]
    assert ids.index("b_slow") < ids.index("b_mid") < ids.index("b_fast")


async def test_sort_by_avg_duration_ms_asc():
    await init_db()
    base = datetime.now(timezone.utc)
    await _batch("b_slow", avg_duration_ms=5000, started_at=base)
    await _batch("b_fast", avg_duration_ms=100, started_at=base)

    rows = await list_batches(sort_by="avg_duration_ms", sort_dir="asc")
    ids = [r.id for r in rows]
    assert ids.index("b_fast") < ids.index("b_slow")


async def test_sort_by_started_at():
    await init_db()
    base = datetime.now(timezone.utc)
    await _batch("b_old", avg_duration_ms=1, started_at=base - timedelta(hours=2))
    await _batch("b_new", avg_duration_ms=1, started_at=base)
    await _batch("b_mid", avg_duration_ms=1, started_at=base - timedelta(hours=1))

    rows = await list_batches(sort_by="started_at", sort_dir="desc")
    ids = [r.id for r in rows]
    assert ids.index("b_new") < ids.index("b_mid") < ids.index("b_old")


async def test_no_sort_by_falls_back_to_created_at_desc():
    await init_db()
    await create_batch(
        batch_id="b1", name="b1", mode="api", concurrency=1, total=1,
        target_profile_default=None,
    )
    await create_batch(
        batch_id="b2", name="b2", mode="api", concurrency=1, total=1,
        target_profile_default=None,
    )
    rows = await list_batches()
    ids = [r.id for r in rows]
    assert ids.index("b2") < ids.index("b1")
