import asyncio

from autoagent.models.api import SampleResult
from autoagent.storage.batches import (
    create_batch,
    get_batch,
    list_batches,
    update_batch_progress,
)
from autoagent.storage.database import init_db
from autoagent.storage.samples import (
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


async def test_update_progress():
    await init_db()
    await create_batch(
        batch_id="b1", name="t", mode="api", concurrency=1, total=10, target_profile_default=None
    )
    await update_batch_progress("b1", done=5, failed=1, avg_duration_ms=100, total_duration_ms=500)
    b = await get_batch("b1")
    assert b.done == 5
    assert b.failed == 1
