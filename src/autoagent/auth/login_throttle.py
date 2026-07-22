"""In-memory login-attempt throttling, keyed by submitted username.

Single-process, in-memory — resets on restart and doesn't share state
across workers. That's an accepted tradeoff for this threat model (slowing
down online brute force against the documented default admin password),
not a general-purpose rate limiter.
"""

from __future__ import annotations

import time
from collections import OrderedDict

MAX_ATTEMPTS = 5
LOCKOUT_SEC = 15 * 60
# Bounds memory if an attacker floods distinct usernames instead of
# retrying one — same bounded-OrderedDict eviction pattern as media.py's
# thumbnail cache.
_MAX_TRACKED = 10_000

_failures: OrderedDict[str, int] = OrderedDict()
_locked_until: dict[str, float] = {}


def seconds_until_unlocked(username: str) -> float | None:
    """None if not locked, else remaining lockout seconds."""
    until = _locked_until.get(username)
    if until is None:
        return None
    remaining = until - time.monotonic()
    if remaining <= 0:
        _locked_until.pop(username, None)
        return None
    return remaining


def record_failure(username: str) -> None:
    count = _failures.get(username, 0) + 1
    _failures[username] = count
    _failures.move_to_end(username)
    while len(_failures) > _MAX_TRACKED:
        oldest, _ = _failures.popitem(last=False)
        _locked_until.pop(oldest, None)
    if count >= MAX_ATTEMPTS:
        _locked_until[username] = time.monotonic() + LOCKOUT_SEC


def record_success(username: str) -> None:
    _failures.pop(username, None)
    _locked_until.pop(username, None)


def reset() -> None:
    """Test-only: clear all tracked state."""
    _failures.clear()
    _locked_until.clear()
