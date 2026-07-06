from __future__ import annotations

import logging
import re as _re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

# All adb subprocess calls carry a timeout so a wifi device that stopped
# responding can't hang the caller (the monitor / device pool live on
# the event loop).
_DEFAULT_ADB_TIMEOUT_SEC = 10


class AdbCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    online: bool
    model: str | None = None
    android_version: str | None = None
    adb_keyboard_installed: bool | None = None
    adb_keyboard_enabled: bool | None = None


def _run_adb(
    *args: str, timeout_sec: float = _DEFAULT_ADB_TIMEOUT_SEC
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            ["adb", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        raise AdbCommandError(f"adb {' '.join(args)} timed out after {timeout_sec}s") from e
    if proc.returncode != 0:
        raise AdbCommandError(proc.stderr.strip() or f"adb {' '.join(args)} failed")
    return proc


def _safe_meta_call(func, serial: str, *args) -> bool | None:
    """Return the result of a metadata probe, or None if the device errors.

    One flaky wifi device shouldn't invalidate the enumeration of every
    other device — swallow per-device failures and let the caller keep
    the row with unknown fields.
    """
    try:
        return func(serial, *args)
    except AdbCommandError as e:
        _log.info("adb metadata probe failed for %s (%s): %s", serial, func.__name__, e)
        return None


def list_devices() -> list[AdbDevice]:
    proc = _run_adb("devices", "-l")
    rows: list[AdbDevice] = []
    for line in proc.stdout.splitlines():
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        serial, state, *extras = parts
        kv = {item.split(":", 1)[0]: item.split(":", 1)[1] for item in extras if ":" in item}
        online = state == "device"
        rows.append(
            AdbDevice(
                serial=serial,
                online=online,
                model=kv.get("model"),
                android_version=None,
                adb_keyboard_installed=(
                    _safe_meta_call(is_package_installed, serial, "com.android.adbkeyboard")
                    if online
                    else None
                ),
                adb_keyboard_enabled=(
                    _safe_meta_call(is_ime_enabled, serial, "com.android.adbkeyboard/.AdbIME")
                    if online
                    else None
                ),
            )
        )
    return rows


def connect(target: str) -> None:
    _run_adb("connect", target)


def disconnect(target: str) -> None:
    _run_adb("disconnect", target)


def _is_network_serial(serial: str) -> bool:
    # host:port form — wifi/network adb. Reboot drops the TCP connection and
    # it must be re-established explicitly (USB re-enumerates on its own).
    return ":" in serial and not serial.startswith(":")


def reboot(serial: str) -> None:
    """Trigger a device reboot. Returns as soon as adb accepts the command."""
    _run_adb("-s", serial, "reboot", timeout_sec=30)


def is_boot_completed(serial: str) -> bool:
    try:
        out = _run_adb(
            "-s", serial, "shell", "getprop", "sys.boot_completed", timeout_sec=8
        ).stdout.strip()
    except AdbCommandError:
        return False
    return out == "1"


def wait_for_boot(serial: str, *, timeout_sec: float = 120.0, poll_sec: float = 3.0) -> bool:
    """Block until sys.boot_completed==1 (reconnecting wifi devices first).

    Returns True on success, False on timeout. Never raises — callers treat
    a False as "reboot didn't come back, proceed / surface an error".
    """
    import time as _time

    deadline = _time.monotonic() + timeout_sec
    network = _is_network_serial(serial)
    while _time.monotonic() < deadline:
        if network:
            # Reconnect is idempotent; keep trying until the device answers.
            try:
                _run_adb("connect", serial, timeout_sec=8)
            except AdbCommandError:
                pass
        if is_boot_completed(serial):
            return True
        _time.sleep(poll_sec)
    return False


def shell(serial: str, *args: str) -> str:
    return _run_adb("-s", serial, "shell", *args).stdout


def is_package_installed(serial: str, package: str) -> bool:
    return f"package:{package}" in shell(serial, "pm", "list", "packages")


def is_ime_enabled(serial: str, ime_id: str) -> bool:
    return ime_id in shell(serial, "ime", "list", "-s")


def get_current_ime(serial: str) -> str | None:
    current = shell(serial, "settings", "get", "secure", "default_input_method").strip()
    return None if not current or current == "null" else current


def enable_ime(serial: str, ime_id: str) -> None:
    _run_adb("-s", serial, "shell", "ime", "enable", ime_id)


def set_ime(serial: str, ime_id: str) -> None:
    _run_adb("-s", serial, "shell", "ime", "set", ime_id)


def list_enabled_imes(serial: str) -> list[str]:
    out = shell(serial, "ime", "list", "-s")
    return [line.strip() for line in out.splitlines() if line.strip()]


def reset_ime(serial: str) -> None:
    """Reset IMEs to the device's system defaults (cross-ROM safe).

    `ime reset` re-enables the framework defaults and selects one, so it
    works even on ROMs that lack the AOSP LatinIME. Used to switch off the
    ADB keyboard without guessing a package name.
    """
    _run_adb("-s", serial, "shell", "ime", "reset")


def install_apk(serial: str, apk_path: Path) -> None:
    # APK install legitimately takes tens of seconds; the caller is a
    # request handler where we're OK waiting longer than the default.
    _run_adb("-s", serial, "install", "-r", "-t", str(apk_path), timeout_sec=120)


def get_screen_resolution(serial: str, target_width: int = 0) -> tuple[int, int]:
    """Return (width, height), optionally scaled so width == target_width."""
    proc = _run_adb("-s", serial, "shell", "wm", "size")
    match = _re.search(r"Physical size:\s*(\d+)x(\d+)", proc.stdout)
    if not match:
        raise AdbCommandError(f"Cannot parse screen resolution from: {proc.stdout!r}")
    native_w, native_h = int(match.group(1)), int(match.group(2))
    if target_width <= 0:
        return native_w, native_h
    scaled_h = round(native_h * target_width / native_w)
    # Ensure both dimensions are even (H264 requirement)
    return target_width - target_width % 2, scaled_h - scaled_h % 2


_SHELL_SPECIAL = set('&|;<>()$`\\"\'')


def _escape_text_for_adb(text: str) -> str:
    """Encode text for `adb shell input text` (spaces → %s, special chars → backslash-escaped)."""
    result = []
    for ch in text:
        if ch == " ":
            result.append("%s")
        elif ch in _SHELL_SPECIAL:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def run_input_command(serial: str, cmd: dict) -> None:
    """Execute an adb input command on the device."""
    t = cmd.get("type")
    if t == "tap":
        _run_adb("-s", serial, "shell", "input", "tap", str(cmd["x"]), str(cmd["y"]))
    elif t == "swipe":
        _run_adb(
            "-s", serial, "shell", "input", "swipe",
            str(cmd["x1"]), str(cmd["y1"]), str(cmd["x2"]), str(cmd["y2"]),
            str(cmd.get("duration_ms", 300)),
        )
    elif t == "text":
        _run_adb("-s", serial, "shell", "input", "text", _escape_text_for_adb(cmd["value"]))
    elif t == "key":
        _run_adb("-s", serial, "shell", "input", "keyevent", cmd["keycode"])
    else:
        raise AdbCommandError(f"Unknown input type: {t!r}")
