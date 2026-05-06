from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from autoagent.executors.agent_core.agent_loop import AgentLoop
from autoagent.executors.agent_core.android_device import AndroidDevice
from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.agent_core.handlers.android import AndroidActionHandler
from autoagent.executors.agent_core.model_client import ModelClient, ModelConfig
from autoagent.executors.agent_core.prompts import ANDROID_SYSTEM_PROMPT
from autoagent.executors.agent_screenshot_extractor import extract_response_from_screenshot
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AgentAndroidProfile


class AgentAndroidExecutor(Executor):
    def __init__(self, screenshots_root: Path | None = None) -> None:
        self._root = Path(screenshots_root) if screenshots_root else Path("./logs")

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, AgentAndroidProfile):
            raise TypeError(
                f"AgentAndroidExecutor requires AgentAndroidProfile, got {type(profile).__name__}"
            )

        serial = ctx.device_serial or profile.serial
        if not serial:
            raise ValueError("AgentAndroidExecutor requires ctx.device_serial or profile.serial")

        batch_id = ctx.logs_dir or "ad_hoc"
        if ctx.logs_dir and Path(ctx.logs_dir).is_absolute():
            store = ScreenshotStore.from_logs_dir(Path(ctx.logs_dir))
        else:
            store = ScreenshotStore(root=self._root, batch_id=batch_id, sample_id=sample.id)
        ctx.logs_dir = store.logs_dir
        device = AndroidDevice(serial=serial)
        client = ModelClient(
            ModelConfig(
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
            )
        )
        handler = AndroidActionHandler(device=device)
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

        agent_loop = AgentLoop(
            device,
            client,
            handler,
            ANDROID_SYSTEM_PROMPT,
            profile.max_steps,
            response_hint=profile.response_hint,
            response_observer=response_observer,
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
            extraction = await extract_response_from_screenshot(
                screenshot=screenshot,
                response_hint=profile.response_hint,
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
            )
            extract_path = store.artifact_path(f"extract_{len(responses) + 1}", "json")
            extract_payload = {
                "prompt": prompt,
                "response_hint": profile.response_hint,
                "text": extraction.text,
                "error": extraction.error,
                "latency_ms": extraction.latency_ms,
                "status_code": extraction.status_code,
                "raw_response_text": extraction.raw_response_text,
                "raw_message_content": extraction.raw_message_content,
            }
            extract_path.write_text(
                json.dumps(extract_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            responses.append(extraction.text)
            ctx.llm_responses.append(extraction.text)
            ctx.llm_errors.append(extraction.error)

        return responses
