"""Per-(device, profile) response whitelist for the same-response rule.

Backed by the kv config table so it survives restart. Comparison is exact
string equality after strip — matches what the rule uses to detect a
"same response" streak.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autoagent.storage.configs import get_config, put_config

_KEY = "notification_whitelist"
_EXCERPT_MAX = 160


def normalize(response: str) -> str:
    """Same normalization as the streak comparison."""
    return response.strip()


def _excerpt(text: str) -> str:
    clean = text.replace("\n", " ").strip()
    return clean[:_EXCERPT_MAX] + "…" if len(clean) > _EXCERPT_MAX else clean


async def load_all() -> list[dict[str, Any]]:
    data = await get_config(_KEY)
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


async def _save_all(entries: list[dict[str, Any]]) -> None:
    await put_config(_KEY, entries)


async def contains(device: str, profile: str, response: str) -> bool:
    target = normalize(response)
    for entry in await load_all():
        if (
            entry.get("device_serial") == device
            and entry.get("target_profile") == profile
            and normalize(str(entry.get("response") or "")) == target
        ):
            return True
    return False


async def add(device: str, profile: str, response: str) -> None:
    if await contains(device, profile, response):
        return
    entries = await load_all()
    entries.append(
        {
            "device_serial": device,
            "target_profile": profile,
            "response": response,
            "response_excerpt": _excerpt(response),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    await _save_all(entries)


async def remove(device: str, profile: str, response: str) -> bool:
    target = normalize(response)
    entries = await load_all()
    keep = [
        e
        for e in entries
        if not (
            e.get("device_serial") == device
            and e.get("target_profile") == profile
            and normalize(str(e.get("response") or "")) == target
        )
    ]
    if len(keep) == len(entries):
        return False
    await _save_all(keep)
    return True


async def clear_all() -> int:
    entries = await load_all()
    await _save_all([])
    return len(entries)
