"""Low-latency device input via a persistent uiautomator2 connection.

`adb shell input tap/swipe/keyevent` pays a ~200-500ms penalty per call: the
on-device `input` binary is a shell script that spins up a fresh `app_process`
JVM and loads the framework every single time. uiautomator2 instead talks to an
on-device server whose JVM stays warm, so each injection skips that cold start.

This module keeps one cached u2 connection per serial and routes the stream
UI's tap/swipe/key through it, falling back to `adb shell input` on any
failure (device dropped, injection rejected on a FLAG_SECURE screen, etc.) so
behavior is never worse than the old shell-only path. `text` deliberately
stays on the shell path — see send_input's docstring.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import uiautomator2 as u2

from autoagent.devices.adb import run_input_command

log = logging.getLogger(__name__)

# KEYCODE_* strings (what the stream UI sends) → the symbolic key names
# uiautomator2's press() understands. A keycode not listed here raises inside
# _dispatch_u2, which routes it to the shell fallback (adb shell input keyevent
# KEYCODE_X handles the full set).
_KEYCODE_TO_U2: dict[str, str] = {
    "KEYCODE_BACK": "back",
    "KEYCODE_HOME": "home",
    "KEYCODE_APP_SWITCH": "recent",
    "KEYCODE_ENTER": "enter",
    "KEYCODE_DEL": "delete",
}

# serial → cached persistent u2 connection.
_connections: dict[str, Any] = {}


def reset_connections() -> None:
    """Drop all cached connections (used by tests)."""
    _connections.clear()


def _get_connection(serial: str, connect: Callable[[str], Any]) -> Any:
    conn = _connections.get(serial)
    if conn is None:
        conn = connect(serial)
        _connections[serial] = conn
    return conn


def _dispatch_u2(conn: Any, cmd: dict) -> None:
    t = cmd.get("type")
    if t == "tap":
        conn.click(cmd["x"], cmd["y"])
    elif t == "swipe":
        conn.swipe(
            cmd["x1"],
            cmd["y1"],
            cmd["x2"],
            cmd["y2"],
            duration=cmd.get("duration_ms", 300) / 1000,
        )
    elif t == "key":
        conn.press(_KEYCODE_TO_U2[cmd["keycode"]])  # KeyError → shell fallback
    else:
        raise ValueError(f"u2 dispatch unsupported type: {t!r}")


def send_input(
    serial: str,
    cmd: dict,
    *,
    connect: Callable[[str], Any] = u2.connect,
    shell: Callable[[str, dict], None] = run_input_command,
) -> None:
    """Inject an input command, preferring u2 and falling back to adb shell.

    tap/swipe/key go through the persistent u2 connection (warm JVM → no
    per-call app_process cold start). `text` always uses the shell path:
    u2.send_keys switches the device IME (FastInputIME) as a side effect,
    which fights the executor's own ADB-Keyboard IME management, and
    text-entry latency was never the pain point taps are.
    """
    if cmd.get("type") == "text":
        shell(serial, cmd)
        return
    try:
        conn = _get_connection(serial, connect)
        _dispatch_u2(conn, cmd)
    except Exception:
        # Drop a possibly-dead connection so the next call reconnects, then
        # fall back to the shell path (never worse than the old behavior).
        _connections.pop(serial, None)
        log.warning(
            "u2 input failed for %s (type=%s); falling back to adb shell input",
            serial,
            cmd.get("type"),
            exc_info=True,
        )
        shell(serial, cmd)
