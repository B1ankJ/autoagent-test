from __future__ import annotations

import time
from typing import Any

from autoagent.executors.agent_core.devices.pc import PcDeviceAdapter
from autoagent.executors.agent_core.result import ActionResult


class PcActionHandler:
    def __init__(self, device: PcDeviceAdapter) -> None:
        self._device = device

    def execute(
        self, action: dict[str, Any], screen_width: int, screen_height: int
    ) -> ActionResult:
        metadata = action.get("_metadata")
        if metadata == "finish":
            return ActionResult(True, True, str(action.get("message", "")))
        if metadata != "do":
            return ActionResult(False, False, f"Unknown action type: {metadata}")

        action_name = str(action.get("action", ""))
        try:
            if action_name == "Tap":
                x, y = _point(action.get("element"))
                self._device.tap(x, y)
            elif action_name == "Type":
                self._device.type_text(str(action.get("text", "")))
            elif action_name == "Swipe":
                start_x, start_y = _point(action.get("start"))
                end_x, end_y = _point(action.get("end"))
                self._device.swipe(start_x, start_y, end_x, end_y)
            elif action_name == "Scroll":
                self._device.scroll(str(action.get("direction", "down")).lower(), int(action.get("clicks", 3)))
            elif action_name == "Press":
                self._device.press_key(str(action.get("key", "enter")).lower())
            elif action_name == "Back":
                self._device.press_key("back")
            elif action_name == "Home":
                self._device.press_key("home")
            elif action_name == "Double Tap":
                x, y = _point(action.get("element"))
                self._device.double_tap(x, y)
            elif action_name == "Long Press":
                x, y = _point(action.get("element"))
                self._device.long_press(x, y, duration_ms=int(action.get("duration_ms", 800)))
            elif action_name == "Hotkey":
                keys = [str(key).lower() for key in action.get("keys", [])]
                self._device.hotkey(*keys)
            elif action_name == "Wait":
                time.sleep(_parse_duration_seconds(action.get("duration", "1 second")))
            else:
                return ActionResult(False, False, f"Unknown action: {action_name}")
        except (TypeError, ValueError, KeyError) as exc:
            return ActionResult(False, False, f"Action failed: {exc}")

        return ActionResult(True, False)


def _point(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("missing coordinates")
    return int(value[0]), int(value[1])


def _parse_duration_seconds(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().lower().replace("seconds", "").replace("second", "").strip()
    return float(text or "1")
