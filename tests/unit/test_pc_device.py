"""Unit tests for PcDevice adapter methods with pyautogui mocked."""

from __future__ import annotations

from unittest.mock import patch

from autoagent.executors.agent_core.pc_device import PcDevice


def test_double_tap() -> None:
    with patch("autoagent.executors.agent_core.devices.pc.pyautogui.doubleClick") as mock_fn:
        PcDevice().double_tap(100, 200)
    mock_fn.assert_called_once_with(100, 200)


def test_long_press() -> None:
    with (
        patch("autoagent.executors.agent_core.devices.pc.pyautogui.mouseDown") as mock_down,
        patch("autoagent.executors.agent_core.devices.pc.pyautogui.mouseUp") as mock_up,
        patch("autoagent.executors.agent_core.devices.pc.time.sleep") as mock_sleep,
    ):
        PcDevice().long_press(100, 200, duration_ms=800)
    mock_down.assert_called_once_with(100, 200)
    mock_sleep.assert_called_once_with(0.8)
    mock_up.assert_called_once_with(100, 200)


def test_hotkey() -> None:
    with patch("autoagent.executors.agent_core.devices.pc.pyautogui.hotkey") as mock_fn:
        PcDevice().hotkey("ctrl", "c")
    mock_fn.assert_called_once_with("ctrl", "c")


def test_scroll_down() -> None:
    with patch("autoagent.executors.agent_core.devices.pc.pyautogui.scroll") as mock_scroll:
        PcDevice().scroll("down", 3)
    mock_scroll.assert_called_once_with(-900)


def test_scroll_up() -> None:
    with patch("autoagent.executors.agent_core.devices.pc.pyautogui.scroll") as mock_scroll:
        PcDevice().scroll("up", 2)
    mock_scroll.assert_called_once_with(600)
