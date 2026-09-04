"""Low-latency device input via a persistent uiautomator2 connection.

`adb shell input tap/swipe/keyevent` pays a ~200-500ms penalty per call: the
on-device `input` binary is a shell script that spins up a fresh `app_process`
JVM and loads the framework every single time. uiautomator2 instead talks to an
on-device server whose JVM stays warm, so each injection skips that cold start.

Critical subtlety (learned the hard way): in uiautomator2 3.x, `u2.connect()`
*synchronously starts* the on-device server — the first time on a given device
it installs the `com.github.uiautomator` apks and launches instrumentation,
which is slow and can hang or fail on locked-down devices. So we must NEVER do
that on the tap's critical path, or a tap just blocks until the client times
out ("操作发送失败").

Design: taps always work via `adb shell input` immediately (never worse than
before, never blocks). The u2 connection is warmed up **in a background
thread**; only once it's confirmed ready does subsequent input route through it
(fast path). If warmup never succeeds (device blocks the test apk), input stays
on the shell path forever — slower, but functional. `text` always uses the
shell path regardless — see send_input's docstring.
"""

from __future__ import annotations

import logging
import threading
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

# serial → confirmed-ready u2 connection (only set by a successful warmup).
_ready: dict[str, Any] = {}
# serials with a warmup currently in flight (dedupes concurrent kick-offs).
_warming: set[str] = set()
# guards _ready / _warming across the request threads + warmup threads.
_lock = threading.Lock()


def reset_connections() -> None:
    """Drop all cached connections and warmup flags (used by tests)."""
    with _lock:
        _ready.clear()
        _warming.clear()


def _default_probe(conn: Any) -> None:
    """Force the u2 server to actually come up and answer, so we only mark a
    connection ready once it can really serve RPCs."""
    _ = conn.info  # property access issues a jsonrpc call (the point is the call)


def _warmup(
    serial: str,
    connect: Callable[[str], Any],
    probe: Callable[[Any], None],
) -> None:
    """Provision + verify a u2 connection off the request path. Marks the
    serial ready on success; always clears the in-flight flag so a later tap
    can retry after a failure."""
    try:
        conn = connect(serial)
        probe(conn)
        with _lock:
            _ready[serial] = conn
        log.info("u2 connection ready for %s; input now uses uiautomator2", serial)
    except Exception:
        log.warning("u2 warmup failed for %s; input stays on adb shell", serial, exc_info=True)
    finally:
        with _lock:
            _warming.discard(serial)


def _default_spawn(
    serial: str,
    connect: Callable[[str], Any],
    probe: Callable[[Any], None],
) -> None:
    threading.Thread(target=_warmup, args=(serial, connect, probe), daemon=True).start()


def _start_warmup(
    serial: str,
    connect: Callable[[str], Any],
    probe: Callable[[Any], None],
    spawn: Callable[[str, Callable[[str], Any], Callable[[Any], None]], None],
) -> None:
    with _lock:
        if serial in _ready or serial in _warming:
            return
        _warming.add(serial)
    spawn(serial, connect, probe)


def _dispatch_u2(conn: Any, cmd: dict) -> None:
    # tap/swipe coords are normalized 0-1 fractions. u2's click/swipe treat a
    # coord < 1 as a fraction of the live window size (pos_rel2abs), so passing
    # them straight through scales to the device's real resolution for free —
    # accuracy is independent of the video stream resolution.
    t = cmd.get("type")
    if t == "tap":
        conn.click(cmd["nx"], cmd["ny"])
    elif t == "swipe":
        conn.swipe(
            cmd["nx1"],
            cmd["ny1"],
            cmd["nx2"],
            cmd["ny2"],
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
    probe: Callable[[Any], None] = _default_probe,
    spawn: Callable[[str, Callable[[str], Any], Callable[[Any], None]], None] = _default_spawn,
) -> None:
    """Inject an input command, preferring a warm u2 connection and never
    blocking on u2 provisioning.

    tap/swipe/key use the persistent u2 connection *only once it's been warmed
    up in the background* (warm JVM → no per-call app_process cold start). Until
    then — and whenever u2 fails — the command goes through `adb shell input`,
    so behavior is never worse (or slower to respond) than the old shell path.
    `text` always uses the shell path: u2.send_keys switches the device IME
    (FastInputIME) as a side effect, which fights the executor's own
    ADB-Keyboard IME management, and text-entry latency was never the pain
    point taps are.
    """
    if cmd.get("type") == "text":
        shell(serial, cmd)
        return

    conn = _ready.get(serial)
    if conn is not None:
        try:
            _dispatch_u2(conn, cmd)
            return
        except Exception:
            with _lock:
                _ready.pop(serial, None)
            log.warning(
                "u2 input failed for %s (type=%s); falling back to adb shell input",
                serial,
                cmd.get("type"),
                exc_info=True,
            )
            # fall through to the shell path below
    else:
        # No warm connection yet — kick one off for next time (non-blocking).
        _start_warmup(serial, connect, probe, spawn)

    shell(serial, cmd)
