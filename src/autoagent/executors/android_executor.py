from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import uiautomator2 as u2

from autoagent.executors.android_input import AndroidInput
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.complete_detector import wait_for_ui_tree_stable
from autoagent.executors.response_extractor import UiTreeExtractor
from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AndroidProfile


class AndroidExecutor(Executor):
    def __init__(self, screenshots_root: Path | None = None) -> None:
        self._root = Path(screenshots_root) if screenshots_root else Path("./data/logs")

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, AndroidProfile):
            raise TypeError(
                f"AndroidExecutor requires AndroidProfile, got {type(profile).__name__}"
            )
        if not ctx.device_serial:
            raise ValueError("AndroidExecutor requires ctx.device_serial")

        device = await asyncio.to_thread(u2.connect, ctx.device_serial)
        batch_id = ctx.logs_dir or "ad_hoc"
        store = ScreenshotStore(root=self._root, batch_id=batch_id, sample_id=sample.id)
        ctx.logs_dir = store.logs_dir

        extractor = UiTreeExtractor()
        responses: list[str] = []

        await asyncio.to_thread(device.app_start, profile.package, profile.activity, True)
        async with AndroidInput(device, profile.input_method) as input_ctl:
            for idx, prompt in enumerate(sample.prompts, start=1):
                await input_ctl.set_text(profile.input_locator, prompt)
                xml = await wait_for_ui_tree_stable(
                    device,
                    stable_sec=profile.complete_detection.stable_sec,
                    max_wait_sec=profile.complete_detection.max_wait_sec,
                )
                result = extractor.extract_from_xml(
                    xml,
                    bubble_class=profile.response_extraction.latest_bubble_match.value,
                )
                responses.append(result.text)
                ctx.screenshot_index.append(
                    ScreenshotResult(path=store.next_path(f"done_{idx}"), label=f"done_{idx}")
                )

        return responses
