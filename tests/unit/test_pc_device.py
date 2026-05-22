"""Unit tests for PcDevice adapter methods with pyautogui mocked."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from autoagent.executors.agent_core.pc_device import PcDevice


def test_double_tap() -> None:
    mock_pg = MagicMock()
    with patch("autoagent.executors.agent_core.devices.pc._pyautogui", return_value=mock_pg):
        PcDevice().double_tap(100, 200)
    mock_pg.doubleClick.assert_called_once_with(100, 200)


def test_long_press() -> None:
    mock_pg = MagicMock()
    with (
        patch("autoagent.executors.agent_core.devices.pc._pyautogui", return_value=mock_pg),
        patch("autoagent.executors.agent_core.devices.pc.time.sleep") as mock_sleep,
    ):
        PcDevice().long_press(100, 200, duration_ms=800)
    mock_pg.mouseDown.assert_called_once_with(100, 200)
    mock_sleep.assert_called_once_with(0.8)
    mock_pg.mouseUp.assert_called_once_with(100, 200)


def test_hotkey() -> None:
    mock_pg = MagicMock()
    with patch("autoagent.executors.agent_core.devices.pc._pyautogui", return_value=mock_pg):
        PcDevice().hotkey("ctrl", "c")
    mock_pg.hotkey.assert_called_once_with("ctrl", "c")


def test_type_text_uses_clipboard_paste_shortcut() -> None:
    mock_pg = MagicMock()
    mock_pc = MagicMock()
    with (
        patch("autoagent.executors.agent_core.devices.pc._pyautogui", return_value=mock_pg),
        patch("autoagent.executors.agent_core.devices.pc._pyperclip", return_value=mock_pc),
        patch("autoagent.executors.agent_core.devices.pc.time.sleep") as mock_sleep,
        patch.object(sys, "platform", "darwin"),
    ):
        PcDevice().type_text("你好")
    mock_pc.copy.assert_called_once_with("你好")
    mock_pg.hotkey.assert_called_once_with("command", "v")
    mock_sleep.assert_called_once_with(0.1)


def test_scroll_down() -> None:
    mock_pg = MagicMock()
    with patch("autoagent.executors.agent_core.devices.pc._pyautogui", return_value=mock_pg):
        PcDevice().scroll("down", 3)
    mock_pg.scroll.assert_called_once_with(-900)


def test_scroll_up() -> None:
    mock_pg = MagicMock()
    with patch("autoagent.executors.agent_core.devices.pc._pyautogui", return_value=mock_pg):
        PcDevice().scroll("up", 2)
    mock_pg.scroll.assert_called_once_with(600)
