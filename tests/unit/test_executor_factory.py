import pytest

from autoagent.api._deps import _build_executor
from autoagent.executors.agent_android_executor import AgentAndroidExecutor
from autoagent.executors.agent_pc_executor import AgentPcExecutor
from autoagent.executors.android_executor import AndroidExecutor
from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.web_executor import WebExecutor


def test_api_mode_returns_api_executor() -> None:
    assert isinstance(_build_executor("api"), ApiExecutor)


def test_gui_pc_web_returns_web_executor() -> None:
    assert isinstance(_build_executor("gui_pc_web"), WebExecutor)


def test_gui_android_returns_android_executor() -> None:
    assert isinstance(_build_executor("gui_android"), AndroidExecutor)


def test_agent_pc_returns_agent_pc_executor() -> None:
    assert isinstance(_build_executor("agent_pc"), AgentPcExecutor)


def test_agent_android_returns_agent_android_executor() -> None:
    assert isinstance(_build_executor("agent_android"), AgentAndroidExecutor)


def test_unsupported_mode_raises() -> None:
    with pytest.raises(ValueError):
        _build_executor("bogus_mode")
