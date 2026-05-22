from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoagent.executors.agent_core.agent_loop import AgentLoop, AgentResult
from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.agent_core.handlers.pc import PcActionHandler
from autoagent.executors.agent_core.model_client import ModelClient, ModelConfig
from autoagent.executors.agent_core.pc_device import PcDevice
from autoagent.executors.agent_core.prompts import PC_SYSTEM_PROMPT
from autoagent.executors.agent_screenshot_extractor import (
    extract_response_from_screenshot,
    verify_text_entry_in_screenshot,
)
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AgentPcProfile, CopyExtraction


@dataclass
class _CopyExtractionResult:
    loop_result: AgentResult
    clipboard_text: str


def _run_copy_extraction(
    device: PcDevice,
    client: ModelClient,
    handler: PcActionHandler,
    config: CopyExtraction,
) -> _CopyExtractionResult:
    """Run a short agent loop to click the copy button and read the clipboard.

    Executes synchronously; the caller wraps it in run_in_executor.
    """
    device.clear_clipboard()
    sub_loop = AgentLoop(
        device,
        client,
        handler,
        PC_SYSTEM_PROMPT,
        config.max_steps,
    )
    loop_result = sub_loop.run(config.task)
    if config.wait_ms > 0:
        time.sleep(config.wait_ms / 1000.0)
    text = device.read_clipboard()
    return _CopyExtractionResult(loop_result=loop_result, clipboard_text=text)


class AgentPcExecutor(Executor):
    def __init__(self, screenshots_root: Path | None = None) -> None:
        if screenshots_root is None:
            from autoagent.config.settings import get_settings
            screenshots_root = get_settings().logs_root
        self._root = Path(screenshots_root)

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, AgentPcProfile):
            raise TypeError(
                f"AgentPcExecutor requires AgentPcProfile, got {type(profile).__name__}"
            )

        batch_id = ctx.logs_dir or "ad_hoc"
        if ctx.logs_dir and Path(ctx.logs_dir).is_absolute():
            store = ScreenshotStore.from_logs_dir(Path(ctx.logs_dir))
        else:
            store = ScreenshotStore(root=self._root, batch_id=batch_id, sample_id=sample.id)
        ctx.logs_dir = store.logs_dir
        device = PcDevice()
        client = ModelClient(
            ModelConfig(
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
            )
        )
        handler = PcActionHandler(device=device)
        loop = asyncio.get_running_loop()
        responses: list[str] = []

        def response_observer(
            task: str,
            response_hint: str,
            screenshot: Screenshot,
        ) -> tuple[bool, str]:
            extraction = asyncio.run(
                extract_response_from_screenshot(
                    screenshot=screenshot,
                    response_hint=response_hint,
                    base_url=profile.base_url,
                    model=profile.model,
                    api_key=profile.api_key,
                )
            )
            return bool(extraction.text.strip()), extraction.text

        def action_observer(
            task: str,
            action: dict[str, Any],
            screenshot: Screenshot,
        ) -> tuple[bool, str] | None:
            if str(action.get("action", "")).strip().lower() != "type":
                return None
            verification = asyncio.run(
                verify_text_entry_in_screenshot(
                    screenshot=screenshot,
                    expected_text=str(action.get("text", "")),
                    base_url=profile.base_url,
                    model=profile.model,
                    api_key=profile.api_key,
                )
            )
            return verification.matched, verification.message

        agent_loop = AgentLoop(
            device,
            client,
            handler,
            PC_SYSTEM_PROMPT,
            profile.max_steps,
            response_hint=profile.response_hint,
            response_observer=response_observer,
            action_observer=action_observer,
        )

        for prompt in sample.prompts:
            template = (
                profile.new_session_task_template
                if sample.new_session and profile.new_session_task_template
                else profile.task_template
            )
            task = template.format(prompt=prompt)
            loop_result = await loop.run_in_executor(None, agent_loop.run, task)
            ctx.action_log.extend(step.to_metadata() for step in loop_result.steps)
            trace_path = store.artifact_path(f"loop_trace_{len(responses) + 1}", "json")
            trace_payload = {
                "task": task,
                "finished": loop_result.finished,
                "finish_message": loop_result.finish_message,
                "step_count": loop_result.step_count,
                "stop_reason": loop_result.stop_reason,
                "conversation": loop_result.conversation,
                "steps": [step.to_metadata() for step in loop_result.steps],
            }
            trace_path.write_text(
                json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for step in loop_result.steps:
                step_path = store.artifact_path(
                    f"step_{len(responses) + 1}_{step.step}",
                    "png",
                )
                step_path.write_bytes(base64.b64decode(step.screenshot.base64_data))
                ctx.screenshot_index.append(
                    ScreenshotResult(
                        path=step_path,
                        label=f"step_{len(responses) + 1}_{step.step}",
                    )
                )
            screenshot = await loop.run_in_executor(None, device.capture)
            final_path = store.artifact_path(f"final_{len(responses) + 1}", "png")
            final_path.write_bytes(base64.b64decode(screenshot.base64_data))
            ctx.screenshot_index.append(
                ScreenshotResult(path=final_path, label=f"final_{len(responses) + 1}")
            )

            response_text: str
            response_error: str | None
            extraction_method: str
            extraction_meta: dict[str, Any] = {}

            copy_cfg = profile.copy_extraction
            if copy_cfg and copy_cfg.enabled:
                clip_result = await loop.run_in_executor(
                    None,
                    _run_copy_extraction,
                    device,
                    client,
                    handler,
                    copy_cfg,
                )
                copy_trace_path = store.artifact_path(
                    f"copy_{len(responses) + 1}", "json"
                )
                copy_trace_path.write_text(
                    json.dumps(
                        {
                            "task": copy_cfg.task,
                            "clipboard_text": clip_result.clipboard_text,
                            "finished": clip_result.loop_result.finished,
                            "stop_reason": clip_result.loop_result.stop_reason,
                            "step_count": clip_result.loop_result.step_count,
                            "steps": [
                                step.to_metadata() for step in clip_result.loop_result.steps
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                ctx.action_log.extend(
                    step.to_metadata() for step in clip_result.loop_result.steps
                )
                for step in clip_result.loop_result.steps:
                    step_path = store.artifact_path(
                        f"copy_step_{len(responses) + 1}_{step.step}",
                        "png",
                    )
                    step_path.write_bytes(base64.b64decode(step.screenshot.base64_data))
                    ctx.screenshot_index.append(
                        ScreenshotResult(
                            path=step_path,
                            label=f"copy_step_{len(responses) + 1}_{step.step}",
                        )
                    )

                if clip_result.clipboard_text.strip():
                    response_text = clip_result.clipboard_text
                    response_error = None
                    extraction_method = "clipboard"
                elif copy_cfg.fallback_to_vlm:
                    extraction = await extract_response_from_screenshot(
                        screenshot=screenshot,
                        response_hint=profile.response_hint,
                        base_url=profile.base_url,
                        model=profile.model,
                        api_key=profile.api_key,
                    )
                    response_text = extraction.text
                    response_error = extraction.error
                    extraction_method = "vlm_fallback"
                    extraction_meta = {
                        "latency_ms": extraction.latency_ms,
                        "status_code": extraction.status_code,
                        "raw_response_text": extraction.raw_response_text,
                        "raw_message_content": extraction.raw_message_content,
                    }
                else:
                    response_text = ""
                    response_error = "clipboard_empty"
                    extraction_method = "clipboard_empty"
            else:
                extraction = await extract_response_from_screenshot(
                    screenshot=screenshot,
                    response_hint=profile.response_hint,
                    base_url=profile.base_url,
                    model=profile.model,
                    api_key=profile.api_key,
                )
                response_text = extraction.text
                response_error = extraction.error
                extraction_method = "vlm"
                extraction_meta = {
                    "latency_ms": extraction.latency_ms,
                    "status_code": extraction.status_code,
                    "raw_response_text": extraction.raw_response_text,
                    "raw_message_content": extraction.raw_message_content,
                }

            extract_path = store.artifact_path(f"extract_{len(responses) + 1}", "json")
            extract_payload = {
                "prompt": prompt,
                "response_hint": profile.response_hint,
                "method": extraction_method,
                "text": response_text,
                "error": response_error,
                **extraction_meta,
            }
            extract_path.write_text(
                json.dumps(extract_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            responses.append(response_text)
            ctx.llm_responses.append(response_text)
            ctx.llm_errors.append(response_error)

        return responses
