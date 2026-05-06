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
        conversation: list[dict[str, Any]] = []

        for step in range(1, self._max_steps + 1):
            screenshot = self._device.capture()
            messages = self._build_messages(task, screenshot, context, steps, step)
            raw = self._client.call(messages)
            _log.debug("agent_runtime step=%d raw=%r", step, raw[:200])
            action = parse_action(raw)
            user_message = self._strip_images(messages[-1])
            conversation.append(user_message)

            if action.get("_metadata") == "finish":
                record = AgentStepRecord(step=step, raw=raw, action=action, screenshot=screenshot)
                steps.append(record)
                conversation.append(self._assistant_message(raw))
                return AgentRunResult(
                    True,
                    str(action.get("message", "")),
                    step,
                    "finish",
                    steps,
                    conversation,
                )

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
                assistant_message = self._assistant_message(raw)
                context.extend([user_message, assistant_message])
                conversation.append(assistant_message)
                if execution.should_finish:
                    return AgentRunResult(
                        True,
                        execution.message or "",
                        step,
                        "handler_finish",
                        steps,
                        conversation,
                    )
                continue

            record = AgentStepRecord(step=step, raw=raw, action=action, screenshot=screenshot)
            steps.append(record)
            assistant_message = self._assistant_message(raw)
            context.extend([user_message, assistant_message])
            conversation.append(assistant_message)

        return AgentRunResult(
            False,
            "max_steps reached",
            self._max_steps,
            "max_steps",
            steps,
            conversation,
        )

    def _build_messages(
        self,
        task: str,
        screenshot: Screenshot,
        context: list[dict[str, Any]],
        steps: list[AgentStepRecord],
        step: int,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt}]
        messages.extend(context)
        text = self._build_user_text(task, screenshot, steps, step)
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
                        "text": text,
                    },
                ],
            }
        )
        return messages

    def _build_user_text(
        self,
        task: str,
        screenshot: Screenshot,
        steps: list[AgentStepRecord],
        step: int,
    ) -> str:
        screen_info = (
            f"Screen info:\n"
            f'- width={screenshot.width}\n'
            f'- height={screenshot.height}\n'
        )
        recent_summary = self._recent_steps_summary(steps)
        repeated_action_warning = self._repeated_action_warning(steps)
        sections = [
            f"Task: {task}",
            f"Step: {step}/{self._max_steps}",
            screen_info,
        ]
        if recent_summary:
            sections.append(f"Recent steps:\n{recent_summary}")
        if repeated_action_warning:
            sections.append(f"Repeated action warning:\n{repeated_action_warning}")
        sections.append(
            "Strategy:\n"
            "- First observe the screenshot and identify the focused app state.\n"
            "- If no input is focused yet, tap the correct input area before typing.\n"
            "- Do not repeat the same action if the screen does not appear to change.\n"
            "- After typing, look for the send control or use a submit key if appropriate.\n"
            "- Return exactly one next action."
        )
        return "\n\n".join(sections)

    def _recent_steps_summary(self, steps: list[AgentStepRecord]) -> str:
        if not steps:
            return ""
        lines = []
        for record in steps[-3:]:
            action_name = record.action.get("action", record.action.get("_metadata", "unknown"))
            execution = record.execution
            execution_text = "pending"
            if execution is not None:
                execution_text = (
                    "ok"
                    if execution.success
                    else f"failed: {execution.message or 'unknown'}"
                )
            lines.append(f"Step {record.step}: {action_name} -> {execution_text}")
        return "\n".join(lines)

    def _repeated_action_warning(self, steps: list[AgentStepRecord]) -> str:
        if len(steps) < 2:
            return ""
        recent = [
            record.action.get("action", record.action.get("_metadata"))
            for record in steps[-3:]
        ]
        if len(recent) >= 2 and len(set(recent[-2:])) == 1:
            action_name = str(recent[-1])
            return (
                f"The last {len(recent[-2:])} actions repeated `{action_name}`. "
                "Only repeat it if the screenshot clearly changed and the action is still needed."
            )
        return ""

    def _assistant_message(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("<answer>") and text.endswith("</answer>"):
            return {"role": "assistant", "content": text}
        return {"role": "assistant", "content": f"<answer>{text}</answer>"}

    def _strip_images(self, message: dict[str, Any]) -> dict[str, Any]:
        content = message.get("content")
        if not isinstance(content, list):
            return message
        text_items = [item for item in content if item.get("type") == "text"]
        return {"role": message["role"], "content": text_items}
