# src/autoagent/executors/agent_core/pc_device.py
from __future__ import annotations

import base64
import logging
import time

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
        elif t == "double_click":
            pyautogui.doubleClick(action["x"], action["y"])
        elif t == "long_press":
            pyautogui.mouseDown(action["x"], action["y"])
            time.sleep(action.get("duration_ms", 800) / 1000.0)
            pyautogui.mouseUp(action["x"], action["y"])
        elif t == "type":
            pyautogui.typewrite(action["text"], interval=0.05)
        elif t == "scroll":
            delta = int(action.get("amount", 3)) * 300
            pyautogui.scroll(delta if action.get("direction") == "up" else -delta)
        elif t == "press":
            pyautogui.press(action["key"])
        elif t == "hotkey":
            pyautogui.hotkey(*action["keys"])
        elif t == "wait":
            time.sleep(float(action.get("seconds", 1)))
        else:
            _log.warning("pc_device: unknown action %r", t)
