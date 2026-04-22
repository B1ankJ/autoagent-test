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
