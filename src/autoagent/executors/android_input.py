from __future__ import annotations


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
