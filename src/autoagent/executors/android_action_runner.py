from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from autoagent.executors.android_locator import resolve_target
from autoagent.profiles.schemas import ActionStep


class AndroidActionRunner:
    def __init__(
        self,
        *,
        device: Any,
        input_controller: Any,
        action_log: list[dict[str, Any]],
        replay_path: Path | None = None,
    ) -> None:
        self.device = device
        self.input_controller = input_controller
        self.log = action_log
        self._replay_path = replay_path
        self._t0 = time.monotonic()

    async def run(self, steps: list[ActionStep]) -> None:
        for step in steps:
            entry = {"t_ms": int((time.monotonic() - self._t0) * 1000), "action": step.action}
            self._annotate_entry(entry, step)
            try:
                await self._dispatch(step)
                entry["ok"] = True
            except Exception as e:  # noqa: BLE001
                entry["ok"] = False
                entry["error"] = f"{type(e).__name__}: {e}"
                self.log.append(entry)
                self._write_replay(entry)
                raise
            self.log.append(entry)
            self._write_replay(entry)

    def _annotate_entry(self, entry: dict[str, Any], step: ActionStep) -> None:
        locator = getattr(step, "locator", None)
        if locator is not None:
            if hasattr(locator, "model_dump"):
                entry["locator"] = locator.model_dump(mode="json")
            else:
                entry["locator"] = dict(locator)
        if step.action == "tap_xy":
            entry["x"] = step.x
            entry["y"] = step.y
        elif step.action == "swipe":
            entry["x1"] = step.x1
            entry["y1"] = step.y1
            entry["x2"] = step.x2
            entry["y2"] = step.y2
        elif step.action == "press_key":
            entry["key"] = step.key
        elif step.action in {"launch_app", "kill_app"}:
            entry["package"] = step.package
            if getattr(step, "activity", None):
                entry["activity"] = step.activity
        elif step.action == "input" and getattr(step, "text", None) is not None:
            entry["text_length"] = len(step.text or "")

    async def _dispatch(self, step: ActionStep) -> None:
        if step.action == "click_locator":
            resolve_target(self.device, step.locator).click()
        elif step.action == "input":
            await self.input_controller.set_text(step.locator, step.text)
        elif step.action == "wait_for":
            await asyncio.to_thread(
                resolve_target(self.device, step.locator).wait,
                timeout=getattr(step, "timeout_sec", 5),
            )
        elif step.action == "launch_app":
            await asyncio.to_thread(
                self.device.app_start,
                step.package,
                getattr(step, "activity", None),
                True,
            )
        elif step.action == "kill_app":
            await asyncio.to_thread(self.device.app_stop, step.package)
        elif step.action == "press_key":
            await asyncio.to_thread(self.device.press, step.key)
        elif step.action == "swipe":
            await asyncio.to_thread(
                self.device.swipe,
                step.x1,
                step.y1,
                step.x2,
                step.y2,
                getattr(step, "duration_sec", 0.1),
            )
        elif step.action == "tap_xy":
            await asyncio.to_thread(self.device.click, step.x, step.y)
        else:
            raise ValueError(f"unknown android action: {step.action}")

    def _write_replay(self, entry: dict[str, Any]) -> None:
        if self._replay_path is None:
            return
        self._replay_path.parent.mkdir(parents=True, exist_ok=True)
        with self._replay_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
