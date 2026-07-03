"""Registry of devices we *expect* to drop offline soon (init reboot).

The device monitor fires a DingTalk "device offline" alert on any
online→offline/missing transition. During an init playbook that reboots
the device, that transition is expected and must not look like a real
hardware fault. The initializer marks the serial here before rebooting;
the notification layer consults it to send a low-key "预期内" message
instead of the alarming one.

Process-local + time-bounded. A restart clears it, which just means a
reboot straddling a restart could produce one alarming alert — an
acceptable edge.
"""
from __future__ import annotations

import time

# serial -> monotonic deadline after which the expectation expires.
_expected_reboot: dict[str, float] = {}


def mark_expected_reboot(serial: str, ttl_sec: float) -> None:
    _expected_reboot[serial] = time.monotonic() + ttl_sec


def clear_expected_reboot(serial: str) -> None:
    _expected_reboot.pop(serial, None)


def is_expected_reboot(serial: str) -> bool:
    """True if `serial` is within a marked reboot window. Prunes as it goes."""
    now = time.monotonic()
    # Drop anything stale so the dict can't grow unbounded.
    for s in [s for s, deadline in _expected_reboot.items() if deadline < now]:
        _expected_reboot.pop(s, None)
    deadline = _expected_reboot.get(serial)
    return deadline is not None and deadline >= now
