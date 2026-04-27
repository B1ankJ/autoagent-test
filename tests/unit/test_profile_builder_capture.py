from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autoagent.executors.profile_builder_capture import capture_android_state


@pytest.mark.asyncio
async def test_capture_android_state_writes_expected_artifacts(tmp_path: Path):
    device = MagicMock()
    device.dump_hierarchy.return_value = "<hierarchy><node text='发消息'/></hierarchy>"
    device.app_current.return_value = {
        "package": "com.aliyun.tongyi",
        "activity": ".BrowserActivity",
    }
    device.screenshot.return_value = b"png-bytes"

    result = await capture_android_state(
        device=device,
        session_dir=tmp_path,
        step="idle",
    )

    assert result.package == "com.aliyun.tongyi"
    assert result.activity == ".BrowserActivity"
    assert (tmp_path / "capture_idle.xml").read_text(encoding="utf-8").startswith("<hierarchy>")
    assert (tmp_path / "capture_idle.png").read_bytes() == b"png-bytes"
    device.click.assert_not_called()
    device.press.assert_not_called()


@pytest.mark.asyncio
async def test_capture_android_state_restores_previous_ime_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    device = MagicMock()
    device.serial = "serial-1"
    device.dump_hierarchy.return_value = "<hierarchy><node text='发消息'/></hierarchy>"
    device.app_current.return_value = {
        "package": "com.aliyun.tongyi",
        "activity": ".BrowserActivity",
    }
    device.screenshot.return_value = b"png-bytes"

    events: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.set_ime",
        lambda serial, ime: events.append((serial, ime)),
    )

    await capture_android_state(
        device=device,
        session_dir=tmp_path,
        step="editing",
        enable_adb_keyboard=True,
    )

    assert events == [("serial-1", "com.example/.Ime")]


@pytest.mark.asyncio
async def test_capture_android_state_focuses_target_and_restores_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    device = MagicMock()
    device.serial = "serial-2"
    device.dump_hierarchy.return_value = (
        "<hierarchy><node class='android.widget.EditText'/></hierarchy>"
    )
    device.app_current.return_value = {
        "package": "com.aliyun.tongyi",
        "activity": ".BrowserActivity",
    }
    device.screenshot.return_value = b"editing-bytes"

    calls: list[tuple[str, tuple]] = []
    device.click.side_effect = lambda x, y: calls.append(("click", (x, y)))
    device.press.side_effect = lambda key: calls.append(("press", (key,)))

    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.set_ime",
        lambda _serial, _ime: None,
    )

    result = await capture_android_state(
        device=device,
        session_dir=tmp_path,
        step="editing",
        enable_adb_keyboard=True,
        focus_target=(480, 2090),
        focus_settle_sec=0.0,
    )

    assert result.step == "editing"
    # tap must happen before dump/screenshot; back must happen afterwards.
    assert calls[0] == ("click", (480, 2090))
    assert calls[-1] == ("press", ("back",))
    assert (tmp_path / "capture_editing.png").read_bytes() == b"editing-bytes"


@pytest.mark.asyncio
async def test_capture_android_state_presses_back_even_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    device = MagicMock()
    device.serial = "serial-3"
    device.dump_hierarchy.side_effect = RuntimeError("dump failed")
    device.app_current.return_value = {"package": "x", "activity": "y"}

    calls: list[str] = []
    device.click.side_effect = lambda *_: calls.append("click")
    device.press.side_effect = lambda *_: calls.append("press")

    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.ensure_adb_keyboard_ready",
        lambda _device: None,
    )
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.set_ime",
        lambda _serial, _ime: None,
    )

    with pytest.raises(RuntimeError):
        await capture_android_state(
            device=device,
            session_dir=tmp_path,
            step="editing",
            focus_target=(100, 200),
            focus_settle_sec=0.0,
        )

    assert calls == ["click", "press"]
