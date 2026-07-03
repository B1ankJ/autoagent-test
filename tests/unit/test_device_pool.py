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


@pytest.mark.asyncio
async def test_acquire_pool_picks_first_free_in_set() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b"), _device("c")])
    # Lock a, then acquire from pool {a, b}: b should win immediately.
    async with pool.acquire(preferred=None, timeout_sec=0.1, allowed_serials={"a"}):
        async with pool.acquire(
            preferred=None, timeout_sec=0.5, allowed_serials={"a", "b"}
        ) as serial:
            assert serial == "b"


@pytest.mark.asyncio
async def test_acquire_pool_raises_when_all_offline() -> None:
    pool = DevicePool(
        lambda: [_device("a", online=False), _device("b", online=False), _device("c")]
    )
    with pytest.raises(DeviceDisabled):
        async with pool.acquire(
            preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"}
        ):
            pass


@pytest.mark.asyncio
async def test_acquire_pool_raises_when_empty_intersection() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    with pytest.raises(DeviceDisabled):
        async with pool.acquire(
            preferred=None, timeout_sec=0.1, allowed_serials={"x", "y"}
        ):
            pass


@pytest.mark.asyncio
async def test_acquire_preferred_and_pool_merge() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b"), _device("c")])
    # Lock b, then acquire preferred=c with pool={a}: c is in the merged set
    # ({a, c}) and unlocked, so it wins.
    async with pool.acquire(preferred="b", timeout_sec=0.1):
        async with pool.acquire(
            preferred="c", timeout_sec=0.1, allowed_serials={"a"}
        ) as serial:
            assert serial in {"a", "c"}


@pytest.mark.asyncio
async def test_hold_blocks_acquire_of_same_device() -> None:
    pool = DevicePool(lambda: [_device("a")])
    async with pool.hold("a"):
        # The only device is held by init → acquire can't pick it up.
        with pytest.raises(DeviceBusy):
            async with pool.acquire(preferred="a", timeout_sec=0.2):
                pass


@pytest.mark.asyncio
async def test_hold_fails_fast_when_device_running_sample() -> None:
    pool = DevicePool(lambda: [_device("a")])
    async with pool.acquire(preferred="a", timeout_sec=0.1):
        # Device is running a sample → init hold times out → DeviceBusy.
        with pytest.raises(DeviceBusy):
            async with pool.hold("a", timeout_sec=0.2):
                pass


@pytest.mark.asyncio
async def test_hold_releases_for_next_user() -> None:
    pool = DevicePool(lambda: [_device("a")])
    async with pool.hold("a"):
        pass
    # After hold releases, acquire works again.
    async with pool.acquire(preferred="a", timeout_sec=0.2) as serial:
        assert serial == "a"
