import pytest

from autoagent.api._deps import _build_executor
from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.web_executor import WebExecutor


def test_api_mode_returns_api_executor() -> None:
    assert isinstance(_build_executor("api"), ApiExecutor)


def test_gui_pc_web_returns_web_executor() -> None:
    assert isinstance(_build_executor("gui_pc_web"), WebExecutor)


def test_unsupported_mode_raises() -> None:
    with pytest.raises(ValueError):
        _build_executor("gui_android")
