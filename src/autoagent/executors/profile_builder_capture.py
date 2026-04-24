from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoagent.devices.adb import set_ime
from autoagent.executors.android_input import ensure_adb_keyboard_ready
from autoagent.executors.complete_detector import capture_screenshot_bytes

FocusTarget = tuple[int, int]


@dataclass
class CapturedState:
    step: str
    package: str
    activity: str | None
    xml_path: Path
    screenshot_path: Path


async def capture_android_state(
    device: Any,
    session_dir: Path,
    step: str,
    *,
    enable_adb_keyboard: bool = False,
    focus_target: FocusTarget | None = None,
    focus_settle_sec: float = 0.4,
    restore_focus: bool = True,
) -> CapturedState:
    session_dir.mkdir(parents=True, exist_ok=True)
    previous_ime: str | None = None
    focused = False
    try:
        if enable_adb_keyboard:
            previous_ime = await asyncio.to_thread(ensure_adb_keyboard_ready, device)
        if focus_target is not None:
            x, y = focus_target
            await asyncio.to_thread(device.click, x, y)
            focused = True
            if focus_settle_sec > 0:
                await asyncio.sleep(focus_settle_sec)
        xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
        current = await asyncio.to_thread(device.app_current)
        screenshot = await asyncio.to_thread(capture_screenshot_bytes, device)
    finally:
        if focused and restore_focus:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(device.press, "back")
        if enable_adb_keyboard and previous_ime:
            await asyncio.to_thread(set_ime, device.serial, previous_ime)

    xml_path = session_dir / f"capture_{step}.xml"
    screenshot_path = session_dir / f"capture_{step}.png"
    await asyncio.to_thread(xml_path.write_text, xml, encoding="utf-8")
    await asyncio.to_thread(screenshot_path.write_bytes, screenshot)

    return CapturedState(
        step=step,
        package=current.get("package", ""),
        activity=current.get("activity"),
        xml_path=xml_path,
        screenshot_path=screenshot_path,
    )
