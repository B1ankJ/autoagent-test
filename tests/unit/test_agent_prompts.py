from __future__ import annotations

from autoagent.executors.agent_core.prompts import ANDROID_SYSTEM_PROMPT, PC_SYSTEM_PROMPT


def test_pc_prompt_mentions_relative_coordinate_contract() -> None:
    assert "0-1000" in PC_SYSTEM_PROMPT
    assert "相对坐标" in PC_SYSTEM_PROMPT


def test_pc_prompt_mentions_input_focus_constraints() -> None:
    assert "输入框" in PC_SYSTEM_PROMPT
    assert "占位文字" in PC_SYSTEM_PROMPT
    assert "工具栏空白" in PC_SYSTEM_PROMPT
    assert "发送按钮" in PC_SYSTEM_PROMPT
    assert "语音按钮" in PC_SYSTEM_PROMPT


def test_android_prompt_mentions_relative_coordinate_contract() -> None:
    assert "0-1000" in ANDROID_SYSTEM_PROMPT
    assert "相对坐标" in ANDROID_SYSTEM_PROMPT
