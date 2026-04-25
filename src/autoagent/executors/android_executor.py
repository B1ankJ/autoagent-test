from __future__ import annotations

import asyncio
import logging
import time
import traceback
from datetime import datetime, timezone
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
from autoagent.executors.response_llm_extractor import extract_response_via_llm
from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ActionStep, AndroidProfile

log = logging.getLogger(__name__)


class _SampleLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str, *args: object) -> None:
        rendered = message % args if args else message
        log.info(rendered)
        self._write("INFO", rendered)

    def exception(self, message: str, *args: object) -> None:
        rendered = message % args if args else message
        log.exception(rendered)
        self._write("ERROR", rendered)
        self._write("ERROR", traceback.format_exc().rstrip())

    def _write(self, level: str, message: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {level} {message}\n")


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
        if ctx.logs_dir and Path(ctx.logs_dir).is_absolute():
            store = ScreenshotStore.from_logs_dir(Path(ctx.logs_dir))
        else:
            batch_id = ctx.logs_dir or "ad_hoc"
            store = ScreenshotStore(root=self._root, batch_id=batch_id, sample_id=sample.id)
        ctx.logs_dir = store.logs_dir
        sample_log = _SampleLogger(Path(store.logs_dir) / "executor.log")

        ui_tree_extractor = UiTreeExtractor()
        ocr_extractor = OcrExtractor()
        responses: list[str] = []

        try:
            sample_log.info(
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
                    sample_log.info(
                        "android sample %s ready_check failed, running recovery_path", sample.id
                    )
                    await action_runner.run(profile.recovery_path)
                    ready = await _wait_for_ready_text(
                        device,
                        profile.ready_check.text,
                        timeout_sec=profile.ready_check.timeout_sec,
                    )
                if not ready:
                    raise TimeoutError(f"ready_check text not found: {profile.ready_check.text!r}")
                resolved_methods = [
                    await input_ctl.preview_method(prompt) for prompt in sample.prompts
                ]
                if "adb_keyboard" in resolved_methods:
                    await input_ctl.prepare_for_prompt(sample.prompts[0])
                if profile.new_session_action:
                    sample_log.info("android sample %s running new_session_action", sample.id)
                    await action_runner.run(profile.new_session_action)
                for idx, prompt in enumerate(sample.prompts, start=1):
                    resolved_input = resolved_methods[idx - 1]
                    if profile.input_focus_action:
                        sample_log.info(
                            "android sample %s prompt %s running input_focus_action",
                            sample.id,
                            idx,
                        )
                        await action_runner.run(profile.input_focus_action)
                    before_input_path = store.artifact_path(f"before_input_{idx}", "png")
                    before_input = await asyncio.to_thread(capture_screenshot_bytes, device)
                    await asyncio.to_thread(before_input_path.write_bytes, before_input)
                    ctx.screenshot_index.append(
                        ScreenshotResult(path=before_input_path, label=f"before_input_{idx}")
                    )
                    sample_log.info(
                        "android sample %s prompt %s set_text start: method=%s locator=%s:%s",
                        sample.id,
                        idx,
                        resolved_input,
                        profile.input_locator.type,
                        profile.input_locator.value,
                    )
                    await input_ctl.set_text(profile.input_locator, prompt)
                    xml_path = store.artifact_path(f"after_input_{idx}", "xml")
                    screenshot_path = store.artifact_path(f"after_input_{idx}", "png")
                    current_xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
                    await asyncio.to_thread(xml_path.write_text, current_xml, "utf-8")
                    after_input = await asyncio.to_thread(capture_screenshot_bytes, device)
                    await asyncio.to_thread(screenshot_path.write_bytes, after_input)
                    ctx.screenshot_index.append(
                        ScreenshotResult(path=screenshot_path, label=f"after_input_{idx}")
                    )
                    sample_log.info(
                        "android sample %s prompt %s captured after_input artifacts: xml=%s png=%s",
                        sample.id,
                        idx,
                        xml_path.name,
                        screenshot_path.name,
                    )
                    if profile.send_action:
                        sample_log.info(
                            "android sample %s prompt %s send action: steps=%s",
                            sample.id,
                            idx,
                            len(profile.send_action),
                        )
                        await action_runner.run(profile.send_action)
                    else:
                        sample_log.info(
                            "android sample %s prompt %s send click: locator=%s:%s",
                            sample.id,
                            idx,
                            profile.send_button_locator.type,
                            profile.send_button_locator.value,
                        )
                        await action_runner.run(
                            [
                                ActionStep(
                                    action="click_locator",
                                    locator=profile.send_button_locator,
                                )
                            ]
                        )
                    after_send_path = store.artifact_path(f"after_send_{idx}", "png")
                    after_send = await asyncio.to_thread(capture_screenshot_bytes, device)
                    await asyncio.to_thread(after_send_path.write_bytes, after_send)
                    ctx.screenshot_index.append(
                        ScreenshotResult(path=after_send_path, label=f"after_send_{idx}")
                    )
                    xml: str | None = None
                    if profile.complete_detection.type == "pixel_stable":
                        sample_log.info(
                            "android sample %s prompt %s wait pixel_stable", sample.id, idx
                        )
                        await wait_for_pixel_stable(
                            device,
                            stable_sec=profile.complete_detection.stable_sec,
                            max_wait_sec=profile.complete_detection.max_wait_sec,
                        )
                    else:
                        sample_log.info(
                            "android sample %s prompt %s wait ui_tree_stable", sample.id, idx
                        )
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
                            response_container_locator=profile.response_extraction.response_container_locator,
                            latest_bubble_locator=profile.response_extraction.latest_bubble_match,
                        )
                        sample_log.info(
                            (
                                "android sample %s prompt %s ui_tree extraction: "
                                "container_found=%s matched=%s response_container=%s "
                                "latest_bubble=%s"
                            ),
                            sample.id,
                            idx,
                            result.container_found,
                            result.matched_locator_count,
                            profile.response_extraction.response_container_locator.model_dump(mode="json"),
                            profile.response_extraction.latest_bubble_match.model_dump(mode="json"),
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
                            response_container_locator=profile.response_extraction.response_container_locator,
                            latest_bubble_locator=profile.response_extraction.latest_bubble_match,
                        )
                        sample_log.info(
                            (
                                "android sample %s prompt %s ui_tree extraction: "
                                "container_found=%s matched=%s response_container=%s "
                                "latest_bubble=%s"
                            ),
                            sample.id,
                            idx,
                            result.container_found,
                            result.matched_locator_count,
                            profile.response_extraction.response_container_locator.model_dump(mode="json"),
                            profile.response_extraction.latest_bubble_match.model_dump(mode="json"),
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
                    after_result_xml_path = store.artifact_path(f"after_result_{idx}", "xml")
                    if xml is not None:
                        await asyncio.to_thread(after_result_xml_path.write_text, xml, "utf-8")
                    after_result_path = store.artifact_path(f"after_result_{idx}", "png")
                    after_result = await asyncio.to_thread(capture_screenshot_bytes, device)
                    await asyncio.to_thread(after_result_path.write_bytes, after_result)
                    sample_log.info(
                        "android sample %s prompt %s extraction done: method=%s text=%r",
                        sample.id,
                        idx,
                        profile.response_extraction.method,
                        responses[-1],
                    )
                    ctx.screenshot_index.append(
                        ScreenshotResult(path=after_result_path, label=f"after_result_{idx}")
                    )
                    if profile.llm_response_enabled():
                        llm_res = await extract_response_via_llm(
                            prompt=prompt,
                            xml=xml or "",
                            base_url=profile.base_url,
                            model=profile.model,
                            api_key=profile.api_key,
                        )
                        ctx.llm_responses.append(llm_res.text)
                        ctx.llm_errors.append(llm_res.error)
        except Exception:
            error_path = store.artifact_path("on_error", "png")
            try:
                on_error = await asyncio.to_thread(capture_screenshot_bytes, device)
                await asyncio.to_thread(error_path.write_bytes, on_error)
            except Exception:
                pass
            sample_log.exception("android sample %s failed", sample.id)
            raise

        return responses


async def _wait_for_ready_text(device: Any, text: str, *, timeout_sec: float) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
        if text in xml:
            return True
        await asyncio.sleep(0.2)
    return False
