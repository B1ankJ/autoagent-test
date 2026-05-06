from __future__ import annotations

import logging
from typing import Any

from autoagent.executors.agent_core.device import Device, Screenshot
from autoagent.executors.agent_core.model_client import ModelClient
from autoagent.executors.agent_core.parser import parse_action
from autoagent.executors.agent_core.result import AgentRunResult, AgentStepRecord

_log = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(
        self,
        device: Device,
        client: ModelClient,
        handler: Any,
        system_prompt: str,
        max_steps: int,
    ) -> None:
        self._device = device
        self._client = client
        self._handler = handler
        self._system_prompt = system_prompt
        self._max_steps = max_steps

    def run(self, task: str) -> AgentRunResult:
        context: list[dict[str, Any]] = []
        steps: list[AgentStepRecord] = []

        for step in range(1, self._max_steps + 1):
            screenshot = self._device.capture()
            messages = self._build_messages(task, screenshot, context, step)
            raw = self._client.call(messages)
            _log.debug("agent_runtime step=%d raw=%r", step, raw[:200])
            action = parse_action(raw)

            if action.get("_metadata") == "finish":
                record = AgentStepRecord(step=step, raw=raw, action=action, screenshot=screenshot)
                steps.append(record)
                return AgentRunResult(True, str(action.get("message", "")), step, "finish", steps)

            execution = None
            if action.get("_metadata") == "do":
                execution = self._handler.execute(action, screenshot.width, screenshot.height)
                record = AgentStepRecord(
                    step=step,
                    raw=raw,
                    action=action,
                    screenshot=screenshot,
                    execution=execution,
                )
                steps.append(record)
                context.append({"step": step, "action_text": raw})
                if execution.should_finish:
                    return AgentRunResult(
                        True,
                        execution.message or "",
                        step,
                        "handler_finish",
                        steps,
                    )
                continue

            record = AgentStepRecord(step=step, raw=raw, action=action, screenshot=screenshot)
            steps.append(record)
            context.append({"step": step, "action_text": raw})

        return AgentRunResult(False, "max_steps reached", self._max_steps, "max_steps", steps)

    def _build_messages(
        self,
        task: str,
        screenshot: Screenshot,
        context: list[dict[str, Any]],
        step: int,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt}]
        for entry in context:
            messages.append({"role": "assistant", "content": entry["action_text"]})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot.base64_data}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Task: {task}\n"
                            f"Step: {step}/{self._max_steps}\n"
                            "Return the next action."
                        ),
                    },
                ],
            }
        )
        return messages
