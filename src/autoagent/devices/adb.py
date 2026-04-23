from __future__ import annotations

import subprocess
from dataclasses import dataclass


class AdbCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    online: bool
    model: str | None = None
    android_version: str | None = None


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
            )
        )
    return rows


def connect(target: str) -> None:
    _run_adb("connect", target)


def disconnect(target: str) -> None:
    _run_adb("disconnect", target)
