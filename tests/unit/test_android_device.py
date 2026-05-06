"""Unit tests for AndroidDevice — no real adb connection needed."""

from __future__ import annotations

import base64
import struct
from unittest.mock import MagicMock, patch

from autoagent.executors.agent_core.android_device import AndroidDevice


def _make_png(w: int = 100, h: int = 200) -> bytes:
    """Build a minimal byte string with a valid PNG IHDR width/height."""
    header = b"\x89PNG\r\n\x1a\n"  # 8-byte PNG signature
    # IHDR chunk: 4-byte length, 4-byte type, 13-byte data
    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data
    return header + ihdr + b"\x00" * 100  # padding


def test_capture_returns_screenshot():
    png = _make_png(1080, 1920)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=png)
        mock_run.return_value.check_returncode = lambda: None
        device = AndroidDevice(serial="emulator-5554")
        shot = device.capture()

    assert shot.width == 1080
    assert shot.height == 1920
    assert shot.base64_data == base64.b64encode(png).decode()


def test_capture_uses_serial():
    png = _make_png()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=png)
        mock_run.return_value.check_returncode = lambda: None
        AndroidDevice(serial="test-serial").capture()

    cmd = mock_run.call_args[0][0]
    assert "-s" in cmd
    assert "test-serial" in cmd


def test_capture_no_serial():
    png = _make_png()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=png)
        mock_run.return_value.check_returncode = lambda: None
        AndroidDevice().capture()

    cmd = mock_run.call_args[0][0]
    assert "-s" not in cmd


def test_execute_action_click():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "click", "x": 540, "y": 960})
    mock_adb.assert_called_once_with(["shell", "input", "tap", "540", "960"])


def test_execute_action_type():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "type", "text": "hello"})
    mock_adb.assert_called_once_with(["shell", "input", "text", "hello"])


def test_execute_action_type_non_ascii():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "type", "text": "你好"})
    mock_adb.assert_called_once_with(
        ["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", "你好"]
    )


def test_execute_action_press_enter():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "press", "key": "enter"})
    mock_adb.assert_called_once_with(["shell", "input", "keyevent", "KEYCODE_ENTER"])


def test_execute_action_scroll_down():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "scroll", "direction": "down", "amount": 3})
    # amount=3, dist=900; swipe from y=1200 up to y=1200-900=300
    mock_adb.assert_called_once_with(
        ["shell", "input", "swipe", "540", "1200", "540", "300", "300"]
    )


def test_execute_action_scroll_up():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "scroll", "direction": "up", "amount": 3})
    # amount=3, dist=900; swipe from y=400 down to y=400+900=1300
    mock_adb.assert_called_once_with(
        ["shell", "input", "swipe", "540", "400", "540", "1300", "300"]
    )


def test_execute_action_double_click():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "double_click", "x": 540, "y": 960})
    assert mock_adb.call_count == 2
    mock_adb.assert_any_call(["shell", "input", "tap", "540", "960"])


def test_execute_action_long_press():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action(
            {"_type": "long_press", "x": 540, "y": 960, "duration_ms": 800}
        )
    mock_adb.assert_called_once_with(
        ["shell", "input", "swipe", "540", "960", "540", "960", "800"]
    )


def test_execute_action_wait():
    with patch("autoagent.executors.agent_core.android_device.time.sleep") as mock_sleep:
        AndroidDevice().execute_action({"_type": "wait", "seconds": 1.5})
    mock_sleep.assert_called_once_with(1.5)


def test_execute_action_finish_does_not_crash():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().execute_action({"_type": "finish", "message": "done"})
    mock_adb.assert_not_called()


def test_execute_action_unknown_logs_warning(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="autoagent.executors.agent_core.android_device"):
        with patch.object(AndroidDevice, "_adb_run"):
            AndroidDevice().execute_action({"_type": "noop"})
    assert "unknown action" in caplog.text
