import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from autoagent.api.device_stream import (
    _DEFAULT_BITRATE_MBPS,
    _DEFAULT_WIDTH,
    _MAX_BITRATE_MBPS,
    _MAX_WIDTH,
    _MIN_BITRATE_MBPS,
    _MIN_WIDTH,
    _resolve_stream_params,
)
from autoagent.devices.adb import AdbCommandError, get_screen_resolution, run_input_command


def test_resolve_stream_params_defaults_when_omitted():
    assert _resolve_stream_params(None, None) == (_DEFAULT_WIDTH, _DEFAULT_BITRATE_MBPS)


def test_resolve_stream_params_passes_through_in_range():
    assert _resolve_stream_params(540, 4) == (540, 4)


def test_resolve_stream_params_clamps_out_of_range():
    assert _resolve_stream_params(99999, 99999) == (_MAX_WIDTH, _MAX_BITRATE_MBPS)
    assert _resolve_stream_params(1, 0) == (_MIN_WIDTH, _MIN_BITRATE_MBPS)


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


def test_run_input_tap_scales_normalized_coords_to_native_pixels():
    with (
        patch("autoagent.devices.adb._native_resolution", return_value=(1080, 1920)),
        patch("autoagent.devices.adb._run_adb") as mock,
    ):
        mock.return_value = MagicMock(stdout="")
        # 0.5 × 1080 = 540, 0.25 × 1920 = 480 — accurate regardless of the
        # video stream resolution the coords were captured against.
        run_input_command("emulator-5554", {"type": "tap", "nx": 0.5, "ny": 0.25})
    mock.assert_called_once_with("-s", "emulator-5554", "shell", "input", "tap", "540", "480")


def test_run_input_swipe_scales_normalized_coords_to_native_pixels():
    with (
        patch("autoagent.devices.adb._native_resolution", return_value=(1080, 1920)),
        patch("autoagent.devices.adb._run_adb") as mock,
    ):
        mock.return_value = MagicMock(stdout="")
        run_input_command(
            "emulator-5554",
            {"type": "swipe", "nx1": 0.1, "ny1": 0.5, "nx2": 0.1, "ny2": 0.2, "duration_ms": 300},
        )
    mock.assert_called_once_with(
        "-s", "emulator-5554", "shell", "input", "swipe", "108", "960", "108", "384", "300"
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


async def test_stream_kills_process_on_disconnect(monkeypatch):
    """WebSocket 断开时，screenrecord 子进程必须被终止。"""
    fake_proc = MagicMock()
    fake_proc.stdout = AsyncMock()
    fake_proc.stdout.read = AsyncMock(side_effect=[b"\x00\x00\x00\x01abc", b""])
    fake_proc.terminate = MagicMock()
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.returncode = None

    async def fake_create_subprocess(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess)

    from autoagent.api.device_stream import _stream_h264

    frames_sent = []

    class FakeWS:
        async def send_bytes(self, data):
            frames_sent.append(data)
            raise WebSocketDisconnect()

    with patch("autoagent.api.device_stream.get_screen_resolution", return_value=(720, 1600)):
        try:
            await _stream_h264(FakeWS(), "emulator-5554")
        except WebSocketDisconnect:
            pass

    fake_proc.terminate.assert_called_once()
    assert frames_sent


async def test_stream_sends_error_frame_on_immediate_exit(monkeypatch):
    """screenrecord 立即退出时，发送 JSON 错误帧后关闭连接。"""
    fake_proc = MagicMock()
    fake_proc.stdout = AsyncMock()
    fake_proc.stdout.read = AsyncMock(return_value=b"")  # 立即 EOF
    fake_proc.terminate = MagicMock()
    fake_proc.wait = AsyncMock(return_value=1)
    fake_proc.returncode = 1

    async def fake_create_subprocess(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess)

    from autoagent.api.device_stream import _stream_h264

    messages_sent = []

    class FakeWS:
        async def send_bytes(self, data):
            messages_sent.append(("bytes", data))

        async def send_text(self, data):
            messages_sent.append(("text", data))

        async def close(self):
            pass

    with patch("autoagent.api.device_stream.get_screen_resolution", return_value=(720, 1600)):
        await _stream_h264(FakeWS(), "emulator-5554")

    text_frames = [m for m in messages_sent if m[0] == "text"]
    assert any("error" in m[1] for m in text_frames)
