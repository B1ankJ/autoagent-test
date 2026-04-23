from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoagent.executors.complete_detector import capture_screenshot_bytes


@dataclass
class CapturedState:
    step: str
    package: str
    activity: str | None
    xml_path: Path
    screenshot_path: Path


async def capture_android_state(device: Any, session_dir: Path, step: str) -> CapturedState:
    session_dir.mkdir(parents=True, exist_ok=True)
    xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
    current = await asyncio.to_thread(device.app_current)
    screenshot = await asyncio.to_thread(capture_screenshot_bytes, device)

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
