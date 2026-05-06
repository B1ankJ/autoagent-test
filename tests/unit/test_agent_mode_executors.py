from __future__ import annotations

from dataclasses import dataclass

import pytest

from autoagent.executors.base import ExecutorContext
from autoagent.executors.response_llm_extractor import LLMExtractionResult
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AgentAndroidProfile, AgentPcProfile


@pytest.mark.asyncio
async def test_agent_pc_executor_runs_task_and_propagates_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autoagent.executors.agent_core.device import Screenshot
    from autoagent.executors.agent_pc_executor import AgentPcExecutor

    seen: dict[str, object] = {}

    @dataclass
    class FakeDevice:
        def capture(self) -> Screenshot:
            seen["captured"] = True
            return Screenshot(base64_data="abc123==", width=100, height=50)

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            seen["client_model"] = config.model

    class FakeLoop:
        def __init__(self, device, client, system_prompt, max_steps) -> None:  # noqa: ANN001
            seen["loop_device"] = device
            seen["loop_prompt"] = system_prompt
            seen["loop_max_steps"] = max_steps

        def run(self, task: str) -> None:
            seen["task"] = task

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

    ctx = ExecutorContext()
    result = await AgentPcExecutor().execute(sample, profile, ctx)

    assert result == ["pc reply"]
    assert ctx.llm_responses == ["pc reply"]
    assert ctx.llm_errors == [None]
    assert seen["task"] == "reset then do hello"
    assert seen["response_hint"] == "latest assistant reply"
    assert seen["loop_max_steps"] == 7


@pytest.mark.asyncio
async def test_agent_android_executor_prefers_ctx_device_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autoagent.executors.agent_android_executor import AgentAndroidExecutor
    from autoagent.executors.agent_core.device import Screenshot

    seen: dict[str, object] = {}

    class FakeDevice:
        def __init__(self, serial: str | None = None) -> None:
            seen["serial"] = serial

        def capture(self) -> Screenshot:
            return Screenshot(base64_data="xyz==", width=50, height=100)

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            seen["client_model"] = config.model

    class FakeLoop:
        def __init__(self, device, client, system_prompt, max_steps) -> None:  # noqa: ANN001
            seen["loop_max_steps"] = max_steps

        def run(self, task: str) -> None:
            seen["task"] = task

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

    ctx = ExecutorContext(device_serial="ctx-serial")
    result = await AgentAndroidExecutor().execute(sample, profile, ctx)

    assert result == ["android reply"]
    assert ctx.llm_responses == ["android reply"]
    assert ctx.llm_errors == ["auth"]
    assert seen["serial"] == "ctx-serial"
    assert seen["task"] == "tap and send hello"
    assert seen["loop_max_steps"] == 9
