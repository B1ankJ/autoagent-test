"""Shared kv-backed (target_profile, response) list logic.

Both notifications/whitelist.py and notifications/blacklist.py are thin
wrappers around this — same storage shape and exact-match-after-strip
comparison, different kv key and opposite meaning for the same-response
rule: a whitelist hit means "known-fine, don't alert"; a blacklist hit
means "known-bad, alert immediately without asking the VLM."
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autoagent.storage.configs import get_config, put_config

_EXCERPT_MAX = 160


def normalize(response: str) -> str:
    """Same normalization as the same-response streak comparison."""
    return response.strip()


def _excerpt(text: str) -> str:
    clean = text.replace("\n", " ").strip()
    return clean[:_EXCERPT_MAX] + "…" if len(clean) > _EXCERPT_MAX else clean


async def load_all(key: str) -> list[dict[str, Any]]:
    data = await get_config(key)
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


async def _save_all(key: str, entries: list[dict[str, Any]]) -> None:
    await put_config(key, entries)


async def contains(key: str, profile: str, response: str) -> bool:
    target = normalize(response)
    for entry in await load_all(key):
        if (
            entry.get("target_profile") == profile
            and normalize(str(entry.get("response") or "")) == target
        ):
            return True
    return False


async def add(key: str, profile: str, response: str) -> None:
    if await contains(key, profile, response):
        return
    entries = await load_all(key)
    entries.append(
        {
            "target_profile": profile,
            "response": response,
            "response_excerpt": _excerpt(response),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    await _save_all(key, entries)


async def remove(key: str, profile: str, response: str) -> bool:
    target = normalize(response)
    entries = await load_all(key)
    keep = [
        e
        for e in entries
        if not (
            e.get("target_profile") == profile
            and normalize(str(e.get("response") or "")) == target
        )
    ]
    if len(keep) == len(entries):
        return False
    await _save_all(key, keep)
    return True


async def clear_all(key: str) -> int:
    entries = await load_all(key)
    await _save_all(key, [])
    return len(entries)
