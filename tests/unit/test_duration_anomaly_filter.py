"""duration_anomaly_only (list_batches / count_batches_by_status): a batch's
own avg_duration_ms compared against its profile's historical average
(storage/samples.py::avg_duration_by_profile) — >2x or <0.5x counts as
anomalous. Scoped to total==1 batches, same precedent as empty_response_only,
since Batch.avg_duration_ms aggregates across every sample in the batch and
only a single-sample batch has one well-defined profile to compare against.
"""
from __future__ import annotations

from autoagent.models.api import SampleResult
from autoagent.storage.batches import (
    count_batches_by_status,
    create_batch,
    list_batches,
    update_batch_progress,
    update_batch_status,
)
from autoagent.storage.database import init_db
from autoagent.storage.samples import upsert_sample


async def _single_sample_batch(batch_id: str, profile: str, duration_ms: int) -> None:
    await create_batch(
        batch_id=batch_id, name=batch_id, mode="api", concurrency=1, total=1,
        target_profile_default=None,
    )
    await update_batch_status(batch_id, "done")
    # Batch.avg_duration_ms is a separate aggregate field the scheduler
    # maintains via update_batch_progress — upsert_sample only writes the
    # per-sample duration_ms.
    await update_batch_progress(batch_id, done=1, failed=0, avg_duration_ms=duration_ms)
    await upsert_sample(
        batch_id,
        SampleResult(
            id="s1", status="done", prompts_sent=["hi"], responses=["ok"],
            mode="api", target_profile=profile, duration_ms=duration_ms,
        ),
    )


async def test_batch_far_above_profile_average_is_anomalous():
    await init_db()
    # Establish a baseline average of ~100ms for "p1" ...
    for i in range(3):
        await _single_sample_batch(f"baseline_{i}", "p1", 100)
    # ... then a batch that's way slower.
    await _single_sample_batch("b_slow", "p1", 500)

    hits = await list_batches(limit=100, duration_anomaly_only=True)
    assert any(b.id == "b_slow" for b in hits)
    assert not any(b.id.startswith("baseline_") for b in hits)


async def test_batch_far_below_profile_average_is_anomalous():
    await init_db()
    for i in range(3):
        await _single_sample_batch(f"baseline2_{i}", "p1", 1000)
    await _single_sample_batch("b_fast", "p1", 100)

    hits = await list_batches(limit=100, duration_anomaly_only=True)
    assert any(b.id == "b_fast" for b in hits)


async def test_batch_close_to_average_is_not_anomalous():
    await init_db()
    for i in range(3):
        await _single_sample_batch(f"baseline3_{i}", "p1", 100)
    await _single_sample_batch("b_normal", "p1", 120)

    hits = await list_batches(limit=100, duration_anomaly_only=True)
    assert not any(b.id == "b_normal" for b in hits)


async def test_multi_sample_batches_are_never_flagged():
    """total > 1 batches are out of scope — no single profile to compare
    against reliably."""
    await init_db()
    for i in range(3):
        await _single_sample_batch(f"baseline4_{i}", "p1", 100)
    await create_batch(
        batch_id="b_multi", name="b_multi", mode="api", concurrency=1, total=2,
        target_profile_default=None,
    )
    await update_batch_status("b_multi", "done")
    await update_batch_progress("b_multi", done=2, failed=0, avg_duration_ms=1000)
    for sid, duration in [("s1", 1000), ("s2", 1000)]:
        await upsert_sample(
            "b_multi",
            SampleResult(
                id=sid, status="done", prompts_sent=["hi"], responses=["ok"],
                mode="api", target_profile="p1", duration_ms=duration,
            ),
        )

    hits = await list_batches(limit=100, duration_anomaly_only=True)
    assert not any(b.id == "b_multi" for b in hits)


async def test_no_baseline_data_matches_nothing():
    await init_db()
    hits = await list_batches(limit=100, duration_anomaly_only=True)
    assert hits == []
    counts = await count_batches_by_status(duration_anomaly_only=True)
    assert counts.get("total", 0) == 0


async def test_count_batches_by_status_respects_duration_anomaly_only():
    await init_db()
    for i in range(3):
        await _single_sample_batch(f"baseline5_{i}", "p1", 100)
    await _single_sample_batch("b_slow2", "p1", 500)

    counts = await count_batches_by_status(duration_anomaly_only=True)
    assert counts["total"] == 1
