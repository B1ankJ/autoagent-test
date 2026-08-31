from datetime import datetime, timezone

import pytest

from autoagent.anomalies import store
from autoagent.anomalies.duration_detector import check_duration_anomaly, evaluate_duration
from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.samples import upsert_sample


def test_returns_none_when_history_too_small():
    assert evaluate_duration(9999, [100, 200, 300]) is None


def test_flags_high_outlier():
    history = list(range(100, 120)) + [110] * 10  # 30 samples, tight around ~110
    verdict = evaluate_duration(10000, history)
    assert verdict is not None
    assert verdict["direction"] == "high"
    assert verdict["value"] == 10000
    assert verdict["fence_high"] < 10000
    assert verdict["sample_count"] == len(history)


def test_ignores_low_outlier():
    history = list(range(1000, 1030))  # 30 samples ~1000-1029
    verdict = evaluate_duration(1, history)
    assert verdict is None


def test_normal_value_returns_none():
    history = list(range(1000, 1030))
    assert evaluate_duration(1015, history) is None


def test_all_equal_history_only_flags_strict_outside():
    history = [500] * 25  # IQR 0 → fences both == 500
    assert evaluate_duration(500, history) is None
    assert evaluate_duration(501, history) is not None
    assert evaluate_duration(501, history)["direction"] == "high"
    assert evaluate_duration(499, history) is None


def _sample(sid: str, profile: str, ms):
    return SampleResult(
        id=sid,
        status="done",
        mode="api",
        target_profile=profile,
        duration_ms=ms,
        ended_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_check_writes_record_for_outlier():
    await init_db()
    for i in range(25):
        await upsert_sample("bh", _sample(f"h{i}", "p", 1000 + i))
    outlier = _sample("s_out", "p", 50000)
    await check_duration_anomaly(outlier, "b_out")

    items, total = await store.list_anomalies(type="duration", limit=10, offset=0)
    assert total == 1
    assert items[0].sample_id == "s_out"
    assert items[0].detail["direction"] == "high"


@pytest.mark.asyncio
async def test_check_skips_when_no_duration():
    await init_db()
    await check_duration_anomaly(_sample("s_nd", "p", None), "b_nd")
    _, total = await store.list_anomalies(type="duration", limit=10, offset=0)
    assert total == 0
