import asyncio
from typing import Any

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample


class FakeExecutor(Executor):
    def __init__(self, *, flaky_for: int = 0):
        self.calls = 0
        self.flaky_for = flaky_for

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        self.calls += 1
        if self.calls <= self.flaky_for:
            raise RuntimeError("boom")
        return [f"reply to: {p}" for p in sample.prompts]


async def test_retry_and_success():
    ex = FakeExecutor(flaky_for=1)
    s = Sample(id="t1", prompts=["hello"], mode="api", target_profile="p", retry=2)
    result = await ex.run(s, profile=object(), default_timeout_sec=10)
    assert result.status == "done"
    assert result.attempt_count == 2
    assert result.responses == ["reply to: hello"]


async def test_all_retries_fail():
    ex = FakeExecutor(flaky_for=99)
    s = Sample(id="t1", prompts=["x"], mode="api", target_profile="p", retry=1)
    result = await ex.run(s, profile=object(), default_timeout_sec=10)
    assert result.status == "failed"
    assert result.attempt_count == 2
    assert "boom" in (result.error or "")


async def test_timeout_marks_timeout_status():
    class Slow(Executor):
        async def execute(self, *a, **k):
            await asyncio.sleep(10)
            return []

    s = Sample(id="t1", prompts=["x"], mode="api", target_profile="p", retry=0, timeout_sec=1)
    result = await Slow().run(s, profile=object(), default_timeout_sec=1)
    assert result.status == "timeout"


async def test_dry_run_returns_placeholder():
    ex = FakeExecutor()
    s = Sample(id="t1", prompts=["p1", "p2"], mode="api", target_profile="p", dry_run=True)
    result = await ex.run(s, profile=object(), default_timeout_sec=10)
    assert result.status == "done"
    assert all(r.startswith("[DRY RUN]") for r in result.responses)
