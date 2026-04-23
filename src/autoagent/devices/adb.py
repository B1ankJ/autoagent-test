from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


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


def _run_adb(*args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AdbCommandError(proc.stderr.strip() or f"adb {' '.join(args)} failed")
    return proc


def list_devices() -> list[AdbDevice]:
    proc = _run_adb("devices", "-l")
    rows: list[AdbDevice] = []
    for line in proc.stdout.splitlines():
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        serial, state, *extras = parts
        kv = {item.split(":", 1)[0]: item.split(":", 1)[1] for item in extras if ":" in item}
        rows.append(
            AdbDevice(
                serial=serial,
                online=state == "device",
                model=kv.get("model"),
                android_version=None,
                adb_keyboard_installed=(
                    is_package_installed(serial, "com.android.adbkeyboard")
                    if state == "device"
                    else None
                ),
                adb_keyboard_enabled=is_ime_enabled(serial, "com.android.adbkeyboard/.AdbIME")
                if state == "device"
                else None,
            )
        )
    return rows


def connect(target: str) -> None:
    _run_adb("connect", target)


def disconnect(target: str) -> None:
    _run_adb("disconnect", target)


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


def install_apk(serial: str, apk_path: Path) -> None:
    _run_adb("-s", serial, "install", "-r", "-t", str(apk_path))
