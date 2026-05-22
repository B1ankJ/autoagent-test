from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import pytest

from autoagent.executors.agent_core.agent_loop import AgentResult, AgentStepRecord
from autoagent.executors.agent_core.result import ActionResult
from autoagent.executors.base import ExecutorContext
from autoagent.executors.response_llm_extractor import LLMExtractionResult
from autoagent.executors.screenshot_store import ScreenshotResult
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AgentAndroidProfile, AgentPcProfile


@pytest.mark.asyncio
async def test_agent_pc_executor_runs_task_and_propagates_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from autoagent.executors.agent_core.device import Screenshot
    from autoagent.executors.agent_pc_executor import AgentPcExecutor

    seen: dict[str, object] = {}

    @dataclass
    class FakeDevice:
        def capture(self) -> Screenshot:
            seen["captured"] = True
            return Screenshot(
                base64_data=base64.b64encode(b"pc-final-shot").decode(),
                width=100,
                height=50,
            )

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            seen["client_model"] = config.model

    class FakeHandler:
        def __init__(self, device) -> None:  # noqa: ANN001
            seen["handler_device"] = device

    class FakeLoop:
        def __init__(
            self,
            device,
            client,
            handler,
            system_prompt,
            max_steps,
            response_hint=None,
            response_observer=None,
            action_observer=None,
        ) -> None:  # noqa: ANN001
            seen["loop_device"] = device
            seen["loop_handler"] = handler
            seen["loop_prompt"] = system_prompt
            seen["loop_max_steps"] = max_steps
            seen["loop_response_hint"] = response_hint
            seen["loop_response_observer"] = response_observer
            seen["loop_action_observer"] = action_observer

        def run(self, task: str) -> AgentResult:
            seen["task"] = task
            raw_action = 'do(action="Tap", element=[10, 20])'
            return AgentResult(
                finished=True,
                finish_message="done",
                step_count=1,
                stop_reason="handler_finish",
                conversation=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Task: reset then do hello"}],
                    },
                    {
                        "role": "assistant",
                        "content": '<answer>do(action="Tap", element=[10, 20])</answer>',
                    },
                ],
                steps=[
                    AgentStepRecord(
                        step=1,
                        raw=raw_action,
                        action={"_metadata": "do", "action": "Tap", "element": [10, 20]},
                        screenshot=Screenshot(
                            base64_data=base64.b64encode(b"pc-step-shot").decode(),
                            width=100,
                            height=50,
                        ),
                        execution=ActionResult(success=True, should_finish=False),
                    )
                ],
            )

    async def fake_extract_response_from_screenshot(**kwargs):  # noqa: ANN003
        seen["response_hint"] = kwargs["response_hint"]
        return LLMExtractionResult(text="pc reply", error=None, latency_ms=1, status_code=200)

    monkeypatch.setattr("autoagent.executors.agent_pc_executor.PcDevice", FakeDevice)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.PcActionHandler", FakeHandler)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.ModelClient", FakeClient)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.AgentLoop", FakeLoop)
    monkeypatch.setattr(
        "autoagent.executors.agent_pc_executor.extract_response_from_screenshot",
        fake_extract_response_from_screenshot,
    )

    profile = AgentPcProfile.model_validate(
        {
            "name": "pc",
            "platform": "agent_pc",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "api_key": "k",
            "task_template": "do {prompt}",
            "new_session_task_template": "reset then do {prompt}",
            "response_hint": "latest assistant reply",
            "max_steps": 7,
        }
    )
    sample = Sample(
        id="s1",
        prompts=["hello"],
        mode="agent_pc",
        target_profile="pc",
        new_session=True,
        retry=0,
    )

    ctx = ExecutorContext(logs_dir="batch-1")
    result = await AgentPcExecutor(screenshots_root=tmp_path).execute(sample, profile, ctx)

    assert result == ["pc reply"]
    assert ctx.llm_responses == ["pc reply"]
    assert ctx.llm_errors == [None]
    assert ctx.action_log == [
        {
            "step": 1,
            "raw": 'do(action="Tap", element=[10, 20])',
            "action": {"_metadata": "do", "action": "Tap", "element": [10, 20]},
            "execution": {"success": True, "should_finish": False, "message": None},
        }
    ]
    assert ctx.logs_dir == str((tmp_path / "batch-1" / "s1").resolve())
    assert any(isinstance(item, ScreenshotResult) for item in ctx.screenshot_index)
    assert (tmp_path / "batch-1" / "s1" / "step_1_1.png").is_file()
    assert (tmp_path / "batch-1" / "s1" / "final_1.png").is_file()
    trace_path = tmp_path / "batch-1" / "s1" / "loop_trace_1.json"
    assert trace_path.is_file()
    assert (tmp_path / "batch-1" / "s1" / "extract_1.json").is_file()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["steps"][0]["action"]["action"] == "Tap"
    assert trace["steps"][0]["execution"]["success"] is True
    assert trace["stop_reason"] == "handler_finish"
    assert (
        trace["conversation"][1]["content"]
        == '<answer>do(action="Tap", element=[10, 20])</answer>'
    )
    assert seen["task"] == "reset then do hello"
    assert seen["response_hint"] == "latest assistant reply"
    assert seen["loop_max_steps"] == 7
    assert seen["loop_response_hint"] == "latest assistant reply"
    assert seen["loop_response_observer"] is not None
    assert seen["loop_action_observer"] is not None
    assert seen["handler_device"] is seen["loop_device"]
    assert seen["loop_handler"] is not None


@pytest.mark.asyncio
async def test_agent_pc_executor_uses_clipboard_when_copy_extraction_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from autoagent.executors.agent_core.device import Screenshot
    from autoagent.executors.agent_pc_executor import AgentPcExecutor

    seen: dict[str, object] = {}

    class FakeDevice:
        def __init__(self) -> None:
            self._clipboard = ""

        def capture(self) -> Screenshot:
            return Screenshot(
                base64_data=base64.b64encode(b"pc-final-shot").decode(),
                width=10,
                height=10,
            )

        def clear_clipboard(self) -> None:
            seen["cleared"] = True
            self._clipboard = ""

        def read_clipboard(self) -> str:
            return "clipboard reply"

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            pass

    class FakeHandler:
        def __init__(self, device) -> None:  # noqa: ANN001
            pass

    class FakeLoop:
        instances: list[FakeLoop] = []

        def __init__(
            self,
            device,
            client,
            handler,
            system_prompt,
            max_steps,
            response_hint=None,
            response_observer=None,
            action_observer=None,
        ) -> None:  # noqa: ANN001
            self.max_steps = max_steps
            self.response_hint = response_hint
            self.is_copy = response_observer is None and response_hint is None
            FakeLoop.instances.append(self)

        def run(self, task: str) -> AgentResult:
            return AgentResult(
                finished=True,
                finish_message="ok",
                step_count=1,
                stop_reason="handler_finish",
                conversation=[],
                steps=[
                    AgentStepRecord(
                        step=1,
                        raw='do(action="Tap")',
                        action={"_metadata": "do", "action": "Tap"},
                        screenshot=Screenshot(
                            base64_data=base64.b64encode(b"shot").decode(),
                            width=10,
                            height=10,
                        ),
                        execution=ActionResult(success=True, should_finish=False),
                    )
                ],
            )

    async def fail_extract(**kwargs):  # noqa: ANN003
        raise AssertionError("VLM extraction should not run when clipboard succeeds")

    monkeypatch.setattr("autoagent.executors.agent_pc_executor.PcDevice", FakeDevice)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.PcActionHandler", FakeHandler)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.ModelClient", FakeClient)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.AgentLoop", FakeLoop)
    monkeypatch.setattr(
        "autoagent.executors.agent_pc_executor.extract_response_from_screenshot",
        fail_extract,
    )

    profile = AgentPcProfile.model_validate(
        {
            "name": "pc",
            "platform": "agent_pc",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "api_key": "k",
            "task_template": "do {prompt}",
            "response_hint": "latest reply",
            "max_steps": 5,
            "copy_extraction": {
                "task": "click the copy button",
                "wait_ms": 0,
                "max_steps": 3,
            },
        }
    )
    sample = Sample(id="s1", prompts=["hello"], mode="agent_pc", target_profile="pc", retry=0)

    ctx = ExecutorContext(logs_dir="batch-cp")
    result = await AgentPcExecutor(screenshots_root=tmp_path).execute(sample, profile, ctx)

    assert result == ["clipboard reply"]
    assert ctx.llm_responses == ["clipboard reply"]
    assert ctx.llm_errors == [None]
    assert seen.get("cleared") is True
    copy_trace = tmp_path / "batch-cp" / "s1" / "copy_1.json"
    assert copy_trace.is_file()
    payload = json.loads(copy_trace.read_text(encoding="utf-8"))
    assert payload["clipboard_text"] == "clipboard reply"
    extract_payload = json.loads(
        (tmp_path / "batch-cp" / "s1" / "extract_1.json").read_text(encoding="utf-8")
    )
    assert extract_payload["method"] == "clipboard"
    assert extract_payload["text"] == "clipboard reply"
    # sub-loop got its own max_steps
    sub_loops = [inst for inst in FakeLoop.instances if inst.is_copy]
    assert sub_loops and sub_loops[0].max_steps == 3


@pytest.mark.asyncio
async def test_agent_pc_executor_falls_back_to_vlm_when_clipboard_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from autoagent.executors.agent_core.device import Screenshot
    from autoagent.executors.agent_pc_executor import AgentPcExecutor

    class FakeDevice:
        def capture(self) -> Screenshot:
            return Screenshot(
                base64_data=base64.b64encode(b"shot").decode(), width=10, height=10
            )

        def clear_clipboard(self) -> None:
            pass

        def read_clipboard(self) -> str:
            return "   "  # only whitespace -> treated as empty

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            pass

    class FakeHandler:
        def __init__(self, device) -> None:  # noqa: ANN001
            pass

    class FakeLoop:
        def __init__(self, *a, **kw) -> None:  # noqa: ANN001, ANN003
            pass

        def run(self, task: str) -> AgentResult:
            return AgentResult(
                finished=True,
                finish_message="ok",
                step_count=0,
                stop_reason="handler_finish",
                conversation=[],
                steps=[],
            )

    async def fake_extract(**kwargs):  # noqa: ANN003
        return LLMExtractionResult(text="vlm reply", error=None, latency_ms=1, status_code=200)

    monkeypatch.setattr("autoagent.executors.agent_pc_executor.PcDevice", FakeDevice)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.PcActionHandler", FakeHandler)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.ModelClient", FakeClient)
    monkeypatch.setattr("autoagent.executors.agent_pc_executor.AgentLoop", FakeLoop)
    monkeypatch.setattr(
        "autoagent.executors.agent_pc_executor.extract_response_from_screenshot",
        fake_extract,
    )

    profile = AgentPcProfile.model_validate(
        {
            "name": "pc",
            "platform": "agent_pc",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "api_key": "k",
            "task_template": "do {prompt}",
            "response_hint": "latest reply",
            "copy_extraction": {
                "task": "click the copy button",
                "wait_ms": 0,
                "fallback_to_vlm": True,
            },
        }
    )
    sample = Sample(id="s1", prompts=["hi"], mode="agent_pc", target_profile="pc", retry=0)
    ctx = ExecutorContext(logs_dir="batch-fb")
    result = await AgentPcExecutor(screenshots_root=tmp_path).execute(sample, profile, ctx)

    assert result == ["vlm reply"]
    extract_payload = json.loads(
        (tmp_path / "batch-fb" / "s1" / "extract_1.json").read_text(encoding="utf-8")
    )
    assert extract_payload["method"] == "vlm_fallback"


@pytest.mark.asyncio
async def test_agent_android_executor_prefers_ctx_device_serial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from autoagent.executors.agent_android_executor import AgentAndroidExecutor
    from autoagent.executors.agent_core.device import Screenshot

    seen: dict[str, object] = {}

    class FakeDevice:
        def __init__(self, serial: str | None = None) -> None:
            seen["serial"] = serial

        def capture(self) -> Screenshot:
            return Screenshot(
                base64_data=base64.b64encode(b"android-final-shot").decode(),
                width=50,
                height=100,
            )

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            seen["client_model"] = config.model

    class FakeHandler:
        def __init__(self, device) -> None:  # noqa: ANN001
            seen["handler_device"] = device

    class FakeLoop:
        def __init__(
            self,
            device,
            client,
            handler,
            system_prompt,
            max_steps,
            response_hint=None,
            response_observer=None,
            action_observer=None,
        ) -> None:  # noqa: ANN001
            seen["loop_handler"] = handler
            seen["loop_max_steps"] = max_steps
            seen["loop_response_hint"] = response_hint
            seen["loop_response_observer"] = response_observer
            seen["loop_action_observer"] = action_observer

        def run(self, task: str) -> AgentResult:
            seen["task"] = task
            return AgentResult(
                finished=False,
                finish_message="max_steps reached",
                step_count=1,
                stop_reason="max_steps",
                conversation=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Task: tap and send hello"}],
                    },
                    {"role": "assistant", "content": '<answer>do(action="Back")</answer>'},
                ],
                steps=[
                    AgentStepRecord(
                        step=1,
                        raw='do(action="Back")',
                        action={"_metadata": "do", "action": "Back"},
                        screenshot=Screenshot(
                            base64_data=base64.b64encode(b"android-step-shot").decode(),
                            width=50,
                            height=100,
                        ),
                        execution=ActionResult(success=True, should_finish=False),
                    )
                ],
            )

    async def fake_extract_response_from_screenshot(**kwargs):  # noqa: ANN003
        return LLMExtractionResult(
            text="android reply",
            error="auth",
            latency_ms=1,
            status_code=401,
        )

    monkeypatch.setattr("autoagent.executors.agent_android_executor.AndroidDevice", FakeDevice)
    monkeypatch.setattr(
        "autoagent.executors.agent_android_executor.AndroidActionHandler",
        FakeHandler,
    )
    monkeypatch.setattr("autoagent.executors.agent_android_executor.ModelClient", FakeClient)
    monkeypatch.setattr("autoagent.executors.agent_android_executor.AgentLoop", FakeLoop)
    monkeypatch.setattr(
        "autoagent.executors.agent_android_executor.extract_response_from_screenshot",
        fake_extract_response_from_screenshot,
    )

    profile = AgentAndroidProfile.model_validate(
        {
            "name": "android",
            "platform": "agent_android",
            "serial": "profile-serial",
            "base_url": "https://api.example.com/v1",
            "model": "m",
            "api_key": "k",
            "task_template": "tap and send {prompt}",
            "response_hint": "latest reply bubble",
            "max_steps": 9,
        }
    )
    sample = Sample(
        id="s1",
        prompts=["hello"],
        mode="agent_android",
        target_profile="android",
        retry=0,
    )

    ctx = ExecutorContext(device_serial="ctx-serial", logs_dir="batch-2")
    result = await AgentAndroidExecutor(screenshots_root=tmp_path).execute(sample, profile, ctx)

    assert result == ["android reply"]
    assert ctx.llm_responses == ["android reply"]
    assert ctx.llm_errors == ["auth"]
    assert ctx.action_log == [
        {
            "step": 1,
            "raw": 'do(action="Back")',
            "action": {"_metadata": "do", "action": "Back"},
            "execution": {"success": True, "should_finish": False, "message": None},
        }
    ]
    assert ctx.logs_dir == str((tmp_path / "batch-2" / "s1").resolve())
    assert (tmp_path / "batch-2" / "s1" / "step_1_1.png").is_file()
    assert (tmp_path / "batch-2" / "s1" / "final_1.png").is_file()
    trace_path = tmp_path / "batch-2" / "s1" / "loop_trace_1.json"
    assert trace_path.is_file()
    assert (tmp_path / "batch-2" / "s1" / "extract_1.json").is_file()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["steps"][0]["action"]["action"] == "Back"
    assert trace["steps"][0]["execution"]["success"] is True
    assert trace["stop_reason"] == "max_steps"
    assert trace["conversation"][1]["content"] == '<answer>do(action="Back")</answer>'
    assert seen["serial"] == "ctx-serial"
    assert seen["task"] == "tap and send hello"
    assert seen["loop_max_steps"] == 9
    assert seen["loop_response_hint"] == "latest reply bubble"
    assert seen["loop_response_observer"] is not None
    assert seen["loop_action_observer"] is not None
    assert seen["loop_handler"] is not None
