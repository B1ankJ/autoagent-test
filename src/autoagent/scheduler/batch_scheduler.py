from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from autoagent.config.settings import get_settings
from autoagent.devices.pool import DeviceBusy, DeviceDisabled, DevicePool, DeviceReserved
from autoagent.events.bus import get_event_bus
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Mode, Sample, SampleResult
from autoagent.notifications.rules import on_sample_result as _notify_on_sample
from autoagent.results.writer import ResultWriter
from autoagent.storage.batches import (
    create_batch,
    update_batch_progress,
    update_batch_status,
)
from autoagent.storage.samples import upsert_sample
from autoagent.webhooks.sender import send_webhook

log = logging.getLogger(__name__)


def _resolve_concurrency(
    requested: int,
    mode: str,
    samples: list[Sample],
    profile_lookup: Callable[[str], Any],
    *,
    available_devices: int | None = None,
    logger: logging.Logger = log,
) -> int:
    if mode in {"gui_android", "agent_android"}:
        avail = max(1, available_devices or 1)
        capped = min(requested, avail)
        # If every distinct profile binds a device pool, a sample can only run
        # on one of those pooled devices — so concurrency above the union of
        # bound serials just parks extra samples in acquire-wait. Cap by it.
        bound: set[str] = set()
        all_bound = True
        for name in {s.target_profile for s in samples}:
            try:
                profile = profile_lookup(name)
            except Exception:
                all_bound = False
                break
            serial = getattr(profile, "serial", None)
            serials = list(getattr(profile, "serials", None) or [])
            if serial:
                serials.append(serial)
            if serials:
                bound.update(serials)
            else:
                all_bound = False  # this profile can use any online device
                break
        if all_bound and bound:
            capped = min(capped, len(bound))
        return max(1, capped)

    if mode != "gui_pc_web" or not samples:
        return max(1, requested)

    seen: set[str] = set()
    for sample in samples:
        if sample.target_profile in seen:
            continue
        seen.add(sample.target_profile)
        try:
            profile = profile_lookup(sample.target_profile)
        except Exception:
            continue
        user_data_dir = getattr(getattr(profile, "browser", None), "user_data_dir", None)
        if user_data_dir:
            if requested > 1:
                logger.warning(
                    "batch: profile %s has user_data_dir=%s; forcing concurrency=1 (requested %d)",
                    profile.name,
                    user_data_dir,
                    requested,
                )
            return 1
    return max(1, requested)


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
        device_pool: DevicePool | None = None,
    ):
        self._executor_factory = executor_factory
        self._profile_lookup = profile_lookup
        self._device_pool = device_pool
        self._states: dict[str, _RunState] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def submit(
        self,
        *,
        name: str,
        mode: Mode,
        concurrency: int,
        samples: list[Sample],
        target_profile_default: str | None = None,
    ) -> str:
        batch_id = f"b_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        effective = _resolve_concurrency(
            concurrency,
            mode,
            samples,
            self._profile_lookup,
                available_devices=(
                    self._device_pool.available_count_sync()
                if mode in {"gui_android", "agent_android"} and self._device_pool
                else None
            ),
        )
        state = _RunState(
            samples=samples,
            mode=mode,
            concurrency=effective,
            target_profile_default=target_profile_default,
        )
        self._states[batch_id] = state
        # Persisted verbatim so /replay can resubmit an identical batch later
        # — SampleResult (what execution actually writes to the DB) doesn't
        # carry request-only fields like new_session/timeout_sec/retry/
        # dry_run/callback_url, so this is the only faithful record of them.
        samples_request_json = json.dumps(
            [s.model_dump(mode="json") for s in samples], ensure_ascii=False
        )
        await create_batch(
            batch_id=batch_id,
            name=name,
            mode=mode,
            concurrency=state.concurrency,
            total=len(samples),
            target_profile_default=target_profile_default,
            samples_request_json=samples_request_json,
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
        bus = get_event_bus()
        writer = ResultWriter(batch_id)
        sem = asyncio.Semaphore(state.concurrency)
        start = time.monotonic()
        final_status = "failed"

        async def run_one(sample: Sample) -> None:
            async with sem:
                await bus.publish(
                    batch_id,
                    "sample_update",
                    {"sample_id": sample.id, "status": "running"},
                )
                if state.cancel_event.is_set():
                    result = SampleResult(
                        id=sample.id,
                        status="cancelled",
                        prompts_sent=list(sample.prompts),
                        mode=sample.mode,
                        target_profile=sample.target_profile,
                    )
                elif sample.end_session:
                    # Purely a "release the device now" signal — no profile
                    # lookup, no device acquisition, no executor run. The
                    # required `prompts` field is present but deliberately
                    # unused.
                    released = (
                        self._device_pool.release_session(sample.session_id)
                        if sample.session_id is not None and self._device_pool is not None
                        else False
                    )
                    result = SampleResult(
                        id=sample.id,
                        status="done",
                        prompts_sent=[],
                        mode=sample.mode,
                        target_profile=sample.target_profile,
                        metadata={"session_released": released},
                    )
                else:
                    # Resolve profile
                    try:
                        profile = self._profile_lookup(sample.target_profile)
                    except Exception as e:
                        result = SampleResult(
                            id=sample.id,
                            status="failed",
                            prompts_sent=list(sample.prompts),
                            mode=sample.mode,
                            target_profile=sample.target_profile,
                            error=f"profile lookup failed: {e}",
                        )
                    else:
                        default_timeout = (
                            settings.default_api_timeout_sec
                            if sample.mode == "api"
                            else settings.default_gui_timeout_sec
                        )
                        ctx = ExecutorContext(
                            logs_dir=batch_id,
                            verbose_logs=settings.default_verbose_logs,
                        )
                        executor = self._executor_factory(sample.mode)
                        if (
                            sample.mode in {"gui_android", "agent_android"}
                            and self._device_pool is not None
                        ):
                            await bus.publish(
                                batch_id,
                                "sample_update",
                                {
                                    "sample_id": sample.id,
                                    "status": "running",
                                    "waiting_for_device": True,
                                },
                            )
                            # Multi-device pool support: a profile may name
                            # a `serials` list to fan out across N phones.
                            # `serial` (legacy single field) still works.
                            profile_serial = getattr(profile, "serial", None)
                            profile_serials = getattr(profile, "serials", None) or []
                            pool_set: set[str] | None = (
                                set(profile_serials) if profile_serials else None
                            )
                            try:
                                async with self._device_pool.acquire(
                                    profile_serial,
                                    timeout_sec=settings.device_acquire_timeout_sec,
                                    cancel_event=state.cancel_event,
                                    allowed_serials=pool_set,
                                    session_id=sample.session_id,
                                    new_session=sample.new_session,
                                ) as serial:
                                    ctx.device_serial = serial
                                    ctx.action_replay_path = (
                                        settings.logs_root
                                        / batch_id
                                        / sample.id
                                        / "actions.jsonl"
                                    )
                                    await bus.publish(
                                        batch_id,
                                        "sample_update",
                                        {
                                            "sample_id": sample.id,
                                            "status": "running",
                                            "waiting_for_device": False,
                                            "device_serial": serial,
                                        },
                                    )
                                    result = await executor.run(
                                        sample,
                                        profile=profile,
                                        default_timeout_sec=default_timeout,
                                        ctx=ctx,
                                    )
                            except DeviceReserved as e:
                                # Fast-fail case (see devices/pool.py): don't
                                # even try to acquire — surface which
                                # session(s) are holding every device so the
                                # API layer can translate this into a 429
                                # instead of a generic failure.
                                result = SampleResult(
                                    id=sample.id,
                                    status="failed",
                                    prompts_sent=list(sample.prompts),
                                    mode=sample.mode,
                                    target_profile=sample.target_profile,
                                    error=str(e),
                                    metadata={"blocking_session_ids": e.blocking_session_ids},
                                )
                            except (DeviceBusy, DeviceDisabled) as e:
                                # Previously uncaught — DeviceBusy (timeout
                                # waiting) / DeviceDisabled (pool offline)
                                # from acquire() used to propagate out of
                                # run_one() entirely, crashing this batch's
                                # background task without ever recording a
                                # result or updating batch status.
                                result = SampleResult(
                                    id=sample.id,
                                    status="failed",
                                    prompts_sent=list(sample.prompts),
                                    mode=sample.mode,
                                    target_profile=sample.target_profile,
                                    error=str(e),
                                )
                        else:
                            result = await executor.run(
                                sample,
                                profile=profile,
                                default_timeout_sec=default_timeout,
                                ctx=ctx,
                            )

                writer.append(result)
                try:
                    await upsert_sample(batch_id, result)
                except Exception:
                    log.exception("failed to persist sample %s", sample.id)
                # Fire notification rules (DingTalk etc.). Best-effort; the
                # rule layer swallows its own exceptions so a misconfigured
                # webhook can't stall batch progress.
                await _notify_on_sample(result, batch_id)

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
                            batch_id,
                            done=state.done_count,
                            failed=state.failed_count,
                            total_duration_ms=state.total_duration_ms,
                            avg_duration_ms=(
                                state.total_duration_ms
                                // max(1, state.done_count + state.failed_count)
                            ),
                        )
                    except Exception:
                        log.exception("failed to update batch progress")
                    try:
                        await bus.publish(
                            batch_id,
                            "sample_update",
                            {
                                "sample_id": sample.id,
                                "status": result.status,
                                "duration_ms": result.duration_ms,
                                "device_serial": ctx.device_serial,
                                "waiting_for_device": False,
                            },
                        )
                        await bus.publish(
                            batch_id,
                            "batch_progress",
                            {
                                "done": state.done_count,
                                "failed": state.failed_count,
                                "total": len(state.samples),
                                "running": 0,
                            },
                        )
                    except Exception:
                        log.exception("failed to publish batch progress events")

                if sample.callback_url:
                    try:
                        await send_webhook(sample.callback_url, result)
                    except Exception:
                        log.exception("webhook failed for %s", sample.id)

        try:
            await asyncio.gather(*(run_one(s) for s in state.samples))
            final_status = (
                "cancelled"
                if state.cancel_event.is_set()
                else ("done" if state.failed_count == 0 else "failed")
            )
            await update_batch_status(batch_id, final_status)
        finally:
            writer.close()
            try:
                await bus.publish(batch_id, "batch_done", {"status": final_status})
            except Exception:
                log.exception("failed to publish batch_done for %s", batch_id)
            state.done_event.set()
            log.info("batch %s complete in %.1fs", batch_id, time.monotonic() - start)
