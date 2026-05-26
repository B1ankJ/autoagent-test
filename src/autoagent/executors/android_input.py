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


def resolve_input_method(
    configured: str,
    prompt: str,
    *,
    adb_keyboard_available: bool | None = None,
) -> str:
    if configured != "auto":
        return configured
    if adb_keyboard_available is not False:
        return "adb_keyboard"
    return "adb_keyboard" if any(ord(ch) > 127 for ch in prompt) else "u2_send_keys"


class AndroidInput:
    def __init__(self, device, configured_method: str = "auto") -> None:
        self.device = device
        self.configured_method = configured_method
        self._pending_restore_ime: str | None = None
        self._active_method: str | None = None

    async def __aenter__(self) -> AndroidInput:
        return self

    async def __aexit__(self, *_exc_info) -> None:
        await self.restore_pending_ime()
        return None

    async def restore_pending_ime(self) -> None:
        if self._pending_restore_ime:
            await asyncio.to_thread(set_ime, self.device.serial, self._pending_restore_ime)
            self._pending_restore_ime = None
        self._active_method = None

    async def prepare_for_prompt(self, text: str) -> str:
        method = await self.preview_method(text)
        if method == "adb_keyboard" and self._active_method != "adb_keyboard":
            previous_ime = await asyncio.to_thread(ensure_adb_keyboard_ready, self.device)
            self._pending_restore_ime = previous_ime
            self._active_method = "adb_keyboard"
        return method

    async def preview_method(self, text: str) -> str:
        adb_keyboard_available: bool | None = None
        if self.configured_method == "auto":
            adb_keyboard_available = await asyncio.to_thread(
                is_package_installed, self.device.serial, "com.android.adbkeyboard"
            )
        return resolve_input_method(
            self.configured_method,
            text,
            adb_keyboard_available=adb_keyboard_available,
        )

    async def set_text(self, locator: Locator | None, text: str) -> None:
        method = await self.prepare_for_prompt(text)
        # When locator is omitted, trust the caller's input_focus_action to
        # have left focus on the correct field. Skip the re-click and the
        # u2 clear_text (which needs an element handle); for cleanup we fall
        # back to ADB_CLEAR_TEXT on the adb_keyboard path and to a select-all
        # + delete on the u2_send_keys path.
        target = resolve_target(self.device, locator) if locator is not None else None
        if method == "u2_send_keys":
            if target is not None:
                await asyncio.to_thread(target.click)
                try:
                    await asyncio.to_thread(target.clear_text)
                except Exception:
                    pass
            else:
                # Approximate clear: select-all then delete on the focused field.
                await asyncio.to_thread(
                    self.device.shell, ["input", "keyevent", "KEYCODE_MOVE_END"]
                )
                await asyncio.to_thread(
                    self.device.shell, ["input", "keyevent", "--longpress"]
                    + ["KEYCODE_DEL"] * 200
                )
            await asyncio.to_thread(self.device.shell, ["input", "text", _escape_input_text(text)])
            return
        if method == "adb_keyboard":
            payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
            if target is not None:
                try:
                    await asyncio.to_thread(_click_target, target, 1.0)
                except Exception:
                    # The focus action may already have opened the editor while
                    # the EditText is not visible in UIA XML. In that state the
                    # ADB keyboard broadcast can still insert into the focused
                    # field.
                    pass
            # Clear focused field first — ADB_INPUT_B64 appends, so retries
            # would otherwise stack text from previous attempts.
            await asyncio.to_thread(
                self.device.shell,
                ["am", "broadcast", "-a", "ADB_CLEAR_TEXT"],
            )
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
            return
        raise ValueError(f"unsupported input method: {method}")


def _click_target(target, timeout: float | None = None) -> None:
    if timeout is None:
        target.click()
        return
    try:
        target.click(timeout=timeout)
    except TypeError:
        target.click()


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
