from __future__ import annotations

import asyncio
import base64
import time

from autoagent.devices.adb import enable_ime, get_current_ime, is_package_installed, set_ime
from autoagent.executors.android_locator import resolve_target
from autoagent.profiles.schemas import Locator

ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"


class AdbKeyboardNotInstalled(RuntimeError):
    pass


def resolve_input_method(configured: str, prompt: str) -> str:
    if configured != "auto":
        return configured
    return "adb_keyboard" if any(ord(ch) > 127 for ch in prompt) else "u2_send_keys"


class AndroidInput:
    def __init__(self, device, configured_method: str = "auto") -> None:
        self.device = device
        self.configured_method = configured_method

    async def __aenter__(self) -> AndroidInput:
        return self

    async def __aexit__(self, *_exc_info) -> None:
        return None

    async def set_text(self, locator: Locator, text: str) -> None:
        method = resolve_input_method(self.configured_method, text)
        target = resolve_target(self.device, locator)
        if method == "u2_send_keys":
            await asyncio.to_thread(target.click)
            await asyncio.to_thread(self.device.shell, ["input", "text", _escape_input_text(text)])
            return
        if method == "adb_keyboard":
            payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
            await asyncio.to_thread(target.click)
            previous_ime = await asyncio.to_thread(ensure_adb_keyboard_ready, self.device)
            try:
                await asyncio.to_thread(
                    self.device.shell,
                    [
                        "am",
                        "broadcast",
                        "-a",
                        "ADB_INPUT_B64",
                        "--es",
                        "msg",
                        payload,
                    ],
                )
                await asyncio.sleep(0.3)
            finally:
                if previous_ime:
                    await asyncio.to_thread(set_ime, self.device.serial, previous_ime)
            return
        raise ValueError(f"unsupported input method: {method}")


def _escape_input_text(text: str) -> str:
    return (
        text.replace("%", "\\%")
        .replace(" ", "%s")
        .replace("&", "\\&")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace('"', '\\"')
        .replace("'", "\\'")
        .replace(";", "\\;")
    )


def ensure_adb_keyboard_ready(device) -> str | None:
    serial = device.serial
    if not is_package_installed(serial, "com.android.adbkeyboard"):
        raise AdbKeyboardNotInstalled("ADB Keyboard is not installed on the device")
    previous_ime = get_current_ime(serial)
    enable_ime(serial, ADB_KEYBOARD_IME)
    set_ime(serial, ADB_KEYBOARD_IME)
    for _ in range(20):
        if get_current_ime(serial) == ADB_KEYBOARD_IME:
            return previous_ime
        time.sleep(0.1)
    raise RuntimeError("ADB Keyboard IME did not become active")
