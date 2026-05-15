from unittest.mock import MagicMock, patch

import pytest

from autoagent.devices.adb import AdbCommandError, get_screen_resolution, run_input_command


def test_get_screen_resolution_parses_portrait():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="Physical size: 1080x2400\n")
        w, h = get_screen_resolution("emulator-5554")
    assert w == 1080
    assert h == 2400


def test_get_screen_resolution_scales_to_720_width():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="Physical size: 1080x2400\n")
        w, h = get_screen_resolution("emulator-5554", target_width=720)
    assert w == 720
    assert h == 1600  # 2400 * 720 / 1080 = 1600


def test_get_screen_resolution_raises_on_bad_output():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="unexpected output\n")
        with pytest.raises(AdbCommandError):
            get_screen_resolution("emulator-5554")


def test_run_input_tap():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "tap", "x": 360, "y": 640})
    mock.assert_called_once_with("-s", "emulator-5554", "shell", "input", "tap", "360", "640")


def test_run_input_swipe():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command(
            "emulator-5554",
            {"type": "swipe", "x1": 100, "y1": 500, "x2": 100, "y2": 200, "duration_ms": 300},
        )
    mock.assert_called_once_with(
        "-s", "emulator-5554", "shell", "input", "swipe", "100", "500", "100", "200", "300"
    )


def test_run_input_key():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "key", "keycode": "KEYCODE_BACK"})
    mock.assert_called_once_with(
        "-s", "emulator-5554", "shell", "input", "keyevent", "KEYCODE_BACK"
    )


def test_run_input_text_escapes_spaces():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "text", "value": "hello world"})
    mock.assert_called_once_with("-s", "emulator-5554", "shell", "input", "text", "hello%sworld")


def test_run_input_text_escapes_special_chars():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "text", "value": "a&b|c"})
    args = mock.call_args[0]
    escaped = args[-1]
    assert "\\&" in escaped
    assert "\\|" in escaped


def test_run_input_rejects_invalid_type():
    with pytest.raises(AdbCommandError):
        run_input_command("emulator-5554", {"type": "unknown"})
