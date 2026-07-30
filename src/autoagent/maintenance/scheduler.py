"""Periodic runtime-cleanup task started from the FastAPI lifespan.

Runs once every 24 hours (first execution ~10 minutes after startup so
the app has settled). Reads log_retention_days from the DefaultsConfig
kv on each tick — no restart required to change retention.
"""
from __future__ import annotations

import asyncio
import logging

from autoagent.config.settings import get_settings
from autoagent.maintenance.backup import run_backup
from autoagent.maintenance.batch_retention import prune_old_batches
from autoagent.maintenance.cleanup import run_cleanup
from autoagent.models.api import DefaultsConfig
from autoagent.storage.configs import get_config

_log = logging.getLogger(__name__)

_STARTUP_DELAY_SEC = 600.0  # 10 min
_INTERVAL_SEC = 24 * 3600.0
_BACKUP_STARTUP_DELAY_SEC = 300.0  # 5 min — sooner, and independent of the retention loop


async def _current_days() -> tuple[int, int]:
    v = await get_config("defaults")
    cfg = DefaultsConfig.model_validate(v) if v else DefaultsConfig()
    return cfg.log_retention_days, cfg.archive_retention_days


async def _tick_once() -> None:
    days, archive_days = await _current_days()
    settings = get_settings()
    # Prune whole finished batches (DB rows + results + logs dir) first so the
    # file sweep below doesn't have to re-walk their logs. Also prunes old
    # archives even when log_retention_days is 0.
    batch_report = await prune_old_batches(
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=days,
        archive_retention_days=archive_days,
        dry_run=False,
    )
    if days <= 0:
        _log.info(
            "log_retention_days=0; archives pruned=%d", batch_report.archives_pruned
        )
        return
    report = await asyncio.to_thread(
        run_cleanup,
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=days,
        dry_run=False,
    )
    _log.info(
        "retention tick: retention=%dd pruned batches=%d archived=%d archives_pruned=%d; "
        "files=%d dirs=%d bytes=%d",
        days,
        batch_report.batches,
        batch_report.archived,
        batch_report.archives_pruned,
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


async def _current_backup_config() -> tuple[int, int]:
    v = await get_config("defaults")
    cfg = DefaultsConfig.model_validate(v) if v else DefaultsConfig()
    return cfg.backup_retention_days, cfg.backup_interval_hours


async def _backup_tick_once() -> None:
    retention_days, _interval_hours = await _current_backup_config()
    if retention_days <= 0:
        return
    settings = get_settings()
    report = await run_backup(data_root=settings.data_root, retention_days=retention_days)
    _log.info(
        "backup tick: wrote=%s bytes=%d pruned=%d",
        report.path,
        report.bytes_written,
        report.pruned,
    )


async def run_backup_loop() -> None:
    """Long-running task: initial delay, then tick every backup_interval_hours.

    Reads backup_retention_days/backup_interval_hours from DefaultsConfig on
    each tick, same as the retention loop — no restart needed to change
    either.
    """
    try:
        await asyncio.sleep(_BACKUP_STARTUP_DELAY_SEC)
    except asyncio.CancelledError:
        return
    while True:
        # interval_hours defaults here so a config-read failure (e.g. a
        # transient DB error) doesn't leave it unbound — this second read
        # used to sit outside the try/except below entirely, so raising
        # here killed the loop's task permanently (no more ticks until a
        # process restart), unlike run_retention_loop's equivalent read,
        # which was always inside its own guarded tick.
        interval_hours = 24
        try:
            await _backup_tick_once()
            _, interval_hours = await _current_backup_config()
        except Exception:  # noqa: BLE001
            _log.exception("backup tick failed")
        try:
            await asyncio.sleep(max(interval_hours, 1) * 3600.0)
        except asyncio.CancelledError:
            return
