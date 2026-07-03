"""Run a profile's device-initialization playbook against one device.

Brings a device from any state into the profile's ready-to-chat state:
optionally reboot → wait for boot → launch app → run init_action steps.
Reuses the same AndroidActionRunner / AndroidInput machinery the executor
uses so init steps behave identically to runtime actions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import uiautomator2 as u2

from autoagent.devices import adb
from autoagent.devices.expected_state import clear_expected_reboot, mark_expected_reboot
from autoagent.executors.android_action_runner import AndroidActionRunner
from autoagent.executors.android_input import AndroidInput
from autoagent.executors.complete_detector import ensure_screen_awake
from autoagent.profiles.schemas import AndroidProfile

_log = logging.getLogger(__name__)


@dataclass
class InitResult:
    serial: str
    ok: bool
    rebooted: bool = False
    steps_run: int = 0
    duration_ms: int = 0
    error: str | None = None
    action_log: list[dict[str, Any]] = field(default_factory=list)


async def initialize_device(
    serial: str, profile: AndroidProfile, *, reboot_override: bool | None = None
) -> InitResult:
    """Execute profile.init_action (optionally after a reboot) on `serial`.

    `reboot_override` lets a caller force reboot on/off for this run without
    editing the profile; None falls back to profile.init_reboot.
    """
    started = time.monotonic()
    action_log: list[dict[str, Any]] = []
    rebooted = False
    do_reboot = profile.init_reboot if reboot_override is None else reboot_override

    try:
        if do_reboot:
            _log.info("init: rebooting %s", serial)
            # Tell the device monitor this offline is expected, so its
            # DingTalk alert reads "初始化重启" rather than a hardware fault.
            # Window = boot wait + margin for the settle + reconnect.
            mark_expected_reboot(serial, ttl_sec=profile.init_boot_wait_sec + 60.0)
            await asyncio.to_thread(adb.reboot, serial)
            rebooted = True
            booted = await asyncio.to_thread(
                adb.wait_for_boot,
                serial,
                timeout_sec=profile.init_boot_wait_sec,
            )
            if not booted:
                # Leave the expectation set: a device that never came back is
                # arguably a real problem, but during THIS window the monitor
                # already treated it as expected; the init job reports the
                # failure separately in the UI.
                return InitResult(
                    serial=serial,
                    ok=False,
                    rebooted=True,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error=f"device did not boot within {profile.init_boot_wait_sec:.0f}s",
                )
            # A freshly-booted device needs a moment before UI automation is
            # reliable even after boot_completed flips.
            await asyncio.sleep(5.0)
            # Device is back and reconnected — end the expectation early so a
            # genuine drop right after init still alerts normally.
            clear_expected_reboot(serial)

        await asyncio.to_thread(ensure_screen_awake, serial)
        device = await asyncio.to_thread(u2.connect, serial)
        await asyncio.to_thread(device.app_start, profile.package, profile.activity, False)
        if profile.init_launch_wait_sec > 0:
            await asyncio.sleep(profile.init_launch_wait_sec)

        steps_run = 0
        if profile.init_action:
            async with AndroidInput(device, profile.input_method) as input_ctl:
                runner = AndroidActionRunner(
                    device=device,
                    input_controller=input_ctl,
                    action_log=action_log,
                )
                await runner.run(profile.init_action)
                steps_run = len(profile.init_action)

        return InitResult(
            serial=serial,
            ok=True,
            rebooted=rebooted,
            steps_run=steps_run,
            duration_ms=int((time.monotonic() - started) * 1000),
            action_log=action_log,
        )
    except Exception as e:  # noqa: BLE001
        _log.exception("init failed for %s", serial)
        return InitResult(
            serial=serial,
            ok=False,
            rebooted=rebooted,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f"{type(e).__name__}: {e}",
            action_log=action_log,
        )
