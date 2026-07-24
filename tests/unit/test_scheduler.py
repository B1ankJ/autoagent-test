import asyncio
from contextlib import asynccontextmanager

import pytest

from autoagent.devices.pool import DeviceBusy, DeviceDisabled, DevicePool, DeviceReserved
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
        async def acquire(
            self,
            preferred: str | None,
            timeout_sec: float = 60,
            cancel_event=None,
            *,
            allowed_serials: set[str] | None = None,
            session_id: str | None = None,
            new_session: bool = False,
        ):
            seen["preferred"] = preferred
            seen["timeout_sec"] = timeout_sec
            seen["allowed_serials"] = allowed_serials
            seen["session_id"] = session_id
            seen["new_session"] = new_session
            yield "emulator-5554"

    await init_db()
    scheduler = BatchScheduler(
        executor_factory=lambda _mode: DeviceAwareExecutor(),
        profile_lookup=lambda _name: type("P", (), {"serial": None})(),
        device_pool=FakePool(),
    )
    sample = Sample(
        id="s1",
        prompts=["x"],
        mode="agent_android",
        target_profile="p",
        session_id="conv-1",
        new_session=True,
    )

    batch_id = await scheduler.submit(
        name="b",
        mode="agent_android",
        concurrency=3,
        samples=[sample],
    )
    await scheduler.wait_done(batch_id, timeout_sec=5)

    assert seen["device_serial"] == "emulator-5554"
    assert seen["preferred"] is None
    assert seen["session_id"] == "conv-1"
    assert seen["new_session"] is True


def test_resolve_concurrency_capped_by_bound_pool():
    from types import SimpleNamespace

    from autoagent.scheduler.batch_scheduler import _resolve_concurrency

    samples = [
        Sample(id=f"s{i}", prompts=["hi"], mode="gui_android", target_profile="p")
        for i in range(10)
    ]

    # Profile bound to 2 devices; 5 online globally, requested 8 → cap to 2.
    def lookup(_n):
        return SimpleNamespace(serial=None, serials=["A", "B"])

    n = _resolve_concurrency(8, "gui_android", samples, lookup, available_devices=5)
    assert n == 2


def test_resolve_concurrency_unbound_uses_available():
    from types import SimpleNamespace

    from autoagent.scheduler.batch_scheduler import _resolve_concurrency

    samples = [
        Sample(id=f"s{i}", prompts=["hi"], mode="gui_android", target_profile="p")
        for i in range(10)
    ]

    # Unbound profile (any online device) → capped only by available_devices.
    def lookup(_n):
        return SimpleNamespace(serial=None, serials=[])

    n = _resolve_concurrency(8, "gui_android", samples, lookup, available_devices=3)
    assert n == 3


async def test_end_session_skips_execution_and_releases_pin():
    called = []

    class TrackingExec(Executor):
        async def execute(self, sample, profile, ctx):
            called.append(sample.id)
            return ["should not run"]

    pool = DevicePool(lambda: [])
    pool._remember_pin("conv-1", "emulator-5554")
    await init_db()
    scheduler = BatchScheduler(
        executor_factory=lambda _mode: TrackingExec(),
        profile_lookup=lambda _name: object(),
        device_pool=pool,
    )
    sample = Sample(
        id="s1",
        prompts=["ignored"],
        mode="agent_android",
        target_profile="p",
        session_id="conv-1",
        end_session=True,
    )

    batch_id = await scheduler.submit(
        name="b", mode="agent_android", concurrency=1, samples=[sample]
    )
    await scheduler.wait_done(batch_id, timeout_sec=5)

    results = await list_samples_for_batch(batch_id)
    assert results[0].status == "done"
    assert results[0].metadata["session_released"] is True
    assert called == []  # executor never ran
    assert pool._lookup_pin("conv-1") is None


async def test_end_session_without_session_id_is_a_noop():
    await init_db()
    scheduler = BatchScheduler(
        executor_factory=lambda _mode: EchoExec(),
        profile_lookup=lambda _name: object(),
        device_pool=DevicePool(lambda: []),
    )
    sample = Sample(id="s1", prompts=["ignored"], mode="api", target_profile="p", end_session=True)

    batch_id = await scheduler.submit(name="b", mode="api", concurrency=1, samples=[sample])
    await scheduler.wait_done(batch_id, timeout_sec=5)

    results = await list_samples_for_batch(batch_id)
    assert results[0].status == "done"
    assert results[0].metadata["session_released"] is False


async def test_device_reserved_becomes_failed_result_with_blocking_sessions():
    class RejectingPool:
        def available_count_sync(self) -> int:
            return 0

        @asynccontextmanager
        async def acquire(self, *args, **kwargs):
            raise DeviceReserved("all reserved", blocking_session_ids=["conv-other"])
            yield  # pragma: no cover - unreachable, satisfies async generator shape

    await init_db()
    scheduler = BatchScheduler(
        executor_factory=lambda _mode: EchoExec(),
        profile_lookup=lambda _name: type("P", (), {"serial": None})(),
        device_pool=RejectingPool(),
    )
    sample = Sample(
        id="s1",
        prompts=["x"],
        mode="agent_android",
        target_profile="p",
        session_id="conv-me",
        new_session=True,
    )

    batch_id = await scheduler.submit(
        name="b", mode="agent_android", concurrency=1, samples=[sample]
    )
    await scheduler.wait_done(batch_id, timeout_sec=5)

    b = await get_batch(batch_id)
    assert b.status == "failed"  # batch reaches a real terminal status, doesn't hang
    results = await list_samples_for_batch(batch_id)
    assert results[0].status == "failed"
    assert results[0].metadata["blocking_session_ids"] == ["conv-other"]


async def test_device_busy_no_longer_crashes_the_batch_task():
    # Regression: acquire() raising DeviceBusy/DeviceDisabled used to
    # propagate uncaught out of run_one(), crashing _run()'s background
    # task before it ever called update_batch_status — the batch would
    # stay stuck showing "running" forever.
    class TimingOutPool:
        def available_count_sync(self) -> int:
            return 0

        @asynccontextmanager
        async def acquire(self, *args, **kwargs):
            raise DeviceBusy("no device available within 0.0s")
            yield  # pragma: no cover - unreachable, satisfies async generator shape

    await init_db()
    scheduler = BatchScheduler(
        executor_factory=lambda _mode: EchoExec(),
        profile_lookup=lambda _name: type("P", (), {"serial": None})(),
        device_pool=TimingOutPool(),
    )
    sample = Sample(id="s1", prompts=["x"], mode="agent_android", target_profile="p")

    batch_id = await scheduler.submit(
        name="b", mode="agent_android", concurrency=1, samples=[sample]
    )
    await scheduler.wait_done(batch_id, timeout_sec=5)

    b = await get_batch(batch_id)
    assert b.status == "failed"
    results = await list_samples_for_batch(batch_id)
    assert results[0].status == "failed"
    assert "no device available" in results[0].error


async def test_device_disabled_also_produces_a_failed_result():
    class OfflinePool:
        def available_count_sync(self) -> int:
            return 0

        @asynccontextmanager
        async def acquire(self, *args, **kwargs):
            raise DeviceDisabled("all devices in pool offline/disabled: ['emulator-5554']")
            yield  # pragma: no cover - unreachable, satisfies async generator shape

    await init_db()
    scheduler = BatchScheduler(
        executor_factory=lambda _mode: EchoExec(),
        profile_lookup=lambda _name: type("P", (), {"serial": None})(),
        device_pool=OfflinePool(),
    )
    sample = Sample(id="s1", prompts=["x"], mode="agent_android", target_profile="p")

    batch_id = await scheduler.submit(
        name="b", mode="agent_android", concurrency=1, samples=[sample]
    )
    await scheduler.wait_done(batch_id, timeout_sec=5)

    results = await list_samples_for_batch(batch_id)
    assert results[0].status == "failed"
    assert "offline/disabled" in results[0].error
