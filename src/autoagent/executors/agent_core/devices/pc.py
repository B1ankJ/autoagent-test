from __future__ import annotations

import base64
import logging
import time
from typing import Any

import mss
import mss.tools
import pyautogui

from autoagent.executors.agent_core.action_parser import parse_action as parse_legacy_action
from autoagent.executors.agent_core.device import Device, Screenshot

_log = logging.getLogger(__name__)

pyautogui.FAILSAFE = False


class PcDeviceAdapter(Device):
    def capture(self) -> Screenshot:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            grab = sct.grab(monitor)
            png_bytes = mss.tools.to_png(grab.rgb, grab.size)
            b64 = base64.b64encode(png_bytes).decode()
            return Screenshot(base64_data=b64, width=grab.width, height=grab.height)

    def tap(self, x: int, y: int) -> None:
        pyautogui.click(x, y)

    def double_tap(self, x: int, y: int) -> None:
        pyautogui.doubleClick(x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        pyautogui.mouseDown(x, y)
        time.sleep(duration_ms / 1000.0)
        pyautogui.mouseUp(x, y)

    def type_text(self, text: str) -> None:
        pyautogui.typewrite(text, interval=0.05)

    def press_key(self, key: str) -> None:
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        pyautogui.hotkey(*keys)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        pyautogui.moveTo(start_x, start_y)
        pyautogui.dragTo(end_x, end_y, duration=0.3, button="left")

    def scroll(self, direction: str, clicks: int) -> None:
        delta = int(clicks) * 300
        pyautogui.scroll(delta if direction == "up" else -delta)

    def execute_action(self, action: dict[str, Any]) -> None:
        legacy_action = action
        if action.get("_metadata") is not None:
            legacy_action = parse_legacy_action(str(action))
        action_type = legacy_action.get("_type")
        if action_type == "click":
            self.tap(legacy_action["x"], legacy_action["y"])
        elif action_type == "double_click":
            self.double_tap(legacy_action["x"], legacy_action["y"])
        elif action_type == "long_press":
            self.long_press(
                legacy_action["x"],
                legacy_action["y"],
                duration_ms=legacy_action.get("duration_ms", 800),
            )
        elif action_type == "type":
            self.type_text(legacy_action["text"])
        elif action_type == "scroll":
            self.scroll(legacy_action.get("direction", "down"), int(legacy_action.get("amount", 3)))
        elif action_type == "press":
            self.press_key(legacy_action["key"])
        elif action_type == "hotkey":
            self.hotkey(*legacy_action["keys"])
        elif action_type == "wait":
            time.sleep(float(legacy_action.get("seconds", 1)))
        elif action_type in {"finish", "noop"}:
            return
        else:
            _log.warning("pc_device: unknown action %r", action_type)
