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


# ── session_id / new_session: multi-turn device stickiness ──────────────────


@pytest.mark.asyncio
async def test_session_omitted_is_unaffected_by_session_machinery() -> None:
    # Same assertion as test_acquire_pool_picks_first_free_in_set, just
    # confirming the new (unused) params don't change anything.
    pool = DevicePool(lambda: [_device("a"), _device("b"), _device("c")])
    async with pool.acquire(preferred=None, timeout_sec=0.1, allowed_serials={"a"}):
        async with pool.acquire(
            preferred=None, timeout_sec=0.5, allowed_serials={"a", "b"}
        ) as serial:
            assert serial == "b"


@pytest.mark.asyncio
async def test_new_session_pins_whichever_device_it_lands_on() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=True,
    ) as serial:
        pinned = serial

    # A continuation must land on that exact device, even though both are
    # free and "a" would otherwise be picked first (list order).
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=False,
    ) as serial:
        assert serial == pinned


@pytest.mark.asyncio
async def test_continuation_waits_for_pinned_device_instead_of_picking_another() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=True,
    ) as pinned:
        # While the pinned device is still held, a continuation must wait
        # for it rather than opportunistically grabbing the other free one.
        with pytest.raises(DeviceBusy):
            async with pool.acquire(
                preferred=None, timeout_sec=0.2, allowed_serials={"a", "b"},
                session_id="conv-1", new_session=False,
            ):
                pass
    assert pinned in {"a", "b"}


@pytest.mark.asyncio
async def test_continuation_raises_when_pinned_device_goes_offline() -> None:
    devices = [_device("a"), _device("b")]
    pool = DevicePool(lambda: devices)
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=True,
    ) as pinned:
        pass
    idx = 0 if pinned == "a" else 1
    devices[idx] = _device(pinned, online=False)

    # The *other* device is free, but a continuation must not silently
    # substitute it — that would silently break conversation continuity.
    with pytest.raises(DeviceDisabled):
        async with pool.acquire(
            preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
            session_id="conv-1", new_session=False,
        ):
            pass


@pytest.mark.asyncio
async def test_continuation_without_a_pin_falls_back_to_normal_selection() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    # No prior new_session=True call for this session_id — self-heals.
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-never-started", new_session=False,
    ) as serial:
        assert serial == "a"


@pytest.mark.asyncio
async def test_new_session_does_not_steal_a_device_reserved_by_another_session() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=True,
    ) as reserved:
        # conv-1's device is free right now (not locked between turns) but
        # reserved; a different session starting fresh must skip it.
        async with pool.acquire(
            preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
            session_id="conv-2", new_session=True,
        ) as other:
            assert other != reserved


@pytest.mark.asyncio
async def test_non_session_acquire_ignores_other_sessions_reservations() -> None:
    # The strict backward-compat contract: a caller not using session_id at
    # all must see exactly today's behavior, including being free to grab
    # a device some other session has reserved (between that session's
    # turns the device isn't locked, and this caller never opted in to the
    # reservation system). "a" is deterministically what conv-1 reserves
    # (first free in list order) and is what a plain acquire would also
    # pick first — proving the reservation was ignored, not just that some
    # device came back.
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=True,
    ) as reserved:
        assert reserved == "a"
    # Outside the `with` now: "a" is unlocked again, but conv-1's
    # reservation (recorded by _remember_pin) isn't released or expired.
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
    ) as serial:
        assert serial == "a"


@pytest.mark.asyncio
async def test_release_session_frees_the_pin() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=True,
    ):
        pass

    assert pool.release_session("conv-1") is True
    assert pool.release_session("conv-1") is False  # already gone, not an error

    # No pin left — falls back to normal selection instead of forcing the
    # (now-unpinned) old device.
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=False,
    ) as serial:
        assert serial == "a"


@pytest.mark.asyncio
async def test_session_pin_expires_after_ttl(monkeypatch) -> None:
    import autoagent.devices.pool as pool_mod

    t = [1000.0]
    monkeypatch.setattr(pool_mod.time, "monotonic", lambda: t[0])
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    # First free-in-order pick is deterministically "a".
    async with pool.acquire(
        preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
        session_id="conv-1", new_session=True,
    ) as pinned:
        assert pinned == "a"

    t[0] += pool_mod._SESSION_TTL_SEC + 1

    # Hold "a" so that if the (expired) pin were wrongly still forced, this
    # continuation would have to wait/time out for it instead of getting
    # "b" immediately.
    async with pool.acquire(preferred="a", timeout_sec=0.1):
        async with pool.acquire(
            preferred=None, timeout_sec=0.1, allowed_serials={"a", "b"},
            session_id="conv-1", new_session=False,
        ) as serial:
            assert serial == "b"


@pytest.mark.asyncio
async def test_session_pins_bounded_evicts_oldest(monkeypatch) -> None:
    import autoagent.devices.pool as pool_mod

    monkeypatch.setattr(pool_mod, "_MAX_SESSIONS", 3)
    pool = DevicePool(lambda: [_device("a")])
    for i in range(4):
        async with pool.acquire(
            preferred=None, timeout_sec=0.1, allowed_serials={"a"},
            session_id=f"conv-{i}", new_session=True,
        ):
            pass

    assert pool._lookup_pin("conv-0") is None
    assert pool._lookup_pin("conv-3") == "a"
