from __future__ import annotations

import asyncio
import logging

import pytest

from autoagent.models.api import Sample, SampleResult
from autoagent.profiles.schemas import (
    ActionStep,
    DomStable,
    WebBrowserConfig,
    WebProfile,
    WebReadyCheck,
    WebSendMethodKeyboard,
)
from autoagent.scheduler.batch_scheduler import BatchScheduler
from autoagent.storage.database import init_db


class _RecordingExecutor:
    def __init__(self) -> None:
        self._peak = 0
        self._active = 0
        self._lock = asyncio.Lock()

    async def run(self, sample, profile, default_timeout_sec, ctx):  # noqa: ANN001
        async with self._lock:
            self._active += 1
            self._peak = max(self._peak, self._active)
        await asyncio.sleep(0.05)
        async with self._lock:
            self._active -= 1
        return SampleResult(
            id=sample.id,
            status="done",
            prompts_sent=list(sample.prompts),
            responses=["ok"],
            duration_ms=50,
            mode=sample.mode,
            target_profile=sample.target_profile,
            attempt_count=1,
        )


def _persistent_profile(name: str, user_data_dir: str) -> WebProfile:
    return WebProfile(
        name=name,
        platform="web",
        url="about:blank",
        browser=WebBrowserConfig(headless=True, user_data_dir=user_data_dir),
        ready_check=WebReadyCheck(type="dom_selector", selector="#x", timeout_sec=1),
        recovery_path=[ActionStep(action="goto", url="about:blank")],
        input_selector="#x",
        send_method=WebSendMethodKeyboard(type="keyboard", key="Enter"),
        response_container_selector="#x",
        complete_detection=DomStable(type="dom_stable", stable_sec=0.1, max_wait_sec=1),
    )


async def test_web_profile_with_user_data_dir_forces_concurrency_1(
    caplog: pytest.LogCaptureFixture, tmp_path
) -> None:
    await init_db()
    prof = _persistent_profile("p_persist", str(tmp_path))
    executor = _RecordingExecutor()

    scheduler = BatchScheduler(
        executor_factory=lambda _m: executor,
        profile_lookup=lambda _n: prof,
    )

    samples = [
        Sample(id=f"s{i}", prompts=["hi"], mode="gui_pc_web", target_profile="p_persist")
        for i in range(4)
    ]

    caplog.set_level(logging.WARNING, logger="autoagent.scheduler.batch_scheduler")
    batch_id = await scheduler.submit(
        name="t", mode="gui_pc_web", concurrency=4, samples=samples
    )
    await scheduler.wait_done(batch_id, timeout_sec=30)

    assert executor._peak == 1, f"expected serial execution, got peak={executor._peak}"
    assert any("user_data_dir" in record.message.lower() for record in caplog.records)
