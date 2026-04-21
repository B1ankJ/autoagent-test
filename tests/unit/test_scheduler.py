import asyncio

import pytest

from autoagent.models.api import Sample
from autoagent.scheduler.batch_scheduler import BatchScheduler
from autoagent.storage.database import init_db
from autoagent.storage.batches import get_batch
from autoagent.storage.samples import list_samples_for_batch
from autoagent.executors.base import Executor, ExecutorContext


class EchoExec(Executor):
    def __init__(self, delay: float = 0):
        self.delay = delay

    async def execute(self, sample, profile, ctx: ExecutorContext) -> list[str]:
        if self.delay:
            await asyncio.sleep(self.delay)
        return [f"echo:{p}" for p in sample.prompts]


@pytest.fixture
async def scheduler(monkeypatch):
    await init_db()
    sch = BatchScheduler(executor_factory=lambda mode: EchoExec(), profile_lookup=lambda name: object())
    yield sch


async def test_run_batch_completes_all(scheduler):
    samples = [Sample(id=f"t{i}", prompts=["x"], mode="api", target_profile="p") for i in range(3)]
    batch_id = await scheduler.submit(name="b", mode="api", concurrency=2, samples=samples)
    await scheduler.wait_done(batch_id, timeout_sec=5)
    b = await get_batch(batch_id)
    assert b.status == "done"
    assert b.done == 3
    assert b.failed == 0
    results = await list_samples_for_batch(batch_id)
    assert len(results) == 3
    assert all(r.status == "done" for r in results)


async def test_concurrency_limits_parallelism():
    # Executor that tracks concurrent running count
    import itertools
    current = itertools.count()
    max_seen = [0]
    now_running = [0]

    class Tracker(Executor):
        async def execute(self, sample, profile, ctx):
            now_running[0] += 1
            max_seen[0] = max(max_seen[0], now_running[0])
            await asyncio.sleep(0.05)
            now_running[0] -= 1
            return ["ok"]

    await init_db()
    sch = BatchScheduler(executor_factory=lambda mode: Tracker(), profile_lookup=lambda n: object())
    samples = [Sample(id=f"t{i}", prompts=["x"], mode="api", target_profile="p") for i in range(6)]
    batch_id = await sch.submit(name="b", mode="api", concurrency=2, samples=samples)
    await sch.wait_done(batch_id, timeout_sec=5)
    assert max_seen[0] <= 2
