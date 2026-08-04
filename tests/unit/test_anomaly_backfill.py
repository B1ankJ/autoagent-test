from datetime import datetime, timedelta, timezone

import pytest

from autoagent.anomalies import store
from autoagent.anomalies.backfill import backfill_duration_anomalies
from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.samples import upsert_sample


def _s(sid, profile, ms, ended):
    return SampleResult(
        id=sid, status="done", mode="api", target_profile=profile, duration_ms=ms, ended_at=ended
    )


@pytest.mark.asyncio
async def test_backfill_flags_outlier_and_is_idempotent():
    await init_db()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(25):
        await upsert_sample("b", _s(f"h{i}", "p", 1000 + i, base + timedelta(minutes=i)))
    await upsert_sample("b", _s("out", "p", 50000, base + timedelta(hours=2)))

    result = await backfill_duration_anomalies()
    assert result.scanned == 26
    assert result.created == 1
    items, total = await store.list_anomalies(type="duration", limit=10, offset=0)
    assert total == 1 and items[0].sample_id == "out"
    assert items[0].detail["direction"] == "high"

    again = await backfill_duration_anomalies()
    assert again.created == 0
    _, total2 = await store.list_anomalies(type="duration", limit=10, offset=0)
    assert total2 == 1


@pytest.mark.asyncio
async def test_backfill_respects_min_history():
    await init_db()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(4):
        await upsert_sample("b", _s(f"h{i}", "p", 1000, base + timedelta(minutes=i)))
    await upsert_sample("b", _s("out", "p", 99999, base + timedelta(minutes=10)))
    result = await backfill_duration_anomalies()
    assert result.created == 0
