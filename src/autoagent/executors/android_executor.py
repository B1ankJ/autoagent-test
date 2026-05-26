from __future__ import annotations

import asyncio
import json
import logging
import re
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
    ensure_screen_awake,
    wait_for_pixel_stable,
    wait_for_ui_tree_stable,
)
from autoagent.executors.copy_button_vlm import locate_copy_button_via_vlm
from autoagent.executors.response_extractor import (
    OcrExtractor,
    UiTreeExtractor,
    find_copy_button_center,
)
from autoagent.executors.response_llm_extractor import extract_response_via_llm
from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ActionStep, AndroidProfile

log = logging.getLogger(__name__)
_NEW_SESSION_STEP_DELAY_SEC = 2.0
_LOADING_RETRY_MAX = 5
_LOADING_RETRY_SEC = 3.0
_LOADING_INDICATOR_PATTERNS = (
    "正在思考",
    "思考中",
    "正在生成",
    "AI正在回复",
    "正在回答",
    "正在回复",
    "正在处理",
    "加载中",
    "Loading",
)


_TRAILING_ELLIPSIS_RE = re.compile(r"[.…·\u30fb ]+$")


def _is_loading_indicator(text: str) -> bool:
    stripped = _TRAILING_ELLIPSIS_RE.sub("", text.strip())
    if not stripped:
        return True
    return any(pattern in stripped for pattern in _LOADING_INDICATOR_PATTERNS)


def _xml_has_loading_indicator(xml: str) -> bool:
    """Return True if the raw XML contains any loading indicator pattern."""
    return any(pattern in xml for pattern in _LOADING_INDICATOR_PATTERNS)


def _clip_log_text(value: str | None, max_chars: int = 240) -> str | None:
    if value is None:
        return None
    compact = value.replace("\n", "\\n")
    if len(compact) <= max_chars:
        return compact
    return f"{compact[:max_chars]}..."


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
        if screenshots_root is None:
            from autoagent.config.settings import get_settings
            screenshots_root = get_settings().logs_root
        self._root = Path(screenshots_root)

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
            await asyncio.to_thread(ensure_screen_awake, ctx.device_serial)
            await asyncio.to_thread(device.app_start, profile.package, profile.activity, False)
            async with AndroidInput(device, profile.input_method) as input_ctl:
                action_runner = AndroidActionRunner(
                    device=device,
                    input_controller=input_ctl,
                    action_log=ctx.action_log,
                    replay_path=ctx.action_replay_path,
                )
                resolved_methods = [
                    await input_ctl.preview_method(prompt) for prompt in sample.prompts
                ]
                if "adb_keyboard" in resolved_methods:
                    await input_ctl.prepare_for_prompt(sample.prompts[0])
                if sample.new_session and profile.new_session_action:
                    sample_log.info("android sample %s running new_session_action", sample.id)
                    await _run_new_session_action_with_delay(
                        action_runner,
                        profile.new_session_action,
                    )
                    await asyncio.sleep(profile.new_session_wait_sec)
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
                    locator_desc = (
                        f"{profile.input_locator.type}:{profile.input_locator.value}"
                        if profile.input_locator is not None
                        else "<focused-field>"
                    )
                    sample_log.info(
                        "android sample %s prompt %s set_text start: method=%s locator=%s",
                        sample.id,
                        idx,
                        resolved_input,
                        locator_desc,
                    )
                    await input_ctl.set_text(profile.input_locator, prompt)
                    screenshot_path = store.artifact_path(f"after_input_{idx}", "png")
                    after_input = await asyncio.to_thread(capture_screenshot_bytes, device)
                    await asyncio.to_thread(screenshot_path.write_bytes, after_input)
                    ctx.screenshot_index.append(
                        ScreenshotResult(path=screenshot_path, label=f"after_input_{idx}")
                    )
                    sample_log.info(
                        "android sample %s prompt %s captured after_input screenshot: png=%s",
                        sample.id,
                        idx,
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
                        if profile.send_button_locator is None:
                            raise RuntimeError(
                                "profile must define either send_action or "
                                "send_button_locator"
                            )
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
                    await asyncio.sleep(profile.post_send_wait_sec)
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
                        # When the profile relies on a copy-button for the real
                        # response text, the XML only needs to locate the button.
                        # u2's dump is fast and never blocks on the UiAutomation
                        # slot — truncation in the chat history doesn't matter.
                        xml = await wait_for_ui_tree_stable(
                            device,
                            stable_sec=profile.complete_detection.stable_sec,
                            max_wait_sec=profile.complete_detection.max_wait_sec,
                            prefer_u2=bool(profile.response_extraction.copy_button_text),
                        )

                    # Optional pre-extract actions, e.g. tap a "scroll to bottom"
                    # arrow that some chat UIs show only after the reply lands.
                    # Behaviour is unchanged when the list is empty.
                    if profile.pre_extract_action:
                        sample_log.info(
                            "android sample %s prompt %s pre_extract_action: steps=%s",
                            sample.id,
                            idx,
                            len(profile.pre_extract_action),
                        )
                        await action_runner.run(profile.pre_extract_action)
                        # UI just shifted; grab a fresh XML so the extraction
                        # below sees the post-action visible state. stable_sec=0
                        # returns on the first successful dump.
                        xml = await wait_for_ui_tree_stable(
                            device,
                            stable_sec=0.0,
                            max_wait_sec=5.0,
                            prefer_u2=bool(profile.response_extraction.copy_button_text),
                        )

                    # VLM-based copy-button location: skip XML entirely and ask a
                    # vision LLM for the button coordinates. Used for WebView /
                    # browser pages where the UI tree is empty or meaningless.
                    if profile.response_extraction.copy_button_vlm:
                        vlm_shot = await asyncio.to_thread(
                            capture_screenshot_bytes, device
                        )
                        vlm_res = await locate_copy_button_via_vlm(
                            vlm_shot, profile.response_extraction.copy_button_vlm
                        )
                        sample_log.info(
                            "android sample %s prompt %s vlm copy-button locate: "
                            "coords=%s latency_ms=%s error=%s",
                            sample.id,
                            idx,
                            vlm_res.coords,
                            vlm_res.latency_ms,
                            vlm_res.error,
                        )
                        if vlm_res.coords is not None:
                            await asyncio.to_thread(
                                device.click, vlm_res.coords[0], vlm_res.coords[1]
                            )
                            await asyncio.sleep(0.5)
                            clipboard_text = await asyncio.to_thread(
                                lambda: device.clipboard or ""
                            )
                            if clipboard_text.strip():
                                sample_log.info(
                                    "android sample %s prompt %s vlm clipboard "
                                    "extraction: chars=%d",
                                    sample.id,
                                    idx,
                                    len(clipboard_text),
                                )
                                responses.append(clipboard_text.strip())
                                after_result_path = store.artifact_path(
                                    f"after_result_{idx}", "png"
                                )
                                after_result = await asyncio.to_thread(
                                    capture_screenshot_bytes, device
                                )
                                await asyncio.to_thread(
                                    after_result_path.write_bytes, after_result
                                )
                                ctx.screenshot_index.append(
                                    ScreenshotResult(
                                        path=after_result_path,
                                        label=f"after_result_{idx}",
                                    )
                                )
                                continue
                            sample_log.info(
                                "android sample %s prompt %s vlm tapped but "
                                "clipboard empty, falling back to method=%s",
                                sample.id,
                                idx,
                                profile.response_extraction.method,
                            )

                    # Copy-button clipboard extraction: if the profile specifies a
                    # copy_button_text, find it in the current XML at runtime and tap
                    # it; the full response text lands in the clipboard and is more
                    # complete than UI-tree or OCR extraction for scrolled WebViews.
                    if profile.response_extraction.copy_button_text and xml:
                        center = find_copy_button_center(
                            xml, profile.response_extraction.copy_button_text
                        )
                        if center is not None:
                            await asyncio.to_thread(device.click, center[0], center[1])
                            await asyncio.sleep(0.5)
                            clipboard_text = await asyncio.to_thread(
                                lambda: device.clipboard or ""
                            )
                            if clipboard_text.strip():
                                sample_log.info(
                                    "android sample %s prompt %s clipboard extraction: "
                                    "button=%r center=%s chars=%d",
                                    sample.id,
                                    idx,
                                    profile.response_extraction.copy_button_text,
                                    center,
                                    len(clipboard_text),
                                )
                                responses.append(clipboard_text.strip())
                                after_result_xml_path = store.artifact_path(
                                    f"after_result_{idx}", "xml"
                                )
                                if xml is not None:
                                    await asyncio.to_thread(
                                        after_result_xml_path.write_text, xml, "utf-8"
                                    )
                                after_result_path = store.artifact_path(
                                    f"after_result_{idx}", "png"
                                )
                                after_result = await asyncio.to_thread(
                                    capture_screenshot_bytes, device
                                )
                                await asyncio.to_thread(
                                    after_result_path.write_bytes, after_result
                                )
                                ctx.screenshot_index.append(
                                    ScreenshotResult(
                                        path=after_result_path,
                                        label=f"after_result_{idx}",
                                    )
                                )
                                continue
                            sample_log.info(
                                "android sample %s prompt %s clipboard empty after "
                                "copy button tap, falling back to method=%s",
                                sample.id,
                                idx,
                                profile.response_extraction.method,
                            )
                        else:
                            sample_log.info(
                                "android sample %s prompt %s copy button %r not found "
                                "in xml, falling back to method=%s",
                                sample.id,
                                idx,
                                profile.response_extraction.copy_button_text,
                                profile.response_extraction.method,
                            )

                    if profile.response_extraction.method == "ui_tree_only":
                        if xml is None:
                            xml = await wait_for_ui_tree_stable(
                                device,
                                stable_sec=0.0,
                                max_wait_sec=profile.complete_detection.max_wait_sec,
                            )
                        for _retry in range(_LOADING_RETRY_MAX):
                            if not _xml_has_loading_indicator(xml):
                                break
                            sample_log.info(
                                "android sample %s prompt %s xml loading indicator, "
                                "retry %s/%s",
                                sample.id,
                                idx,
                                _retry + 1,
                                _LOADING_RETRY_MAX,
                            )
                            await asyncio.sleep(_LOADING_RETRY_SEC)
                            xml = await wait_for_ui_tree_stable(
                                device,
                                stable_sec=1.0,
                                max_wait_sec=profile.complete_detection.max_wait_sec,
                            )
                        result = ui_tree_extractor.extract_from_xml(
                            xml,
                            response_container_locator=profile.response_extraction.response_container_locator,
                            latest_bubble_locator=profile.response_extraction.latest_bubble_match,
                        )
                        if _is_loading_indicator(result.text):
                            sample_log.info(
                                "android sample %s prompt %s result is loading indicator: %r",
                                sample.id,
                                idx,
                                result.text,
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
                        for _retry in range(_LOADING_RETRY_MAX):
                            if not _xml_has_loading_indicator(xml):
                                break
                            sample_log.info(
                                "android sample %s prompt %s xml loading indicator, "
                                "retry %s/%s",
                                sample.id,
                                idx,
                                _retry + 1,
                                _LOADING_RETRY_MAX,
                            )
                            await asyncio.sleep(_LOADING_RETRY_SEC)
                            xml = await wait_for_ui_tree_stable(
                                device,
                                stable_sec=1.0,
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
                        if result.text.strip() and not _is_loading_indicator(result.text):
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
                        llm_debug_path = store.artifact_path(f"llm_extract_{idx}", "json")
                        llm_debug_payload = {
                            "prompt": prompt,
                            "xml_artifact": after_result_xml_path.name if xml is not None else None,
                            "xml_sent": llm_res.xml_sent,
                            "status_code": llm_res.status_code,
                            "latency_ms": llm_res.latency_ms,
                            "error": llm_res.error,
                            "text": llm_res.text,
                            "truncated_input": llm_res.truncated_input,
                            "raw_message_content": llm_res.raw_message_content,
                            "raw_response_text": llm_res.raw_response_text,
                        }
                        await asyncio.to_thread(
                            llm_debug_path.write_text,
                            json.dumps(llm_debug_payload, ensure_ascii=False, indent=2),
                            "utf-8",
                        )
                        sample_log.info(
                            (
                                "android sample %s prompt %s llm extraction: "
                                "status=%s error=%s latency_ms=%s text=%r raw=%s"
                            ),
                            sample.id,
                            idx,
                            llm_res.status_code,
                            llm_res.error,
                            llm_res.latency_ms,
                            llm_res.text,
                            _clip_log_text(llm_res.raw_message_content),
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


async def _run_new_session_action_with_delay(
    action_runner: AndroidActionRunner,
    steps: list[ActionStep],
) -> None:
    for step in steps:
        await action_runner.run([step])
        await asyncio.sleep(_NEW_SESSION_STEP_DELAY_SEC)
