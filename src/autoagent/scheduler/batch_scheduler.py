from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from autoagent.config.settings import get_settings
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Mode, Sample, SampleResult
from autoagent.results.writer import ResultWriter
from autoagent.storage.batches import (
    create_batch,
    update_batch_progress,
    update_batch_status,
)
from autoagent.storage.samples import upsert_sample
from autoagent.webhooks.sender import send_webhook

log = logging.getLogger(__name__)


@dataclass
class _RunState:
    samples: list[Sample]
    mode: Mode
    concurrency: int
    target_profile_default: str | None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    progress_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done_count: int = 0
    failed_count: int = 0
    total_duration_ms: int = 0
    results: list[SampleResult] = field(default_factory=list)


class BatchScheduler:
    def __init__(
        self,
        executor_factory: Callable[[str], Executor],
        profile_lookup: Callable[[str], Any],
    ):
        self._executor_factory = executor_factory
        self._profile_lookup = profile_lookup
        self._states: dict[str, _RunState] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def submit(
        self, *, name: str, mode: Mode, concurrency: int, samples: list[Sample],
        target_profile_default: str | None = None,
    ) -> str:
        batch_id = f"b_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        state = _RunState(
            samples=samples, mode=mode, concurrency=max(1, concurrency),
            target_profile_default=target_profile_default,
        )
        self._states[batch_id] = state
        await create_batch(
            batch_id=batch_id, name=name, mode=mode, concurrency=state.concurrency,
            total=len(samples), target_profile_default=target_profile_default,
        )
        self._tasks[batch_id] = asyncio.create_task(self._run(batch_id, state))
        return batch_id

    async def cancel(self, batch_id: str) -> bool:
        state = self._states.get(batch_id)
        if state is None:
            return False
        state.cancel_event.set()
        return True

    async def wait_done(self, batch_id: str, timeout_sec: float | None = None) -> None:
        state = self._states.get(batch_id)
        if state is None:
            return
        await asyncio.wait_for(state.done_event.wait(), timeout=timeout_sec)

    def get_results(self, batch_id: str) -> list[SampleResult]:
        state = self._states.get(batch_id)
        return list(state.results) if state else []

    async def _run(self, batch_id: str, state: _RunState) -> None:
        settings = get_settings()
        await update_batch_status(batch_id, "running")
        writer = ResultWriter(batch_id)
        sem = asyncio.Semaphore(state.concurrency)
        start = time.monotonic()

        async def run_one(sample: Sample) -> None:
            async with sem:
                if state.cancel_event.is_set():
                    result = SampleResult(
                        id=sample.id, status="cancelled", prompts_sent=list(sample.prompts),
                        mode=sample.mode, target_profile=sample.target_profile,
                    )
                else:
                    # Resolve profile
                    try:
                        profile = self._profile_lookup(sample.target_profile)
                    except Exception as e:
                        result = SampleResult(
                            id=sample.id, status="failed", prompts_sent=list(sample.prompts),
                            mode=sample.mode, target_profile=sample.target_profile,
                            error=f"profile lookup failed: {e}",
                        )
                    else:
                        default_timeout = (
                            settings.default_api_timeout_sec if sample.mode == "api"
                            else settings.default_gui_timeout_sec
                        )
                        ctx = ExecutorContext(verbose_logs=settings.default_verbose_logs)
                        executor = self._executor_factory(sample.mode)
                        result = await executor.run(
                            sample, profile=profile, default_timeout_sec=default_timeout, ctx=ctx,
                        )

                writer.append(result)
                try:
                    await upsert_sample(batch_id, result)
                except Exception:
                    log.exception("failed to persist sample %s", sample.id)

                async with state.progress_lock:
                    state.results.append(result)
                    if result.status == "done":
                        state.done_count += 1
                    else:
                        state.failed_count += 1
                    if result.duration_ms:
                        state.total_duration_ms += result.duration_ms

                    try:
                        await update_batch_progress(
                            batch_id, done=state.done_count, failed=state.failed_count,
                            total_duration_ms=state.total_duration_ms,
                            avg_duration_ms=(
                                state.total_duration_ms
                                // max(1, state.done_count + state.failed_count)
                            ),
                        )
                    except Exception:
                        log.exception("failed to update batch progress")

                if sample.callback_url:
                    try:
                        await send_webhook(sample.callback_url, result)
                    except Exception:
                        log.exception("webhook failed for %s", sample.id)

        try:
            await asyncio.gather(*(run_one(s) for s in state.samples))
            final_status = (
                "cancelled" if state.cancel_event.is_set()
                else ("done" if state.failed_count == 0 else "failed")
            )
            await update_batch_status(batch_id, final_status)
        finally:
            writer.close()
            state.done_event.set()
            log.info("batch %s complete in %.1fs", batch_id, time.monotonic() - start)
