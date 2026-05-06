from __future__ import annotations

import logging
from typing import Any

from autoagent.executors.agent_core.action_parser import parse_action
from autoagent.executors.agent_core.device import Device, Screenshot
from autoagent.executors.agent_core.model_client import ModelClient
from autoagent.executors.agent_core.result import AgentResult, AgentStepRecord

_log = logging.getLogger(__name__)


class AgentLoop:
    def __init__(
        self,
        device: Device,
        client: ModelClient,
        system_prompt: str,
        max_steps: int,
    ) -> None:
        self._device = device
        self._client = client
        self._system_prompt = system_prompt
        self._max_steps = max_steps

    def run(self, task: str) -> AgentResult:
        context: list[dict[str, Any]] = []
        steps: list[AgentStepRecord] = []
        for step in range(1, self._max_steps + 1):
            screenshot = self._device.capture()
            messages = self._build_messages(task, screenshot, context, step)
            raw = self._client.call(messages)
            _log.debug("agent_loop step=%d raw=%r", step, raw[:200])
            action = parse_action(raw)
            context.append({"step": step, "action_text": raw})
            steps.append(AgentStepRecord(step=step, raw=raw, action=action, screenshot=screenshot))

            if action["_type"] == "finish":
                return AgentResult(
                    finished=True,
                    finish_message=action.get("message", ""),
                    step_count=step,
                    steps=steps,
                )
            if action["_type"] != "noop":
                self._device.execute_action(action)

        return AgentResult(
            finished=False,
            finish_message="max_steps reached",
            step_count=self._max_steps,
            steps=steps,
        )

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
