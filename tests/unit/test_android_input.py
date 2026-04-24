from unittest.mock import MagicMock

import pytest

from autoagent.executors.android_input import (
    ADB_KEYBOARD_IME,
    AndroidInput,
    resolve_input_method,
)
from autoagent.profiles.schemas import Locator


def test_auto_uses_adb_keyboard_for_non_ascii() -> None:
    assert resolve_input_method("auto", "你好") == "adb_keyboard"


def test_auto_prefers_adb_keyboard_for_ascii_when_available() -> None:
    assert resolve_input_method("auto", "hello", adb_keyboard_available=True) == "adb_keyboard"


def test_auto_falls_back_for_ascii_when_adb_keyboard_unavailable() -> None:
    assert resolve_input_method("auto", "hello", adb_keyboard_available=False) == "u2_send_keys"


@pytest.mark.asyncio
async def test_set_text_supports_xpath_locator() -> None:
    device = MagicMock()
    xpath_target = MagicMock()
    device.xpath.return_value = xpath_target
    device.serial = "serial-1"

    async with AndroidInput(device, "u2_send_keys") as ctl:
        await ctl.set_text(
            Locator(type="xpath", value='//node[@class="android.widget.EditText"]'),
            "hello",
        )

    device.xpath.assert_called_once_with('//node[@class="android.widget.EditText"]')
    xpath_target.click.assert_called_once()
    device.shell.assert_called_once_with(["input", "text", "hello"])


@pytest.mark.asyncio
async def test_set_text_escapes_shell_input_spaces() -> None:
    device = MagicMock()
    target = MagicMock()
    device.return_value = target
    device.serial = "serial-1"

    async with AndroidInput(device, "u2_send_keys") as ctl:
        await ctl.set_text(
            Locator(type="resource_id", value="demo:id/input"),
            "hello world",
        )

    target.click.assert_called_once()
    device.shell.assert_called_once_with(["input", "text", "hello%sworld"])


@pytest.mark.asyncio
async def test_set_text_adb_keyboard_switches_and_restores_ime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = MagicMock()
    target = MagicMock()
    device.return_value = target
    device.serial = "serial-1"

    events: list[str] = []

    def fake_ensure(_device):
        events.append("ensure")
        return "com.example/.Ime"

    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        fake_ensure,
    )
    restored: list[tuple[object, object]] = []
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: restored.append((_serial, _ime)),
    )
    target.click.side_effect = lambda *_, **__: events.append("click")
    device.shell.side_effect = lambda args: events.append(f"shell:{args[0]}")

    async with AndroidInput(device, "adb_keyboard") as ctl:
        await ctl.set_text(
            Locator(type="resource_id", value="demo:id/input"),
            "你好",
        )
        assert restored == []
        await ctl.restore_pending_ime()

    target.click.assert_called_once()
    device.shell.assert_any_call(
        [
            "am",
            "broadcast",
            "-a",
            "ADB_INPUT_B64",
            "--es",
            "msg",
            "5L2g5aW9",
        ]
    )
    assert restored == [(device.serial, "com.example/.Ime")]
    assert events == ["ensure", "click", "shell:am"]


@pytest.mark.asyncio
async def test_set_text_auto_prefers_adb_keyboard_for_ascii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = MagicMock()
    target = MagicMock()
    device.return_value = target
    device.serial = "serial-1"

    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: True,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    restored: list[tuple[object, object]] = []
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: restored.append((_serial, _ime)),
    )

    async with AndroidInput(device, "auto") as ctl:
        await ctl.set_text(
            Locator(type="resource_id", value="demo:id/input"),
            "hello",
        )
        await ctl.restore_pending_ime()

    device.shell.assert_called_once_with(
        [
            "am",
            "broadcast",
            "-a",
            "ADB_INPUT_B64",
            "--es",
            "msg",
            "aGVsbG8=",
        ]
    )
    assert restored == [(device.serial, "com.example/.Ime")]


@pytest.mark.asyncio
async def test_prepare_for_prompt_activates_adb_keyboard_once_and_restore_is_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = MagicMock()
    device.serial = "serial-1"

    calls: list[str] = []
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: calls.append("ensure") or "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: calls.append("restore"),
    )

    async with AndroidInput(device, "adb_keyboard") as ctl:
        assert await ctl.prepare_for_prompt("hello") == "adb_keyboard"
        assert await ctl.prepare_for_prompt("hello") == "adb_keyboard"
        assert calls == ["ensure"]
        await ctl.restore_pending_ime()

    assert calls == ["ensure", "restore"]


@pytest.mark.asyncio
async def test_set_text_adb_keyboard_broadcasts_when_refocus_locator_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = MagicMock()
    target = MagicMock()
    device.return_value = target
    device.serial = "serial-1"

    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: None,
    )
    target.click.side_effect = RuntimeError("input locator disappeared after focus")

    async with AndroidInput(device, "adb_keyboard") as ctl:
        await ctl.set_text(
            Locator(type="resource_id", value="demo:id/input"),
            "hello",
        )

    target.click.assert_called_once()
    device.shell.assert_called_once_with(
        [
            "am",
            "broadcast",
            "-a",
            "ADB_INPUT_B64",
            "--es",
            "msg",
            "aGVsbG8=",
        ]
    )


@pytest.mark.asyncio
async def test_set_text_auto_falls_back_to_shell_input_for_ascii_when_adb_keyboard_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = MagicMock()
    target = MagicMock()
    device.return_value = target
    device.serial = "serial-1"

    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )

    async with AndroidInput(device, "auto") as ctl:
        await ctl.set_text(
            Locator(type="resource_id", value="demo:id/input"),
            "hello",
        )

    target.click.assert_called_once()
    device.shell.assert_called_once_with(["input", "text", "hello"])


def test_ensure_adb_keyboard_ready_waits_until_ime_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autoagent.executors import android_input as mod

    states = iter(["com.example/.Ime", "com.example/.Ime", ADB_KEYBOARD_IME])
    monkeypatch.setattr(
        mod,
        "is_package_installed",
        lambda _serial, _package: True,
    )
    monkeypatch.setattr(
        mod,
        "get_current_ime",
        lambda _serial: next(states),
    )
    enabled: list[str] = []
    switched: list[str] = []
    monkeypatch.setattr(mod, "enable_ime", lambda _serial, ime: enabled.append(ime))
    monkeypatch.setattr(mod, "set_ime", lambda _serial, ime: switched.append(ime))
    sleeps: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda sec: sleeps.append(sec))

    previous = mod.ensure_adb_keyboard_ready(type("D", (), {"serial": "abc"})())

    assert previous == "com.example/.Ime"
    assert enabled == [ADB_KEYBOARD_IME]
    assert switched == [ADB_KEYBOARD_IME]
    assert sleeps == [0.1]
