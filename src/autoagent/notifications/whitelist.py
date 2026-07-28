"""Per-profile response whitelist for the same-response rule.

Scoped by `target_profile` only — if a profile legitimately produces a
canned reply, that fact is the same regardless of which device runs it,
so one whitelist add applies to every device using that profile.

Thin wrapper around _response_list.py's shared storage/matching logic —
see blacklist.py for the symmetric "known-bad" counterpart. Backed by the
kv config table so it survives restart.
"""
from __future__ import annotations

from typing import Any

from autoagent.notifications import _response_list as _rl

_KEY = "notification_whitelist"

normalize = _rl.normalize


async def load_all() -> list[dict[str, Any]]:
    return await _rl.load_all(_KEY)


async def contains(profile: str, response: str) -> bool:
    return await _rl.contains(_KEY, profile, response)


async def add(profile: str, response: str) -> None:
    await _rl.add(_KEY, profile, response)


async def remove(profile: str, response: str) -> bool:
    return await _rl.remove(_KEY, profile, response)


async def clear_all() -> int:
    return await _rl.clear_all(_KEY)
