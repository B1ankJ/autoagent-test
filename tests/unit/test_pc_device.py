"""Unit tests for PcDevice with pyautogui mocked."""

from __future__ import annotations

from unittest.mock import patch

from autoagent.executors.agent_core.pc_device import PcDevice


def test_execute_action_double_click() -> None:
    with patch("autoagent.executors.agent_core.pc_device.pyautogui.doubleClick") as mock_fn:
        PcDevice().execute_action({"_type": "double_click", "x": 100, "y": 200})
    mock_fn.assert_called_once_with(100, 200)


def test_execute_action_long_press() -> None:
    with (
        patch("autoagent.executors.agent_core.pc_device.pyautogui.mouseDown") as mock_down,
        patch("autoagent.executors.agent_core.pc_device.pyautogui.mouseUp") as mock_up,
        patch("autoagent.executors.agent_core.pc_device.time.sleep") as mock_sleep,
    ):
        PcDevice().execute_action({"_type": "long_press", "x": 100, "y": 200, "duration_ms": 800})
    mock_down.assert_called_once_with(100, 200)
    mock_sleep.assert_called_once_with(0.8)
    mock_up.assert_called_once_with(100, 200)


def test_execute_action_hotkey() -> None:
    with patch("autoagent.executors.agent_core.pc_device.pyautogui.hotkey") as mock_fn:
        PcDevice().execute_action({"_type": "hotkey", "keys": ["ctrl", "c"]})
    mock_fn.assert_called_once_with("ctrl", "c")


def test_execute_action_wait() -> None:
    with patch("autoagent.executors.agent_core.pc_device.time.sleep") as mock_sleep:
        PcDevice().execute_action({"_type": "wait", "seconds": 1.5})
    mock_sleep.assert_called_once_with(1.5)
