# src/autoagent/executors/agent_core/pc_device.py
from __future__ import annotations

import base64
import logging

import mss
import mss.tools
import pyautogui

from .device import Device, Screenshot

_log = logging.getLogger(__name__)

pyautogui.FAILSAFE = False  # prevent corner-of-screen abort during automation


class PcDevice(Device):
    def capture(self) -> Screenshot:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            grab = sct.grab(monitor)
            png_bytes = mss.tools.to_png(grab.rgb, grab.size)
            b64 = base64.b64encode(png_bytes).decode()
            return Screenshot(base64_data=b64, width=grab.width, height=grab.height)

    def execute_action(self, action: dict) -> None:
        t = action.get("_type")
        if t == "click":
            pyautogui.click(action["x"], action["y"])
        elif t == "type":
            pyautogui.typewrite(action["text"], interval=0.05)
        elif t == "scroll":
            if action.get("direction") == "up":
                pyautogui.scroll(300)
            else:
                pyautogui.scroll(-300)
        elif t == "press":
            pyautogui.press(action["key"])
        else:
            _log.warning("pc_device: unknown action %r", t)
