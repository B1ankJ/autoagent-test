from __future__ import annotations

import asyncio
import base64

from autoagent.executors.android_locator import resolve_target
from autoagent.profiles.schemas import Locator


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
