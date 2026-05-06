from __future__ import annotations

import base64
from dataclasses import dataclass

import pytest

from autoagent.executors.agent_core.action_parser import parse_action as parse_legacy_action
from autoagent.executors.agent_core.agent_loop import AgentResult, AgentStepRecord
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

    class FakeLoop:
        def __init__(self, device, client, system_prompt, max_steps) -> None:  # noqa: ANN001
            seen["loop_device"] = device
            seen["loop_prompt"] = system_prompt
            seen["loop_max_steps"] = max_steps

        def run(self, task: str) -> AgentResult:
            seen["task"] = task
            raw_action = 'do(action="Tap", element=[10, 20])'
            return AgentResult(
                finished=True,
                finish_message="done",
                step_count=1,
                steps=[
                    AgentStepRecord(
                        step=1,
                        raw=raw_action,
                        action=parse_legacy_action(raw_action),
                        screenshot=Screenshot(
                            base64_data=base64.b64encode(b"pc-step-shot").decode(),
                            width=100,
                            height=50,
                        ),
                    )
                ],
            )

    async def fake_extract_response_from_screenshot(**kwargs):  # noqa: ANN003
        seen["response_hint"] = kwargs["response_hint"]
        return LLMExtractionResult(text="pc reply", error=None, latency_ms=1, status_code=200)

    monkeypatch.setattr("autoagent.executors.agent_pc_executor.PcDevice", FakeDevice)
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
            "action": {"_type": "click", "x": 10, "y": 20},
        }
    ]
    assert ctx.logs_dir == str((tmp_path / "batch-1" / "s1").resolve())
    assert any(isinstance(item, ScreenshotResult) for item in ctx.screenshot_index)
    assert (tmp_path / "batch-1" / "s1" / "step_1_1.png").is_file()
    assert (tmp_path / "batch-1" / "s1" / "final_1.png").is_file()
    assert (tmp_path / "batch-1" / "s1" / "loop_trace_1.json").is_file()
    assert (tmp_path / "batch-1" / "s1" / "extract_1.json").is_file()
    assert seen["task"] == "reset then do hello"
    assert seen["response_hint"] == "latest assistant reply"
    assert seen["loop_max_steps"] == 7


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

    class FakeLoop:
        def __init__(self, device, client, system_prompt, max_steps) -> None:  # noqa: ANN001
            seen["loop_max_steps"] = max_steps

        def run(self, task: str) -> AgentResult:
            seen["task"] = task
            return AgentResult(
                finished=False,
                finish_message="max_steps reached",
                step_count=1,
                steps=[
                    AgentStepRecord(
                        step=1,
                        raw='Action: press(back)',
                        action={"_type": "press", "key": "back"},
                        screenshot=Screenshot(
                            base64_data=base64.b64encode(b"android-step-shot").decode(),
                            width=50,
                            height=100,
                        ),
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
            "raw": 'Action: press(back)',
            "action": {"_type": "press", "key": "back"},
        }
    ]
    assert ctx.logs_dir == str((tmp_path / "batch-2" / "s1").resolve())
    assert (tmp_path / "batch-2" / "s1" / "step_1_1.png").is_file()
    assert (tmp_path / "batch-2" / "s1" / "final_1.png").is_file()
    assert (tmp_path / "batch-2" / "s1" / "loop_trace_1.json").is_file()
    assert (tmp_path / "batch-2" / "s1" / "extract_1.json").is_file()
    assert seen["serial"] == "ctx-serial"
    assert seen["task"] == "tap and send hello"
    assert seen["loop_max_steps"] == 9
