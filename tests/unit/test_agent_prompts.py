from __future__ import annotations

from autoagent.executors.agent_core.prompts import ANDROID_SYSTEM_PROMPT, PC_SYSTEM_PROMPT


def test_pc_prompt_mentions_relative_coordinate_contract() -> None:
    assert "0-1000" in PC_SYSTEM_PROMPT
    assert "相对坐标" in PC_SYSTEM_PROMPT


def test_android_prompt_mentions_relative_coordinate_contract() -> None:
    assert "0-1000" in ANDROID_SYSTEM_PROMPT
    assert "相对坐标" in ANDROID_SYSTEM_PROMPT
