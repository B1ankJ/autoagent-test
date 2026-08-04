from datetime import datetime, timedelta, timezone

import pytest

from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.samples import (
    avg_duration_by_profile,
    success_stats_by_profile,
    upsert_sample,
)


def _sample(sid, profile, status, ms, ended):
    return SampleResult(
        id=sid, status=status, mode="api", target_profile=profile, duration_ms=ms, ended_at=ended
    )


@pytest.mark.asyncio
async def test_success_stats_and_windowed_avg():
    await init_db()
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=30)
    await upsert_sample("b", _sample("s1", "p", "done", 100, now))
    await upsert_sample("b", _sample("s2", "p", "done", 200, now))
    await upsert_sample("b", _sample("s3", "p", "done", 300, now))
    await upsert_sample("b", _sample("s4", "p", "failed", None, now))
    await upsert_sample("b", _sample("s5", "p", "done", 9999, old))
    await upsert_sample("b", _sample("s6", "p", "running", None, None))

    since = now - timedelta(days=7)
    stats = await success_stats_by_profile(since)
    assert stats["p"] == (3, 4)

    avg = await avg_duration_by_profile(since=since)
    assert round(avg["p"]) == 200

    avg_all = await avg_duration_by_profile()
    assert avg_all["p"] > 200
