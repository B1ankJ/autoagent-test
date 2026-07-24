from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from autoagent.models.api import Sample, SampleResult


class SyncSampleResultMissingError(RuntimeError):
    """Raised when batch execution finishes without a recorded sample result."""


def blocking_session_ids(result: SampleResult) -> list[str] | None:
    """Session ids holding every device this sample could have used, if
    that's why it failed (see devices/pool.py::DeviceReserved). Callers
    use this to translate the result into an HTTP 429 instead of a
    generic failure — the caller's own sample-level status/error stay a
    plain "failed" either way, since this is only surfaced at the
    synchronous single-sample endpoints (`/tests/sync`,
    `/v1/chat/completions`), not batch execution in general.
    """
    ids = result.metadata.get("blocking_session_ids")
    return ids or None


class SyncSampleScheduler(Protocol):
    async def submit(
        self,
        *,
        name: str,
        mode: str,
        concurrency: int,
        samples: list[Sample],
    ) -> str: ...

    async def wait_done(self, batch_id: str, timeout_sec: float | None = None) -> None: ...


async def execute_sync_sample(
    sample: Sample,
    *,
    get_scheduler_fn: Callable[[], SyncSampleScheduler],
    list_samples_for_batch_fn: Callable[[str], Awaitable[list[SampleResult]]],
) -> SampleResult:
    scheduler = get_scheduler_fn()
    batch_id = await scheduler.submit(
        name=f"sync-{sample.id}",
        mode=sample.mode,
        concurrency=1,
        samples=[sample],
    )
    wait_timeout = sample.timeout_sec or (180 if sample.mode == "gui_android" else 600)
    # sample.timeout_sec is the per-sample timeout; we wait slightly longer
    # to absorb executor startup/teardown, including GUI driver startup time.
    await scheduler.wait_done(batch_id, timeout_sec=wait_timeout + 30)
    results = await list_samples_for_batch_fn(batch_id)
    if not results:
        raise SyncSampleResultMissingError("no result recorded")
    return results[0]
