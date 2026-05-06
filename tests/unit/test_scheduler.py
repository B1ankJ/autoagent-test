import asyncio
from contextlib import asynccontextmanager

import pytest

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample
from autoagent.scheduler.batch_scheduler import BatchScheduler
from autoagent.storage.batches import get_batch
from autoagent.storage.database import init_db
from autoagent.storage.samples import list_samples_for_batch


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
    sch = BatchScheduler(
        executor_factory=lambda mode: EchoExec(), profile_lookup=lambda name: object()
    )
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


async def test_agent_android_mode_acquires_device_and_passes_ctx_serial():
    seen: dict[str, object] = {}

    class DeviceAwareExecutor(Executor):
        async def execute(self, sample, profile, ctx: ExecutorContext):  # noqa: ANN001
            seen["device_serial"] = ctx.device_serial
            return ["ok"]

    class FakePool:
        def available_count_sync(self) -> int:
            return 1

        @asynccontextmanager
        async def acquire(self, preferred: str | None, timeout_sec: float = 60):
            seen["preferred"] = preferred
            seen["timeout_sec"] = timeout_sec
            yield "emulator-5554"

    await init_db()
    scheduler = BatchScheduler(
        executor_factory=lambda _mode: DeviceAwareExecutor(),
        profile_lookup=lambda _name: type("P", (), {"serial": None})(),
        device_pool=FakePool(),
    )
    sample = Sample(id="s1", prompts=["x"], mode="agent_android", target_profile="p")

    batch_id = await scheduler.submit(
        name="b",
        mode="agent_android",
        concurrency=3,
        samples=[sample],
    )
    await scheduler.wait_done(batch_id, timeout_sec=5)

    assert seen["device_serial"] == "emulator-5554"
    assert seen["preferred"] is None
