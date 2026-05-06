from __future__ import annotations

import base64
import logging
import struct
import subprocess
import time
from typing import Any

from autoagent.executors.agent_core.action_parser import parse_action as parse_legacy_action
from autoagent.executors.agent_core.device import Device, Screenshot

_log = logging.getLogger(__name__)


class AndroidDeviceAdapter(Device):
    def __init__(self, serial: str | None = None) -> None:
        self._serial = serial
        self._adb = ["adb"] + (["-s", serial] if serial else [])

    def capture(self) -> Screenshot:
        result = subprocess.run(
            self._adb + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=15,
        )
        result.check_returncode()
        png_bytes = result.stdout
        b64 = base64.b64encode(png_bytes).decode()
        width, height = struct.unpack(">II", png_bytes[16:24])
        return Screenshot(base64_data=b64, width=width, height=height)

    def tap(self, x: int, y: int) -> None:
        self._adb_run(["shell", "input", "tap", str(x), str(y)])

    def double_tap(self, x: int, y: int) -> None:
        tap_args = ["shell", "input", "tap", str(x), str(y)]
        self._adb_run(tap_args)
        self._adb_run(tap_args)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._adb_run(
            ["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms)]
        )

    def type_text(self, text: str) -> None:
        if text.isascii():
            self._adb_run(["shell", "input", "text", text])
            return
        self._adb_run(["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text])

    def press_key(self, key: str) -> None:
        key_map = {"enter": "KEYCODE_ENTER", "back": "KEYCODE_BACK", "home": "KEYCODE_HOME"}
        keycode = key_map.get(key.lower(), key.upper())
        self._adb_run(["shell", "input", "keyevent", keycode])

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self._adb_run(
            [
                "shell",
                "input",
                "swipe",
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                "300",
            ]
        )

    def scroll(self, direction: str, clicks: int) -> None:
        distance = int(clicks) * 300
        if direction == "up":
            self._adb_run(
                ["shell", "input", "swipe", "540", "400", "540", str(400 + distance), "300"]
            )
            return
        self._adb_run(
            ["shell", "input", "swipe", "540", "1200", "540", str(1200 - distance), "300"]
        )

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
        elif action_type == "wait":
            time.sleep(float(legacy_action.get("seconds", 1)))
        elif action_type in {"finish", "noop"}:
            return
        else:
            _log.warning("android_device: unknown action %r", action_type)

    def _adb_run(self, args: list[str], *, timeout: int = 10) -> None:
        subprocess.run(self._adb + args, capture_output=True, timeout=timeout, check=True)
