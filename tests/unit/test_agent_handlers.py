from __future__ import annotations

from unittest.mock import Mock, patch

from autoagent.executors.agent_core.handlers.android import AndroidActionHandler
from autoagent.executors.agent_core.handlers.pc import PcActionHandler


def test_pc_handler_executes_tap() -> None:
    device = Mock()
    handler = PcActionHandler(device=device)

    result = handler.execute(
        {"_metadata": "do", "action": "Tap", "element": [500, 500]},
        1920,
        1080,
    )

    device.tap.assert_called_once_with(960, 540)
    assert result.success is True
    assert result.should_finish is False


def test_pc_handler_accepts_click_alias_for_tap() -> None:
    device = Mock()
    handler = PcActionHandler(device=device)

    result = handler.execute(
        {"_metadata": "do", "action": "Click", "element": [500, 500]},
        1920,
        1080,
    )

    device.tap.assert_called_once_with(960, 540)
    assert result.success is True


def test_pc_handler_accepts_double_click_alias() -> None:
    device = Mock()
    handler = PcActionHandler(device=device)

    result = handler.execute(
        {"_metadata": "do", "action": "double_click", "element": [500, 500]},
        1920,
        1080,
    )

    device.double_tap.assert_called_once_with(960, 540)
    assert result.success is True


def test_pc_handler_executes_hotkey() -> None:
    device = Mock()
    handler = PcActionHandler(device=device)

    result = handler.execute(
        {"_metadata": "do", "action": "Hotkey", "keys": ["ctrl", "c"]},
        1920,
        1080,
    )

    device.hotkey.assert_called_once_with("ctrl", "c")
    assert result.success is True
    assert result.should_finish is False


def test_pc_handler_waits_for_duration() -> None:
    device = Mock()
    handler = PcActionHandler(device=device)

    with patch("autoagent.executors.agent_core.handlers.pc.time.sleep") as mock_sleep:
        result = handler.execute(
            {"_metadata": "do", "action": "Wait", "duration": "1.5 seconds"},
            1920,
            1080,
        )

    mock_sleep.assert_called_once_with(1.5)
    assert result.success is True
    assert result.should_finish is False


def test_android_handler_executes_back() -> None:
    device = Mock()
    handler = AndroidActionHandler(device=device)

    result = handler.execute({"_metadata": "do", "action": "Back"}, 1080, 2400)

    device.press_key.assert_called_once_with("back")
    assert result.success is True
    assert result.should_finish is False


def test_android_handler_executes_long_press() -> None:
    device = Mock()
    handler = AndroidActionHandler(device=device)

    result = handler.execute(
        {"_metadata": "do", "action": "Long Press", "element": [250, 500], "duration_ms": 800},
        1080,
        2400,
    )

    device.long_press.assert_called_once_with(270, 1200, duration_ms=800)
    assert result.success is True
    assert result.should_finish is False
