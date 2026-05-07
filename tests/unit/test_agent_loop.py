from __future__ import annotations

import base64
import copy
from dataclasses import dataclass

from autoagent.executors.agent_core.agent_loop import AgentResult, AgentStepRecord
from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.agent_core.result import ActionResult, AgentRunResult
from autoagent.executors.agent_core.runtime import AgentRuntime


def _screenshot() -> Screenshot:
    return Screenshot(
        base64_data=base64.b64encode(b"fake-png-bytes").decode(),
        width=1920,
        height=1080,
    )


@dataclass
class FakeDevice:
    def capture(self) -> Screenshot:
        return _screenshot()


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0
        self.calls: list[list[dict]] = []

    def call(self, messages) -> str:  # noqa: ANN001
        self.calls.append(copy.deepcopy(messages))
        response = self._responses[self._index]
        self._index += 1
        return response


class FakeHandler:
    def __init__(self, results: list[ActionResult]) -> None:
        self._results = results
        self.calls: list[tuple[dict, int, int]] = []

    def execute(self, action: dict, screen_width: int, screen_height: int) -> ActionResult:
        self.calls.append((action, screen_width, screen_height))
        return self._results[len(self.calls) - 1]


class FakeResponseObserver:
    def __init__(self, outcomes: list[tuple[bool, str]]) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, str, int]] = []

    def __call__(self, task: str, response_hint: str, screenshot: Screenshot) -> tuple[bool, str]:
        self.calls.append((task, response_hint, screenshot.width))
        return self._outcomes[len(self.calls) - 1]


class FakeActionObserver:
    def __init__(self, outcomes: list[tuple[bool, str] | None]) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, dict, int]] = []

    def __call__(self, task: str, action: dict, screenshot: Screenshot) -> tuple[bool, str] | None:
        self.calls.append((task, action, screenshot.width))
        return self._outcomes[len(self.calls) - 1]


def test_runtime_stops_on_finish_action() -> None:
    device = FakeDevice()
    client = FakeClient(['finish(message="done")'])
    handler = FakeHandler([ActionResult(success=True, should_finish=True, message="done")])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="x",
        max_steps=3,
    )
    result = runtime.run("task")

    assert result.finished is True
    assert result.stop_reason == "finish"
    assert result.step_count == 1
    assert result.finish_message == "done"
    assert len(result.steps) == 1
    assert result.steps[0].action == {"_metadata": "finish", "message": "done"}
    assert result.steps[0].execution is None


def test_agent_loop_exports_canonical_result_types() -> None:
    assert AgentResult is AgentRunResult
    assert AgentStepRecord.__module__ == "autoagent.executors.agent_core.result"


def test_runtime_records_execution_result() -> None:
    device = FakeDevice()
    client = FakeClient(['do(action="Tap", element=[100, 200])', 'finish(message="done")'])
    handler = FakeHandler(
        [
            ActionResult(success=True, should_finish=False),
            ActionResult(success=True, should_finish=True, message="done"),
        ]
    )

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="x",
        max_steps=3,
    )
    result = runtime.run("task")

    assert result.finished is True
    assert result.finish_message == "done"
    assert result.stop_reason == "finish"
    assert result.steps[0].execution is not None
    assert result.steps[0].execution.success is True
    assert result.steps[0].action["action"] == "Tap"
    assert handler.calls[0][1:] == (1920, 1080)


def test_runtime_carries_forward_text_only_conversation_context() -> None:
    device = FakeDevice()
    client = FakeClient(['do(action="Tap", element=[100, 200])', 'finish(message="done")'])
    handler = FakeHandler([ActionResult(success=True, should_finish=False)])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=3,
    )
    result = runtime.run("task")

    second_call = client.calls[1]
    assert len(second_call) == 4
    assert second_call[1]["role"] == "user"
    assert second_call[1]["content"] == [
        {
            "type": "text",
            "text": result.conversation[0]["content"][0]["text"],
        }
    ]
    assert second_call[2]["role"] == "assistant"
    assert second_call[2]["content"] == '<answer>do(action="Tap", element=[100, 200])</answer>'


def test_runtime_includes_recent_step_summary_and_repeated_action_warning() -> None:
    device = FakeDevice()
    client = FakeClient(
        [
            'do(action="Type", text="hello")',
            'do(action="Type", text="hello")',
            'finish(message="done")',
        ]
    )
    handler = FakeHandler(
        [
            ActionResult(success=True, should_finish=False),
            ActionResult(success=True, should_finish=False),
        ]
    )

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=3,
    )
    runtime.run("send hello")

    third_call_user = client.calls[2][-1]
    third_call_text = third_call_user["content"][1]["text"]
    assert "Recent steps:" in third_call_text
    assert "Step 1: Type" in third_call_text
    assert "Repeated action warning" in third_call_text


def test_runtime_does_not_double_wrap_answer_tags_in_conversation() -> None:
    device = FakeDevice()
    client = FakeClient(
        ['<answer>do(action="Tap", element=[500, 500])</answer>', 'finish(message="done")']
    )
    handler = FakeHandler([ActionResult(success=True, should_finish=False)])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=3,
    )
    result = runtime.run("task")

    assert (
        result.conversation[1]["content"]
        == '<answer>do(action="Tap", element=[500, 500])</answer>'
    )


def test_runtime_stops_at_max_steps() -> None:
    device = FakeDevice()
    client = FakeClient(
        ["Action: click(100, 200)", "Action: click(100, 200)", "Action: click(100, 200)"]
    )
    handler = FakeHandler(
        [
            ActionResult(success=True, should_finish=False),
            ActionResult(success=True, should_finish=False),
            ActionResult(success=True, should_finish=False),
        ]
    )

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=3,
    )
    result = runtime.run("do something")

    assert result.finished is False
    assert result.stop_reason == "max_steps"
    assert result.step_count == 3
    assert result.finish_message == "max_steps reached"
    assert len(result.steps) == 3
    assert len(handler.calls) == 3


def test_runtime_skips_noop_but_counts_step() -> None:
    device = FakeDevice()
    client = FakeClient(["gibberish output", 'finish(message="ok")'])
    handler = FakeHandler([ActionResult(success=True, should_finish=False)])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=10,
    )
    result = runtime.run("task")

    assert result.finished is True
    assert result.step_count == 2
    assert result.stop_reason == "finish"
    assert len(handler.calls) == 0
    assert result.steps[0].action["_metadata"] == "noop"


def test_runtime_requires_response_observer_confirmation_before_finish() -> None:
    device = FakeDevice()
    client = FakeClient(
        [
            'do(action="Press", key="enter")',
            'finish(message="done")',
            'finish(message="done")',
        ]
    )
    handler = FakeHandler([ActionResult(success=True, should_finish=False)])
    observer = FakeResponseObserver([(False, ""), (True, "assistant reply")])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=4,
        response_hint="latest assistant reply",
        response_observer=observer,
    )
    result = runtime.run("task")

    assert result.finished is True
    assert result.stop_reason == "finish"
    assert result.finish_message == "assistant reply"
    assert result.step_count == 3
    assert observer.calls[0][1] == "latest assistant reply"
    assert result.steps[1].action == {"_metadata": "noop", "raw": 'finish(message="done")'}


def test_runtime_finish_without_observer_keeps_existing_behavior() -> None:
    device = FakeDevice()
    client = FakeClient(['finish(message="done")'])
    handler = FakeHandler([ActionResult(success=True, should_finish=False)])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=3,
    )
    result = runtime.run("task")

    assert result.finished is True
    assert result.finish_message == "done"
    assert result.step_count == 1


def test_runtime_marks_type_failed_when_multimodal_input_check_rejects_it() -> None:
    device = FakeDevice()
    client = FakeClient(['do(action="Type", text="hello")', 'finish(message="done")'])
    handler = FakeHandler([ActionResult(success=True, should_finish=False)])
    observer = FakeActionObserver([(False, "typed text not visible in input field")])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=3,
        action_observer=observer,
    )
    result = runtime.run("task")

    assert result.steps[0].execution is not None
    assert result.steps[0].execution.success is False
    assert result.steps[0].execution.message == "typed text not visible in input field"
    second_call_text = client.calls[1][-1]["content"][1]["text"]
    assert "failed: typed text not visible in input field" in second_call_text
    assert observer.calls[0][1]["action"] == "Type"


def test_runtime_blocks_press_enter_after_failed_type_validation() -> None:
    device = FakeDevice()
    client = FakeClient(
        [
            'do(action="Type", text="hello")',
            'do(action="Press", key="enter")',
            'do(action="Tap", element=[500, 500])',
        ]
    )
    handler = FakeHandler(
        [
            ActionResult(success=True, should_finish=False),
            ActionResult(success=True, should_finish=False),
            ActionResult(success=True, should_finish=False),
        ]
    )
    observer = FakeActionObserver([(False, "typed text not visible in input field")])

    runtime = AgentRuntime(
        device=device,
        client=client,
        handler=handler,
        system_prompt="sys",
        max_steps=3,
        action_observer=observer,
    )
    result = runtime.run("task")

    assert result.steps[0].execution is not None
    assert result.steps[0].execution.success is False
    assert result.steps[1].action["action"] == "Press"
    assert result.steps[1].execution is not None
    assert result.steps[1].execution.success is False
    assert "Input is not ready" in (result.steps[1].execution.message or "")
    assert len(handler.calls) == 2
