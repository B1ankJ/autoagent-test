from __future__ import annotations

import base64
import logging
import struct
import subprocess

from autoagent.executors.agent_core.device import Device, Screenshot

_log = logging.getLogger(__name__)


class AndroidDevice(Device):
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
        w, h = struct.unpack(">II", png_bytes[16:24])
        return Screenshot(base64_data=b64, width=w, height=h)

    def execute_action(self, action: dict) -> None:
        t = action.get("_type")
        if t == "click":
            self._adb_run(["shell", "input", "tap", str(action["x"]), str(action["y"])])
        elif t == "type":
            text = action["text"]
            escaped = text.replace("'", "'\\''")
            if text.isascii():
                self._adb_run(["shell", "input", "text", f"'{escaped}'"])
            else:
                self._adb_run(
                    # ADB Keyboard broadcast for non-ASCII text
                    [
                        "shell",
                        "am",
                        "broadcast",
                        "-a",
                        "ADB_INPUT_TEXT",
                        "--es",
                        "msg",
                        f"'{escaped}'",
                    ]
                )
        elif t == "scroll":
            amount = action.get("amount", 3)
            dist = amount * 300
            if action.get("direction") == "up":
                # finger swipes down → content moves up
                y_end = 400 + dist
                self._adb_run(["shell", "input", "swipe", "540", "400", "540", str(y_end), "300"])
            else:
                # finger swipes up → content moves down
                y_end = 1200 - dist
                self._adb_run(["shell", "input", "swipe", "540", "1200", "540", str(y_end), "300"])
        elif t == "press":
            key_map = {"enter": "KEYCODE_ENTER", "back": "KEYCODE_BACK", "home": "KEYCODE_HOME"}
            keycode = key_map.get(action["key"], action["key"].upper())
            self._adb_run(["shell", "input", "keyevent", keycode])
        else:
            _log.warning("android_device: unknown action %r", t)

    def _adb_run(self, args: list[str], *, timeout: int = 10) -> None:
        subprocess.run(self._adb + args, capture_output=True, timeout=timeout, check=True)
