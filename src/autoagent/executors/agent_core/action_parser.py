from __future__ import annotations

import re
from typing import Any

from autoagent.executors.agent_core.parser import parse_action as parse_unified_action


def parse_action(text: str) -> dict[str, Any]:
    """Compatibility wrapper returning the legacy `_type` action schema."""
    return _to_legacy_action(parse_unified_action(text))


def _to_legacy_action(action: dict[str, Any]) -> dict[str, Any]:
    metadata = action.get("_metadata")
    if metadata == "finish":
        return {"_type": "finish", "message": str(action.get("message", ""))}

    if metadata == "noop":
        return {"_type": "noop"}

    if metadata != "do":
        return {"_type": "noop"}

    action_name = str(action.get("action", "")).strip().lower()

    if action_name in {"tap", "click"}:
        element = action.get("element")
        if _is_point(element):
            return {"_type": "click", "x": int(element[0]), "y": int(element[1])}
        return {"_type": "noop"}

    if action_name == "type":
        return {"_type": "type", "text": str(action.get("text", ""))}

    if action_name == "press":
        return {"_type": "press", "key": str(action.get("key", "")).lower()}

    if action_name == "back":
        return {"_type": "press", "key": "back"}

    if action_name == "home":
        return {"_type": "press", "key": "home"}

    if action_name == "scroll":
        return {
            "_type": "scroll",
            "direction": str(action.get("direction", "down")).lower(),
            "amount": int(action.get("clicks", 3)),
        }

    if action_name == "wait":
        seconds = _parse_wait_seconds(action.get("duration", action.get("seconds", 1)))
        return {"_type": "wait", "seconds": seconds}

    if action_name == "double tap":
        element = action.get("element")
        if _is_point(element):
            return {"_type": "double_click", "x": int(element[0]), "y": int(element[1])}
        return {"_type": "noop"}

    if action_name == "long press":
        element = action.get("element")
        if _is_point(element):
            return {
                "_type": "long_press",
                "x": int(element[0]),
                "y": int(element[1]),
                "duration_ms": int(action.get("duration_ms", 800)),
            }
        return {"_type": "noop"}

    if action_name == "hotkey":
        keys = action.get("keys")
        if isinstance(keys, list) and keys:
            return {"_type": "hotkey", "keys": [str(key).lower() for key in keys]}
        return {"_type": "noop"}

    return {"_type": "noop"}


def _is_point(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 2


def _parse_wait_seconds(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError("invalid wait duration")
    return float(match.group(0))


__all__ = ["parse_action", "parse_unified_action"]
