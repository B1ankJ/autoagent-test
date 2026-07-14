from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uiautomator2 as u2

from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.agent_screenshot_extractor import extract_response_from_screenshot
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
# VLM copy-button: initial attempt + 2 retries, each restarting from a fresh
# screenshot. When configured, the VLM path is authoritative — failure means
# the run records an empty response, no fallback to ui_tree / ocr extraction.
_VLM_MAX_ATTEMPTS = 3
_VLM_RETRY_BACKOFF_SEC = 0.5
# Copy-button tap → clipboard check: a single fixed-delay read races apps
# whose copy action populates the clipboard slightly late (toast-triggered
# copies, Android 10+ clipboard-access latency, a loaded device) — that
# produced false "miss" verdicts which sent the caller on to tap a
# *different* coordinate while the correct tap's copy was still in flight,
# sometimes overwriting it. Poll instead: same total budget, but return as
# soon as the clipboard has something.
_CLIPBOARD_POLL_BUDGET_SEC = 1.0
_CLIPBOARD_POLL_INTERVAL_SEC = 0.12
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


async def _poll_clipboard(
    device: Any,
    *,
    budget_sec: float = _CLIPBOARD_POLL_BUDGET_SEC,
    interval_sec: float = _CLIPBOARD_POLL_INTERVAL_SEC,
) -> str:
    """Poll the device clipboard for up to budget_sec, returning as soon as
    it's non-empty (stripped). Returns "" if nothing showed up in time."""
    deadline = time.monotonic() + budget_sec
    while True:
        text = (await asyncio.to_thread(lambda: device.clipboard or "")).strip()
        if text:
            return text
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return ""
        await asyncio.sleep(min(interval_sec, remaining))


class _SampleLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str, *args: object) -> None:
        rendered = message % args if args else message
        log.info(rendered)
        self._write("INFO", rendered)

    def warning(self, message: str, *args: object) -> None:
        rendered = message % args if args else message
        log.warning(rendered)
        self._write("WARN", rendered)

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
                    before_input = await asyncio.to_thread(capture_screenshot_bytes, device)
                    before_input_path = await asyncio.to_thread(
                        store.write_screenshot, f"before_input_{idx}", before_input
                    )
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
                    after_input = await asyncio.to_thread(capture_screenshot_bytes, device)
                    screenshot_path = await asyncio.to_thread(
                        store.write_screenshot, f"after_input_{idx}", after_input
                    )
                    ctx.screenshot_index.append(
                        ScreenshotResult(path=screenshot_path, label=f"after_input_{idx}")
                    )
                    sample_log.info(
                        "android sample %s prompt %s captured after_input screenshot: file=%s",
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
                    after_send = await asyncio.to_thread(capture_screenshot_bytes, device)
                    after_send_path = await asyncio.to_thread(
                        store.write_screenshot, f"after_send_{idx}", after_send
                    )
                    ctx.screenshot_index.append(
                        ScreenshotResult(path=after_send_path, label=f"after_send_{idx}")
                    )
                    await asyncio.sleep(profile.post_send_wait_sec)
                    xml: str | None = None
                    if profile.complete_detection.type == "fixed_delay":
                        sample_log.info(
                            "android sample %s prompt %s wait fixed_delay sec=%.1f",
                            sample.id,
                            idx,
                            profile.complete_detection.wait_sec,
                        )
                        await asyncio.sleep(profile.complete_detection.wait_sec)
                    elif profile.complete_detection.type == "pixel_stable":
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
                        # returns on the first successful dump. Skip entirely
                        # when copy_button_vlm is configured — that path uses
                        # screenshots + clipboard and never reads the XML.
                        if not profile.response_extraction.copy_button_vlm:
                            xml = await wait_for_ui_tree_stable(
                                device,
                                stable_sec=0.0,
                                max_wait_sec=5.0,
                                prefer_u2=bool(profile.response_extraction.copy_button_text),
                            )

                    # VLM-based copy-button location: skip XML entirely and ask a
                    # vision LLM for the button coordinates. Used for WebView /
                    # browser pages where the UI tree is empty or meaningless.
                    # When configured, this is the only valid extraction path —
                    # if all attempts fail we record an empty response rather
                    # than falling back to ui_tree / ocr, which wouldn't work
                    # for this kind of page anyway.
                    if profile.response_extraction.copy_button_vlm:
                        vlm_cfg = profile.response_extraction.copy_button_vlm
                        # Clear clipboard so a previous prompt's text can't be
                        # mistaken for a successful copy. Cheapest possible
                        # check for "did the tap actually copy something new?"
                        try:
                            await asyncio.to_thread(
                                lambda: setattr(device, "clipboard", "")
                            )
                        except Exception:
                            pass
                        vlm_clipboard: str | None = None
                        vlm_last_error: str | None = None
                        # Optional fast path: try each cached coord before paying
                        # for a VLM call. Clipboard is cleared per candidate so
                        # a wrong tap that wrote a URL / share text into the
                        # clipboard can't masquerade as a hit on the next try.
                        if vlm_cfg.default_coords:
                            for cand_idx, (dx, dy) in enumerate(vlm_cfg.default_coords):
                                try:
                                    await asyncio.to_thread(
                                        lambda: setattr(device, "clipboard", "")
                                    )
                                except Exception:
                                    pass
                                await asyncio.to_thread(device.click, dx, dy)
                                cached_clipboard = await _poll_clipboard(device)
                                if cached_clipboard:
                                    vlm_clipboard = cached_clipboard
                                    sample_log.info(
                                        "android sample %s prompt %s vlm copy-button "
                                        "default_coords hit #%d/%d: coords=(%d,%d) chars=%d",
                                        sample.id,
                                        idx,
                                        cand_idx + 1,
                                        len(vlm_cfg.default_coords),
                                        dx,
                                        dy,
                                        len(vlm_clipboard),
                                    )
                                    break
                                sample_log.info(
                                    "android sample %s prompt %s vlm copy-button "
                                    "default_coords miss #%d/%d: coords=(%d,%d)",
                                    sample.id,
                                    idx,
                                    cand_idx + 1,
                                    len(vlm_cfg.default_coords),
                                    dx,
                                    dy,
                                )
                            if vlm_clipboard is None:
                                sample_log.info(
                                    "android sample %s prompt %s vlm copy-button "
                                    "all %d default_coords candidates missed, "
                                    "falling through to VLM",
                                    sample.id,
                                    idx,
                                    len(vlm_cfg.default_coords),
                                )
                        for vlm_attempt in range(_VLM_MAX_ATTEMPTS):
                            if vlm_clipboard is not None:
                                break
                            vlm_shot = await asyncio.to_thread(
                                capture_screenshot_bytes, device
                            )
                            vlm_res = await locate_copy_button_via_vlm(
                                vlm_shot, profile.response_extraction.copy_button_vlm
                            )
                            sample_log.info(
                                "android sample %s prompt %s vlm copy-button "
                                "attempt %d/%d: coords=%s dialog_coords=%s "
                                "latency_ms=%s error=%s",
                                sample.id,
                                idx,
                                vlm_attempt + 1,
                                _VLM_MAX_ATTEMPTS,
                                vlm_res.coords,
                                vlm_res.dialog_coords,
                                vlm_res.latency_ms,
                                vlm_res.error,
                            )
                            if vlm_res.dialog_coords is not None:
                                # A blocking consent/auth dialog, not a miss —
                                # dismiss it and retry on a fresh screenshot
                                # instead of burning this attempt on a screen
                                # the copy button was never going to be on.
                                sample_log.info(
                                    "android sample %s prompt %s vlm copy-button "
                                    "dismissing blocking dialog at %s, waiting %.1fs",
                                    sample.id,
                                    idx,
                                    vlm_res.dialog_coords,
                                    vlm_cfg.dialog_dismiss_wait_sec,
                                )
                                await asyncio.to_thread(
                                    device.click,
                                    vlm_res.dialog_coords[0],
                                    vlm_res.dialog_coords[1],
                                )
                                vlm_last_error = "blocking_dialog_dismissed"
                                if vlm_cfg.dialog_dismiss_wait_sec > 0:
                                    await asyncio.sleep(vlm_cfg.dialog_dismiss_wait_sec)
                                continue
                            if vlm_res.coords is None:
                                vlm_last_error = vlm_res.error or "no_coords"
                            else:
                                # Clear again per attempt — a previous tap on
                                # the wrong element (e.g. share) might have
                                # written a URL that would falsely pass the
                                # "non-empty clipboard" check below.
                                try:
                                    await asyncio.to_thread(
                                        lambda: setattr(device, "clipboard", "")
                                    )
                                except Exception:
                                    pass
                                await asyncio.to_thread(
                                    device.click,
                                    vlm_res.coords[0],
                                    vlm_res.coords[1],
                                )
                                clipboard_text = await _poll_clipboard(device)
                                if clipboard_text:
                                    vlm_clipboard = clipboard_text
                                    break
                                vlm_last_error = "empty_clipboard"
                            if vlm_attempt < _VLM_MAX_ATTEMPTS - 1:
                                await asyncio.sleep(_VLM_RETRY_BACKOFF_SEC)
                        # Always snapshot final state for diagnostics.
                        after_result = await asyncio.to_thread(
                            capture_screenshot_bytes, device
                        )
                        after_result_path = await asyncio.to_thread(
                            store.write_screenshot, f"after_result_{idx}", after_result
                        )
                        ctx.screenshot_index.append(
                            ScreenshotResult(
                                path=after_result_path,
                                label=f"after_result_{idx}",
                            )
                        )
                        if vlm_clipboard is not None:
                            sample_log.info(
                                "android sample %s prompt %s vlm clipboard "
                                "extraction: chars=%d",
                                sample.id,
                                idx,
                                len(vlm_clipboard),
                            )
                            responses.append(vlm_clipboard)
                            continue
                        if vlm_cfg.fallback_to_method:
                            if vlm_cfg.retry_wait_sec > 0:
                                sample_log.info(
                                    "android sample %s prompt %s vlm failed "
                                    "(last_error=%s), sleeping %.1fs before "
                                    "falling back to method=%s",
                                    sample.id,
                                    idx,
                                    vlm_last_error,
                                    vlm_cfg.retry_wait_sec,
                                    profile.response_extraction.method,
                                )
                                await asyncio.sleep(vlm_cfg.retry_wait_sec)
                            else:
                                sample_log.info(
                                    "android sample %s prompt %s vlm failed "
                                    "(last_error=%s), falling back to method=%s",
                                    sample.id,
                                    idx,
                                    vlm_last_error,
                                    profile.response_extraction.method,
                                )
                            # Fall through to method block. XML may still be
                            # None at this point — the ui_tree_only branch
                            # below handles that with a fresh dump.
                        else:
                            sample_log.warning(
                                "android sample %s prompt %s vlm copy-button "
                                "failed after %d attempts: last_error=%s; "
                                "recording empty response (fallback_to_method "
                                "disabled)",
                                sample.id,
                                idx,
                                _VLM_MAX_ATTEMPTS,
                                vlm_last_error,
                            )
                            responses.append("")
                            continue

                    # Direct VLM read of the screenshot — second choice when
                    # copy_button_vlm exists and fell through, OR primary when
                    # only response_vlm is configured. Asks the model to
                    # transcribe the latest reply directly from the image, no
                    # tap / clipboard / XML involved.
                    if profile.response_extraction.response_vlm:
                        rvlm_cfg = profile.response_extraction.response_vlm
                        rvlm_text: str | None = None
                        rvlm_last_error: str | None = None
                        for rvlm_attempt in range(rvlm_cfg.max_attempts):
                            rvlm_shot_bytes = await asyncio.to_thread(
                                capture_screenshot_bytes, device
                            )
                            rvlm_screenshot = Screenshot(
                                base64_data=base64.b64encode(rvlm_shot_bytes).decode("ascii"),
                                width=0,
                                height=0,
                            )
                            rvlm_res = await extract_response_from_screenshot(
                                screenshot=rvlm_screenshot,
                                response_hint=rvlm_cfg.response_hint,
                                base_url=rvlm_cfg.base_url,
                                model=rvlm_cfg.model,
                                api_key=rvlm_cfg.api_key,
                                timeout_sec=rvlm_cfg.timeout_sec,
                            )
                            sample_log.info(
                                "android sample %s prompt %s response_vlm "
                                "attempt %d/%d: chars=%d latency_ms=%s error=%s",
                                sample.id,
                                idx,
                                rvlm_attempt + 1,
                                rvlm_cfg.max_attempts,
                                len(rvlm_res.text),
                                rvlm_res.latency_ms,
                                rvlm_res.error,
                            )
                            if rvlm_res.error is None and rvlm_res.text.strip():
                                rvlm_text = rvlm_res.text
                                break
                            rvlm_last_error = rvlm_res.error or "empty_text"
                            if rvlm_attempt < rvlm_cfg.max_attempts - 1:
                                await asyncio.sleep(rvlm_cfg.retry_backoff_sec)
                        # Always snapshot final state for diagnostics — unless a
                        # prior branch already wrote after_result for this idx.
                        rvlm_result_path = store.artifact_path(
                            f"after_result_{idx}", "jpg"
                        )
                        if not rvlm_result_path.exists():
                            rvlm_final_shot = await asyncio.to_thread(
                                capture_screenshot_bytes, device
                            )
                            rvlm_result_path = await asyncio.to_thread(
                                store.write_screenshot, f"after_result_{idx}", rvlm_final_shot
                            )
                            ctx.screenshot_index.append(
                                ScreenshotResult(
                                    path=rvlm_result_path,
                                    label=f"after_result_{idx}",
                                )
                            )
                        if rvlm_text is not None:
                            sample_log.info(
                                "android sample %s prompt %s response_vlm "
                                "extraction: chars=%d",
                                sample.id,
                                idx,
                                len(rvlm_text),
                            )
                            responses.append(rvlm_text)
                            continue
                        if rvlm_cfg.fallback_to_method:
                            if rvlm_cfg.retry_wait_sec > 0:
                                sample_log.info(
                                    "android sample %s prompt %s response_vlm "
                                    "failed (last_error=%s), sleeping %.1fs "
                                    "before falling back to method=%s",
                                    sample.id,
                                    idx,
                                    rvlm_last_error,
                                    rvlm_cfg.retry_wait_sec,
                                    profile.response_extraction.method,
                                )
                                await asyncio.sleep(rvlm_cfg.retry_wait_sec)
                            else:
                                sample_log.info(
                                    "android sample %s prompt %s response_vlm "
                                    "failed (last_error=%s), falling back to "
                                    "method=%s",
                                    sample.id,
                                    idx,
                                    rvlm_last_error,
                                    profile.response_extraction.method,
                                )
                            # Fall through to copy_button_text / method.
                        else:
                            sample_log.warning(
                                "android sample %s prompt %s response_vlm failed "
                                "after %d attempts: last_error=%s; recording "
                                "empty response (fallback_to_method disabled)",
                                sample.id,
                                idx,
                                rvlm_cfg.max_attempts,
                                rvlm_last_error,
                            )
                            responses.append("")
                            continue

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
                                after_result = await asyncio.to_thread(
                                    capture_screenshot_bytes, device
                                )
                                after_result_path = await asyncio.to_thread(
                                    store.write_screenshot,
                                    f"after_result_{idx}",
                                    after_result,
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
                    after_result = await asyncio.to_thread(capture_screenshot_bytes, device)
                    after_result_path = await asyncio.to_thread(
                        store.write_screenshot, f"after_result_{idx}", after_result
                    )
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
            try:
                on_error = await asyncio.to_thread(capture_screenshot_bytes, device)
                await asyncio.to_thread(store.write_screenshot, "on_error", on_error)
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
