"""Periodic runtime-cleanup task started from the FastAPI lifespan.

Runs once every 24 hours (first execution ~10 minutes after startup so
the app has settled). Reads log_retention_days from the DefaultsConfig
kv on each tick — no restart required to change retention.
"""
from __future__ import annotations

import asyncio
import logging

from autoagent.config.settings import get_settings
from autoagent.maintenance.batch_retention import prune_old_batches
from autoagent.maintenance.cleanup import run_cleanup
from autoagent.models.api import DefaultsConfig
from autoagent.storage.configs import get_config

_log = logging.getLogger(__name__)

_STARTUP_DELAY_SEC = 600.0  # 10 min
_INTERVAL_SEC = 24 * 3600.0


async def _current_days() -> int:
    v = await get_config("defaults")
    cfg = DefaultsConfig.model_validate(v) if v else DefaultsConfig()
    return cfg.log_retention_days


async def _tick_once() -> None:
    days = await _current_days()
    if days <= 0:
        _log.info("log_retention_days=%d, skipping cleanup tick", days)
        return
    settings = get_settings()
    # Prune whole finished batches (DB rows + results + logs dir) first so the
    # file sweep below doesn't have to re-walk their logs.
    batch_report = await prune_old_batches(
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=days,
        dry_run=False,
    )
    report = await asyncio.to_thread(
        run_cleanup,
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=days,
        dry_run=False,
    )
    _log.info(
        "retention tick: retention=%dd pruned batches=%d; files=%d dirs=%d bytes=%d",
        days,
        batch_report.batches,
        report.files_deleted,
        report.dirs_deleted,
        report.bytes_freed,
    )


async def run_retention_loop() -> None:
    """Long-running task: initial delay, then tick every 24h."""
    try:
        await asyncio.sleep(_STARTUP_DELAY_SEC)
    except asyncio.CancelledError:
        return
    while True:
        try:
            await _tick_once()
        except Exception:  # noqa: BLE001
            _log.exception("log retention tick failed")
        try:
            await asyncio.sleep(_INTERVAL_SEC)
        except asyncio.CancelledError:
            return
