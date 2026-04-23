from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import uiautomator2 as u2

from autoagent.executors.android_action_runner import AndroidActionRunner
from autoagent.executors.android_input import AndroidInput
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.complete_detector import (
    capture_screenshot_bytes,
    wait_for_pixel_stable,
    wait_for_ui_tree_stable,
)
from autoagent.executors.response_extractor import OcrExtractor, UiTreeExtractor
from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ActionStep, AndroidProfile

log = logging.getLogger(__name__)


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

        ui_tree_extractor = UiTreeExtractor()
        ocr_extractor = OcrExtractor()
        responses: list[str] = []

        log.info(
            "android sample %s start: device=%s package=%s activity=%s",
            sample.id,
            ctx.device_serial,
            profile.package,
            profile.activity,
        )
        await asyncio.to_thread(device.app_start, profile.package, profile.activity, True)
        async with AndroidInput(device, profile.input_method) as input_ctl:
            action_runner = AndroidActionRunner(
                device=device,
                input_controller=input_ctl,
                action_log=ctx.action_log,
                replay_path=ctx.action_replay_path,
            )
            ready = await _wait_for_ready_text(
                device,
                profile.ready_check.text,
                timeout_sec=profile.ready_check.timeout_sec,
            )
            if not ready and profile.recovery_path:
                log.info("android sample %s ready_check failed, running recovery_path", sample.id)
                await action_runner.run(profile.recovery_path)
                ready = await _wait_for_ready_text(
                    device,
                    profile.ready_check.text,
                    timeout_sec=profile.ready_check.timeout_sec,
                )
            if not ready:
                raise TimeoutError(
                    f"ready_check text not found: {profile.ready_check.text!r}"
                )
            if profile.new_session_action:
                log.info("android sample %s running new_session_action", sample.id)
                await action_runner.run(profile.new_session_action)
            for idx, prompt in enumerate(sample.prompts, start=1):
                log.info("android sample %s prompt %s set_text start", sample.id, idx)
                await input_ctl.set_text(profile.input_locator, prompt)
                log.info("android sample %s prompt %s send click", sample.id, idx)
                await action_runner.run(
                    [ActionStep(action="click_locator", locator=profile.send_button_locator)]
                )
                xml: str | None = None
                if profile.complete_detection.type == "pixel_stable":
                    log.info("android sample %s prompt %s wait pixel_stable", sample.id, idx)
                    await wait_for_pixel_stable(
                        device,
                        stable_sec=profile.complete_detection.stable_sec,
                        max_wait_sec=profile.complete_detection.max_wait_sec,
                    )
                else:
                    log.info("android sample %s prompt %s wait ui_tree_stable", sample.id, idx)
                    xml = await wait_for_ui_tree_stable(
                        device,
                        stable_sec=profile.complete_detection.stable_sec,
                        max_wait_sec=profile.complete_detection.max_wait_sec,
                    )

                if profile.response_extraction.method == "ui_tree_only":
                    if xml is None:
                        xml = await wait_for_ui_tree_stable(
                            device,
                            stable_sec=0.0,
                            max_wait_sec=profile.complete_detection.max_wait_sec,
                        )
                    result = ui_tree_extractor.extract_from_xml(
                        xml,
                        bubble_class=profile.response_extraction.latest_bubble_match.value,
                    )
                    responses.append(result.text)
                elif profile.response_extraction.method == "ocr_only":
                    raw = await asyncio.to_thread(capture_screenshot_bytes, device)
                    result = await ocr_extractor.extract([raw])
                    responses.append(result.text)
                elif profile.response_extraction.method == "ui_tree_then_ocr":
                    if xml is None:
                        xml = await wait_for_ui_tree_stable(
                            device,
                            stable_sec=0.0,
                            max_wait_sec=profile.complete_detection.max_wait_sec,
                        )
                    result = ui_tree_extractor.extract_from_xml(
                        xml,
                        bubble_class=profile.response_extraction.latest_bubble_match.value,
                    )
                    if result.text.strip():
                        responses.append(result.text)
                    else:
                        raw = await asyncio.to_thread(capture_screenshot_bytes, device)
                        ocr_result = await ocr_extractor.extract([raw])
                        responses.append(ocr_result.text)
                else:
                    raise NotImplementedError(
                        "unsupported response extraction method: "
                        f"{profile.response_extraction.method}"
                    )
                ctx.screenshot_index.append(
                    ScreenshotResult(path=store.next_path(f"done_{idx}"), label=f"done_{idx}")
                )

        return responses


async def _wait_for_ready_text(device: Any, text: str, *, timeout_sec: float) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
        if text in xml:
            return True
        await asyncio.sleep(0.2)
    return False
