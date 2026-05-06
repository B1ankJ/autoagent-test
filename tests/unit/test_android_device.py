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


def test_tap():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().tap(540, 960)
    mock_adb.assert_called_once_with(["shell", "input", "tap", "540", "960"])


def test_type_text():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().type_text("hello")
    mock_adb.assert_called_once_with(["shell", "input", "text", "hello"])


def test_type_text_non_ascii():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().type_text("你好")
    mock_adb.assert_called_once_with(
        ["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", "你好"]
    )


def test_press_key_back():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().press_key("back")
    mock_adb.assert_called_once_with(["shell", "input", "keyevent", "KEYCODE_BACK"])


def test_scroll_down():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().scroll("down", 3)
    mock_adb.assert_called_once_with(
        ["shell", "input", "swipe", "540", "1200", "540", "300", "300"]
    )


def test_scroll_up():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().scroll("up", 3)
    mock_adb.assert_called_once_with(
        ["shell", "input", "swipe", "540", "400", "540", "1300", "300"]
    )


def test_double_tap():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().double_tap(540, 960)
    assert mock_adb.call_count == 2
    mock_adb.assert_any_call(["shell", "input", "tap", "540", "960"])


def test_long_press():
    with patch.object(AndroidDevice, "_adb_run") as mock_adb:
        AndroidDevice().long_press(540, 960, duration_ms=800)
    mock_adb.assert_called_once_with(
        ["shell", "input", "swipe", "540", "960", "540", "960", "800"]
    )
