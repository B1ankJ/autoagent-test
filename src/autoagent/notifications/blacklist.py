"""Per-profile response blacklist for the same-response rule.

Symmetric to whitelist.py but opposite meaning: a blacklisted response is
known-bad (a human confirmed a past same-response alert was a real
anomaly), so a repeat is alerted on immediately — skipping both the
consecutive-streak wait and the VLM "is this still a normal page?" judge,
since we already know the answer is no. Manual-only (no auto-add, unlike
whitelist's auto-add-on-VLM-says-normal) — auto-blacklisting on every
alert would risk permanently blacklisting a response off one VLM/human
misjudgment with no review step.
"""
from __future__ import annotations

from typing import Any

from autoagent.notifications import _response_list as _rl

_KEY = "notification_blacklist"

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
