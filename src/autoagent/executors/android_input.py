from __future__ import annotations

import asyncio

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
        if method in {"u2_send_keys", "adb_keyboard"}:
            await asyncio.to_thread(target.set_text, text)
            return
        raise ValueError(f"unsupported input method: {method}")
