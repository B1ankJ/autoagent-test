"""Periodic `git fetch` so /system/update/status reflects the remote without
hitting the network on each request.

The fetch updates git's own origin/main tracking ref; the status endpoint then
reads that ref with do_fetch=False. Only runs when self-update is enabled, so a
box that never opts in makes no outbound git calls. Mirrors the retention loop.
"""

from __future__ import annotations

import asyncio
import logging

from autoagent.models.api import DefaultsConfig
from autoagent.storage.configs import get_config
from autoagent.system import updater

_log = logging.getLogger(__name__)

_STARTUP_DELAY_SEC = 120.0  # 2 min after boot
_INTERVAL_SEC = 3600.0  # hourly


async def _enabled() -> bool:
    v = await get_config("defaults")
    cfg = DefaultsConfig.model_validate(v) if v else DefaultsConfig()
    return cfg.self_update_enabled


async def _tick_once() -> None:
    if not await _enabled():
        return
    status = await asyncio.to_thread(updater.check_for_update, enabled=True, do_fetch=True)
    if not status.fetch_ok:
        _log.warning("update fetch failed: %s", status.error)
    elif not status.up_to_date:
        _log.info(
            "update available: local=%s remote=%s (behind %d)",
            status.current_short,
            status.remote_short,
            status.behind,
        )


async def run_update_fetch_loop() -> None:
    """Long-running task: initial delay, then fetch every hour."""
    try:
        await asyncio.sleep(_STARTUP_DELAY_SEC)
    except asyncio.CancelledError:
        return
    while True:
        try:
            await _tick_once()
        except Exception:  # noqa: BLE001
            _log.exception("update fetch tick failed")
        try:
            await asyncio.sleep(_INTERVAL_SEC)
        except asyncio.CancelledError:
            return
