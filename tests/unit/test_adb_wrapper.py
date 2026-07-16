from unittest.mock import MagicMock

import pytest

from autoagent.devices.adb import AdbCommandError, list_devices


def test_list_devices_parses_adb_devices_l(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = (
        "List of devices attached\n"
        "emulator-5554 device product:sdk model:sdk_gphone64_arm64 device:emu transport_id:1\n"
        "R3CN30 offline usb:1-1 transport_id:2\n"
    )
    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", lambda *a, **k: proc)

    rows = list_devices()

    assert len(rows) == 2
    assert rows[0].serial == "emulator-5554"
    assert rows[0].online is True
    assert rows[0].model == "sdk_gphone64_arm64"
    assert rows[1].serial == "R3CN30"
    assert rows[1].online is False


def test_list_devices_raises_on_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock(returncode=1, stdout="", stderr="adb missing")
    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", lambda *a, **k: proc)
    with pytest.raises(AdbCommandError):
        list_devices()


def test_list_devices_detects_adb_keyboard_state(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, **_kwargs):
        cmd = tuple(args)
        if cmd == ("adb", "devices", "-l"):
            return MagicMock(
                returncode=0,
                stdout=(
                    "List of devices attached\n"
                    "emulator-5554 device product:sdk model:sdk_gphone64_arm64 device:emu "
                    "transport_id:1\n"
                ),
                stderr="",
            )
        if cmd == ("adb", "-s", "emulator-5554", "shell", "pm", "list", "packages"):
            return MagicMock(
                returncode=0,
                stdout="package:com.android.adbkeyboard\n",
                stderr="",
            )
        if cmd == ("adb", "-s", "emulator-5554", "shell", "ime", "list", "-s"):
            return MagicMock(
                returncode=0,
                stdout="com.android.adbkeyboard/.AdbIME\n",
                stderr="",
            )
        if cmd == (
            "adb",
            "-s",
            "emulator-5554",
            "shell",
            "getprop",
            "ro.build.version.release",
        ):
            return MagicMock(returncode=0, stdout="14\n", stderr="")
        raise AssertionError(f"unexpected adb command: {cmd}")

    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", fake_run)

    rows = list_devices()

    assert rows[0].adb_keyboard_installed is True
    assert rows[0].adb_keyboard_enabled is True


def test_list_devices_reads_android_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, **_kwargs):
        cmd = tuple(args)
        if cmd == ("adb", "devices", "-l"):
            return MagicMock(
                returncode=0,
                stdout=(
                    "List of devices attached\n"
                    "emulator-5554 device product:sdk model:sdk_gphone64_arm64 device:emu "
                    "transport_id:1\n"
                ),
                stderr="",
            )
        if cmd == (
            "adb",
            "-s",
            "emulator-5554",
            "shell",
            "getprop",
            "ro.build.version.release",
        ):
            return MagicMock(returncode=0, stdout="14\n", stderr="")
        if cmd[-3:] in (("pm", "list", "packages"), ("ime", "list", "-s")):
            return MagicMock(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected adb command: {cmd}")

    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", fake_run)

    rows = list_devices()

    assert rows[0].android_version == "14"


def test_list_devices_leaves_android_version_none_when_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "List of devices attached\nR3CN30 offline usb:1-1 transport_id:2\n"
    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", lambda *a, **k: proc)

    rows = list_devices()

    assert rows[0].android_version is None


def test_list_devices_swallows_android_version_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args, **_kwargs):
        cmd = tuple(args)
        if cmd == ("adb", "devices", "-l"):
            return MagicMock(
                returncode=0,
                stdout=(
                    "List of devices attached\n"
                    "emulator-5554 device product:sdk model:sdk_gphone64_arm64 device:emu "
                    "transport_id:1\n"
                ),
                stderr="",
            )
        return MagicMock(returncode=1, stdout="", stderr="device offline")

    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", fake_run)

    rows = list_devices()

    assert rows[0].android_version is None
