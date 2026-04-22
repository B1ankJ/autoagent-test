from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoagent.models.api import Sample, SampleResult


@dataclass
class ExecutorContext:
    logs_dir: str | None = None
    verbose_logs: bool = True
    api_timeout_sec: int = 60
    gui_timeout_sec: int = 180
    action_log: list[dict[str, Any]] = field(default_factory=list)
    action_replay_path: Path | None = None
    screenshot_index: list[Any] = field(default_factory=list)
    device_serial: str | None = None


def _merge_ctx_metadata(sample: Sample, ctx: ExecutorContext) -> dict[str, Any]:
    metadata = dict(sample.metadata)
    if ctx.action_log:
        metadata["action_log"] = ctx.action_log
    if ctx.action_replay_path is not None:
        metadata["action_replay_available"] = True
    if ctx.device_serial:
        metadata["device_serial"] = ctx.device_serial
    if ctx.screenshot_index:
        metadata["screenshots"] = [
            item.to_metadata() if hasattr(item, "to_metadata") else item
            for item in ctx.screenshot_index
        ]
    return metadata


class Executor(ABC):
    """Base class. Subclasses implement `execute`. `run` is the supervised entry point."""

    @abstractmethod
    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        """Run sample and return list of response strings (one per prompt). Raise on failure."""

    async def run(
        self,
        sample: Sample,
        profile: Any,
        default_timeout_sec: int,
        ctx: ExecutorContext | None = None,
    ) -> SampleResult:
        ctx = ctx or ExecutorContext()
        timeout_sec = sample.timeout_sec or default_timeout_sec
        attempts = 0
        max_attempts = sample.retry + 1
        last_error: str | None = None
        status: str = "failed"
        responses: list[str] = []
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()

        if sample.dry_run:
            return SampleResult(
                id=sample.id,
                status="done",
                prompts_sent=list(sample.prompts),
                responses=[f"[DRY RUN] would send: {p}" for p in sample.prompts],
                duration_ms=int((time.monotonic() - t0) * 1000),
                attempt_count=1,
                mode=sample.mode,
                target_profile=sample.target_profile,
                metadata=_merge_ctx_metadata(sample, ctx),
                logs_dir=ctx.logs_dir,
                started_at=started,
                ended_at=datetime.now(timezone.utc),
            )

        while attempts < max_attempts:
            attempts += 1
            try:
                responses = await asyncio.wait_for(
                    self.execute(sample, profile, ctx), timeout=timeout_sec
                )
                status = "done"
                last_error = None
                break
            except asyncio.TimeoutError:
                last_error = f"timeout after {timeout_sec}s"
                status = "timeout"
            except Exception as e:  # noqa: BLE001
                last_error = f"{type(e).__name__}: {e}"
                status = "failed"

        return SampleResult(
            id=sample.id,
            status=status if status == "done" else ("timeout" if status == "timeout" else "failed"),
            prompts_sent=list(sample.prompts),
            responses=responses,
            duration_ms=int((time.monotonic() - t0) * 1000),
            attempt_count=attempts,
            mode=sample.mode,
            target_profile=sample.target_profile,
            metadata=_merge_ctx_metadata(sample, ctx),
            error=last_error,
            logs_dir=ctx.logs_dir,
            started_at=started,
            ended_at=datetime.now(timezone.utc),
        )
