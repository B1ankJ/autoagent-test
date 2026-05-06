from __future__ import annotations

import asyncio
from typing import Any

from autoagent.executors.agent_core.agent_loop import AgentLoop
from autoagent.executors.agent_core.android_device import AndroidDevice
from autoagent.executors.agent_core.model_client import ModelClient, ModelConfig
from autoagent.executors.agent_core.prompts import ANDROID_SYSTEM_PROMPT
from autoagent.executors.agent_screenshot_extractor import extract_response_from_screenshot
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AgentAndroidProfile


class AgentAndroidExecutor(Executor):
    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, AgentAndroidProfile):
            raise TypeError(
                f"AgentAndroidExecutor requires AgentAndroidProfile, got {type(profile).__name__}"
            )

        serial = ctx.device_serial or profile.serial
        if not serial:
            raise ValueError("AgentAndroidExecutor requires ctx.device_serial or profile.serial")

        device = AndroidDevice(serial=serial)
        client = ModelClient(
            ModelConfig(
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
            )
        )
        agent_loop = AgentLoop(device, client, ANDROID_SYSTEM_PROMPT, profile.max_steps)
        loop = asyncio.get_running_loop()
        responses: list[str] = []

        for prompt in sample.prompts:
            template = (
                profile.new_session_task_template
                if sample.new_session and profile.new_session_task_template
                else profile.task_template
            )
            task = template.format(prompt=prompt)
            await loop.run_in_executor(None, agent_loop.run, task)
            screenshot = await loop.run_in_executor(None, device.capture)
            extraction = await extract_response_from_screenshot(
                screenshot=screenshot,
                response_hint=profile.response_hint,
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
            )
            responses.append(extraction.text)
            ctx.llm_responses.append(extraction.text)
            ctx.llm_errors.append(extraction.error)

        return responses
