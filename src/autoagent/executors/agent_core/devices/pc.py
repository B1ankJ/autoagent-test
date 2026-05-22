from __future__ import annotations

import base64
import logging
import subprocess
import sys
import time
from typing import Any

from autoagent.executors.agent_core.device import Device, Screenshot

_log = logging.getLogger(__name__)


def _pyautogui():
    import pyautogui as _m  # noqa: PLC0415
    _m.FAILSAFE = False
    return _m



def _pyperclip():
    try:
        import pyperclip as _m  # noqa: PLC0415
        return _m
    except ImportError:
        class _ClipboardFallback:
            @staticmethod
            def copy(text: str) -> None:
                if sys.platform == "darwin":
                    subprocess.run(["pbcopy"], input=text, text=True, check=True)
                    return
                if sys.platform.startswith("win"):
                    subprocess.run(["clip"], input=text, text=True, check=True)
                    return
                subprocess.run(
                    ["xclip", "-selection", "clipboard"], input=text, text=True, check=True
                )

        return _ClipboardFallback()


class PcDeviceAdapter(Device):
    def capture(self) -> Screenshot:
        import mss as _mss_mod  # noqa: PLC0415
        import mss.tools as _mss_tools  # noqa: PLC0415
        with _mss_mod.mss() as sct:
            monitor = sct.monitors[1]
            grab = sct.grab(monitor)
            png_bytes = _mss_tools.to_png(grab.rgb, grab.size)
            b64 = base64.b64encode(png_bytes).decode()
            return Screenshot(base64_data=b64, width=grab.width, height=grab.height)

    def tap(self, x: int, y: int) -> None:
        _pyautogui().click(x, y)

    def double_tap(self, x: int, y: int) -> None:
        _pyautogui().doubleClick(x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        pg = _pyautogui()
        pg.mouseDown(x, y)
        time.sleep(duration_ms / 1000.0)
        pg.mouseUp(x, y)

    def type_text(self, text: str) -> None:
        _pyperclip().copy(text)
        paste_modifier = "command" if sys.platform == "darwin" else "ctrl"
        _pyautogui().hotkey(paste_modifier, "v")
        time.sleep(0.1)

    def clear_clipboard(self) -> None:
        _pyperclip().copy("")

    def read_clipboard(self) -> str:
        clip = _pyperclip()
        paste = getattr(clip, "paste", None)
        if paste is None:
            return ""
        try:
            return paste() or ""
        except Exception:
            _log.exception("pc_device: read_clipboard failed")
            return ""

    def press_key(self, key: str) -> None:
        _pyautogui().press(key)

    def hotkey(self, *keys: str) -> None:
        _pyautogui().hotkey(*keys)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        pg = _pyautogui()
        pg.moveTo(start_x, start_y)
        pg.dragTo(end_x, end_y, duration=0.3, button="left")

    def scroll(self, direction: str, clicks: int) -> None:
        delta = int(clicks) * 300
        _pyautogui().scroll(delta if direction == "up" else -delta)

    def execute_action(self, action: dict[str, Any]) -> None:
        legacy_action = _coerce_legacy_action(action)
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


def _coerce_legacy_action(action: dict[str, Any]) -> dict[str, Any]:
    action_type = action.get("_type")
    if isinstance(action_type, str):
        return action

    metadata = action.get("_metadata")
    if metadata != "do":
        return {"_type": "finish" if metadata == "finish" else "noop"}

    action_name = str(action.get("action", "")).strip().lower()
    if action_name in {"tap", "click"}:
        return {"_type": "click", "x": int(action["element"][0]), "y": int(action["element"][1])}
    if action_name == "double tap":
        return {
            "_type": "double_click",
            "x": int(action["element"][0]),
            "y": int(action["element"][1]),
        }
    if action_name == "long press":
        return {
            "_type": "long_press",
            "x": int(action["element"][0]),
            "y": int(action["element"][1]),
            "duration_ms": int(action.get("duration_ms", 800)),
        }
    if action_name == "type":
        return {"_type": "type", "text": str(action.get("text", ""))}
    if action_name == "scroll":
        return {
            "_type": "scroll",
            "direction": str(action.get("direction", "down")).lower(),
            "amount": int(action.get("clicks", 3)),
        }
    if action_name == "press":
        return {"_type": "press", "key": str(action.get("key", "")).lower()}
    if action_name == "back":
        return {"_type": "press", "key": "back"}
    if action_name == "home":
        return {"_type": "press", "key": "home"}
    if action_name == "hotkey":
        return {"_type": "hotkey", "keys": [str(key).lower() for key in action.get("keys", [])]}
    if action_name == "wait":
        duration = action.get("duration", action.get("seconds", 1))
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            seconds = float(duration)
        else:
            text = str(duration).strip().lower().replace("seconds", "").replace("second", "")
            seconds = float(text.strip() or "1")
        return {"_type": "wait", "seconds": seconds}
    return {"_type": "noop"}
