from dataclasses import dataclass

import pytest

from autoagent.devices.healer import DeviceHealer


@dataclass
class _Dev:
    serial: str
    online: bool
    enabled: bool = True


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _healer(devs, *, enabled=True, is_locked=lambda s: False, clock=None):
    connected: list[str] = []
    clock = clock or _Clock()

    async def list_devices():
        return devs

    async def is_enabled():
        return enabled

    healer = DeviceHealer(
        list_devices=list_devices,
        is_locked=is_locked,
        is_enabled=is_enabled,
        connect=lambda s: connected.append(s),
        clock=clock,
    )
    return healer, connected, clock


@pytest.mark.asyncio
async def test_reconnects_offline_network_device_with_backoff():
    devs = [_Dev("10.0.0.5:5555", online=False)]
    healer, connected, clock = _healer(devs)
    await healer.maybe_heal()
    assert connected == ["10.0.0.5:5555"]
    clock.t += 5
    await healer.maybe_heal()
    assert connected == ["10.0.0.5:5555"]
    clock.t += 30
    await healer.maybe_heal()
    assert connected == ["10.0.0.5:5555", "10.0.0.5:5555"]


@pytest.mark.asyncio
async def test_online_resets_backoff():
    dev = _Dev("10.0.0.5:5555", online=False)
    healer, connected, clock = _healer([dev])
    await healer.maybe_heal()
    assert len(connected) == 1
    dev.online = True
    await healer.maybe_heal()
    dev.online = False
    await healer.maybe_heal()
    assert len(connected) == 2


@pytest.mark.asyncio
async def test_skips_usb_disabled_and_online():
    devs = [
        _Dev("emulator-5554", online=False),
        _Dev("10.0.0.6:5555", online=False, enabled=False),
        _Dev("10.0.0.7:5555", online=True),
    ]
    healer, connected, _ = _healer(devs)
    await healer.maybe_heal()
    assert connected == []


@pytest.mark.asyncio
async def test_skips_locked_and_respects_disabled_toggle():
    devs = [_Dev("10.0.0.8:5555", online=False)]
    healer, connected, _ = _healer(devs, is_locked=lambda s: True)
    await healer.maybe_heal()
    assert connected == []
    healer2, connected2, _ = _healer([_Dev("10.0.0.9:5555", online=False)], enabled=False)
    await healer2.maybe_heal()
    assert connected2 == []


@pytest.mark.asyncio
async def test_connect_exception_is_isolated():
    devs = [_Dev("10.0.0.10:5555", online=False), _Dev("10.0.0.11:5555", online=False)]
    calls: list[str] = []

    def boom(serial):
        calls.append(serial)
        if serial.endswith("10:5555"):
            raise RuntimeError("adb down")

    async def list_devices():
        return devs

    async def is_enabled():
        return True

    healer = DeviceHealer(
        list_devices=list_devices,
        is_locked=lambda s: False,
        is_enabled=is_enabled,
        connect=boom,
        clock=_Clock(),
    )
    await healer.maybe_heal()
    assert set(calls) == {"10.0.0.10:5555", "10.0.0.11:5555"}
