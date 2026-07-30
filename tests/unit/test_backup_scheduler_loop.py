"""run_backup_loop must survive a config-read failure and keep ticking.

Regression: the second _current_backup_config() call (used only to size the
next sleep) sat outside the try/except wrapping _backup_tick_once() — an
exception there killed the loop's task permanently, unlike run_retention_loop
whose equivalent config read is always inside its own guarded tick.
"""
from __future__ import annotations

import asyncio

from autoagent.maintenance import scheduler


async def test_run_backup_loop_survives_a_config_read_failure(monkeypatch):
    monkeypatch.setattr(scheduler, "_BACKUP_STARTUP_DELAY_SEC", 0.0)

    tick_calls = 0

    async def _fake_tick_once() -> None:
        nonlocal tick_calls
        tick_calls += 1

    config_calls = 0

    async def _fake_config() -> tuple[int, int]:
        nonlocal config_calls
        config_calls += 1
        if config_calls == 1:
            raise RuntimeError("transient db error")
        return 14, 24

    sleep_calls = 0
    real_sleep = asyncio.sleep

    async def _fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        # Call 1 is the loop's own startup delay (patched to 0 above but
        # still goes through this same mocked asyncio.sleep) — let it and
        # the first two tick-interval sleeps through, then stop the loop.
        if sleep_calls >= 3:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(scheduler, "_backup_tick_once", _fake_tick_once)
    monkeypatch.setattr(scheduler, "_current_backup_config", _fake_config)
    monkeypatch.setattr(scheduler.asyncio, "sleep", _fake_sleep)

    # run_backup_loop returns cleanly on CancelledError from its own sleep —
    # if the config-read failure instead propagated out unhandled, this
    # await would raise and fail the test.
    await scheduler.run_backup_loop()

    # Ticked (and thus reached the second sleep) despite the first
    # _current_backup_config() call raising — proof the loop kept going.
    assert tick_calls == 2
    assert sleep_calls == 3
