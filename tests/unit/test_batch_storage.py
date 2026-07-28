import asyncio

from autoagent.models.api import SampleResult
from autoagent.storage.batches import (
    count_batches_by_status,
    create_batch,
    get_batch,
    list_batches,
    update_batch_progress,
    update_batch_status,
)
from autoagent.storage.database import init_db
from autoagent.storage.samples import (
    list_samples_by_session_id,
    list_samples_for_batch,
    list_samples_for_batches,
    upsert_sample,
)


async def test_batch_create_and_get():
    await init_db()
    await create_batch(
        batch_id="b1", name="test", mode="api", concurrency=2, total=3, target_profile_default=None
    )
    b = await get_batch("b1")
    assert b is not None
    assert b.name == "test"
    assert b.total == 3
    assert b.status == "queued"


async def test_batch_list_orders_newest_first():
    await init_db()
    await create_batch(
        batch_id="b1", name="n1", mode="api", concurrency=1, total=1, target_profile_default=None
    )
    await asyncio.sleep(0.01)
    await create_batch(
        batch_id="b2", name="n2", mode="api", concurrency=1, total=1, target_profile_default=None
    )
    batches = await list_batches(limit=10, offset=0)
    assert batches[0].id == "b2"


async def test_sample_upsert_and_list():
    await init_db()
    await create_batch(
        batch_id="b1", name="t", mode="api", concurrency=1, total=2, target_profile_default=None
    )
    r = SampleResult(
        id="t1",
        status="done",
        prompts_sent=["p"],
        responses=["r"],
        llm_responses=["lr"],
        llm_errors=[None],
        duration_ms=10,
        attempt_count=1,
        mode="api",
        target_profile="pf",
    )
    await upsert_sample("b1", r)
    rs = await list_samples_for_batch("b1")
    assert len(rs) == 1
    assert rs[0].id == "t1"
    assert rs[0].status == "done"
    assert rs[0].llm_responses == ["lr"]
    assert rs[0].llm_errors == [None]


async def test_list_samples_for_batches_groups_by_batch_in_one_query():
    await init_db()
    await create_batch(
        batch_id="b1", name="t", mode="api", concurrency=1, total=1, target_profile_default=None
    )
    await create_batch(
        batch_id="b2", name="t", mode="api", concurrency=1, total=1, target_profile_default=None
    )
    await upsert_sample("b1", SampleResult(id="s1", status="done", mode="api", target_profile="pf"))
    await upsert_sample("b2", SampleResult(id="s2", status="done", mode="api", target_profile="pf"))

    by_batch = await list_samples_for_batches(["b1", "b2", "b3-missing"])

    assert {s.id for s in by_batch["b1"]} == {"s1"}
    assert {s.id for s in by_batch["b2"]} == {"s2"}
    assert "b3-missing" not in by_batch


async def test_list_samples_for_batches_empty_ids_returns_empty_map():
    assert await list_samples_for_batches([]) == {}


async def test_list_batches_filters_by_status_and_mode():
    await init_db()
    await create_batch(
        batch_id="b1", name="n1", mode="api", concurrency=1, total=1, target_profile_default=None
    )
    await create_batch(
        batch_id="b2",
        name="n2",
        mode="gui_android",
        concurrency=1,
        total=1,
        target_profile_default=None,
    )
    await update_batch_status("b2", "failed")

    only_failed = await list_batches(limit=10, offset=0, status=["failed"])
    assert [b.id for b in only_failed] == ["b2"]

    only_api = await list_batches(limit=10, offset=0, mode=["api"])
    assert [b.id for b in only_api] == ["b1"]

    # b1 is mode=api/status=queued, b2 is mode=gui_android/status=failed —
    # no batch matches both filters at once.
    assert await list_batches(limit=10, offset=0, status=["failed"], mode=["api"]) == []


async def test_count_batches_by_status_has_no_status_filter_but_respects_mode():
    await init_db()
    await create_batch(
        batch_id="b1", name="n1", mode="api", concurrency=1, total=1, target_profile_default=None
    )
    await create_batch(
        batch_id="b2",
        name="n2",
        mode="gui_android",
        concurrency=1,
        total=1,
        target_profile_default=None,
    )
    await update_batch_status("b2", "failed")

    counts = await count_batches_by_status(mode=["gui_android"])
    assert counts == {"failed": 1, "total": 1}


async def test_list_samples_by_session_id_spans_batches_ordered_by_time():
    """A session_id conversation is typically a sequence of separate
    single-sample batches (each turn its own /tests/sync-style submission),
    not one batch — so reconstruction must query across the whole table,
    not one batch_id, and come back in conversation order regardless of
    which batch was created/updated last."""
    import datetime as dt

    await init_db()
    entries = [("b2", "turn-2", 2), ("b1", "turn-1", 1), ("b3", "turn-3", 3)]
    for batch_id, sample_id, minute in entries:
        await create_batch(
            batch_id=batch_id, name=batch_id, mode="agent_android", concurrency=1,
            total=1, target_profile_default=None,
        )
        await upsert_sample(
            batch_id,
            SampleResult(
                id=sample_id,
                status="done",
                prompts_sent=[f"prompt {minute}"],
                responses=[f"response {minute}"],
                mode="agent_android",
                target_profile="p",
                started_at=dt.datetime(2026, 1, 1, 0, minute, tzinfo=dt.timezone.utc),
                session_id="conv-1",
            ),
        )
    # A different session_id must not leak in.
    await create_batch(
        batch_id="other", name="other", mode="agent_android", concurrency=1,
        total=1, target_profile_default=None,
    )
    await upsert_sample(
        "other",
        SampleResult(
            id="turn-x", status="done", mode="agent_android", target_profile="p",
            session_id="conv-2",
        ),
    )

    turns = await list_samples_by_session_id("conv-1")
    assert [batch_id for batch_id, _ in turns] == ["b1", "b2", "b3"]
    assert [r.id for _, r in turns] == ["turn-1", "turn-2", "turn-3"]


async def test_list_samples_by_session_id_empty_for_unknown_session():
    await init_db()
    assert await list_samples_by_session_id("never-existed") == []


async def test_update_progress():
    await init_db()
    await create_batch(
        batch_id="b1", name="t", mode="api", concurrency=1, total=10, target_profile_default=None
    )
    await update_batch_progress("b1", done=5, failed=1, avg_duration_ms=100, total_duration_ms=500)
    b = await get_batch("b1")
    assert b.done == 5
    assert b.failed == 1
