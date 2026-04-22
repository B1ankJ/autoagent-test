import asyncio

import pytest

from autoagent.devices.pool import DeviceBusy, DeviceDisabled, DevicePool
from autoagent.models.api import DeviceInfo


def _device(serial: str, *, online: bool = True, enabled: bool = True) -> DeviceInfo:
    return DeviceInfo(serial=serial, online=online, enabled=enabled)


@pytest.mark.asyncio
async def test_acquire_prefers_requested_serial() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    async with pool.acquire(preferred="b", timeout_sec=0.1) as serial:
        assert serial == "b"


@pytest.mark.asyncio
async def test_acquire_raises_when_device_disabled_mid_wait() -> None:
    devices = [_device("a", enabled=True)]
    pool = DevicePool(lambda: devices)

    async with pool.acquire(preferred="a", timeout_sec=0.1):

        async def waiter():
            async with pool.acquire(preferred="a", timeout_sec=0.2):
                return None

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        devices[0] = _device("a", enabled=False)
        with pytest.raises(DeviceDisabled):
            await task
