from __future__ import annotations

from typing import Any

from autoagent.devices.adb import list_devices as adb_list_devices
from autoagent.devices.monitor import DeviceMonitor
from autoagent.devices.pool import DevicePool
from autoagent.executors.agent_android_executor import AgentAndroidExecutor
from autoagent.executors.agent_pc_executor import AgentPcExecutor
from autoagent.executors.android_executor import AndroidExecutor
from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.base import Executor
from autoagent.executors.web_executor import WebExecutor
from autoagent.profiles.registry import load_profile
from autoagent.scheduler.batch_scheduler import BatchScheduler
from autoagent.storage.devices import (
    list_devices as list_stored_devices,
)
from autoagent.storage.devices import (
    mark_missing_devices_offline,
    upsert_discovered_device,
)

_scheduler: BatchScheduler | None = None
_device_pool: DevicePool | None = None
_device_monitor: DeviceMonitor | None = None
_executors: dict[str, Executor] = {}


def _build_executor(mode: str) -> Executor:
    if mode not in _executors:
        if mode == "api":
            _executors[mode] = ApiExecutor()
        elif mode == "gui_pc_web":
            _executors[mode] = WebExecutor()
        elif mode == "gui_android":
            _executors[mode] = AndroidExecutor()
        elif mode == "agent_pc":
            _executors[mode] = AgentPcExecutor()
        elif mode == "agent_android":
            _executors[mode] = AgentAndroidExecutor()
        else:
            raise ValueError(f"mode {mode} not supported in this build")
    return _executors[mode]


def _lookup_profile(name: str) -> Any:
    p = load_profile(name)
    if p is None:
        raise LookupError(f"profile {name!r} not found")
    return p


def get_scheduler() -> BatchScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BatchScheduler(
            executor_factory=_build_executor,
            profile_lookup=_lookup_profile,
            device_pool=get_device_pool(),
        )
    return _scheduler


def get_device_pool() -> DevicePool:
    global _device_pool
    if _device_pool is None:
        _device_pool = DevicePool()
    return _device_pool


def get_device_monitor() -> DeviceMonitor:
    global _device_monitor
    if _device_monitor is None:
        pool = get_device_pool()

        async def _refresh_pool() -> None:
            pool.update_snapshot(await list_stored_devices())

        async def _upsert_and_refresh(
            *,
            serial: str,
            model: str | None,
            android_version: str | None,
            adb_keyboard_installed: bool | None,
            adb_keyboard_enabled: bool | None,
            online: bool,
            seen_at,
        ) -> None:
            await upsert_discovered_device(
                serial=serial,
                model=model,
                android_version=android_version,
                adb_keyboard_installed=adb_keyboard_installed,
                adb_keyboard_enabled=adb_keyboard_enabled,
                online=online,
                seen_at=seen_at,
            )
            await _refresh_pool()

        async def _mark_missing_and_refresh(seen_serials: set[str]) -> None:
            await mark_missing_devices_offline(seen_serials)
            await _refresh_pool()

        from autoagent.notifications.device_state import on_device_state_change

        _device_monitor = DeviceMonitor(
            list_devices=adb_list_devices,
            upsert_device=_upsert_and_refresh,
            mark_missing_offline=_mark_missing_and_refresh,
            on_state_change=on_device_state_change,
        )
    return _device_monitor


def reset_scheduler_for_tests() -> None:
    global _scheduler, _device_pool, _device_monitor
    _scheduler = None
    _device_pool = None
    _device_monitor = None
    _executors.clear()
