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
        point = _coerce_point(action.get("element"))
        if point is not None:
            return {"_type": "click", "x": point[0], "y": point[1]}
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
        if seconds is not None:
            return {"_type": "wait", "seconds": seconds}
        return {"_type": "noop"}

    if action_name == "swipe":
        start = _coerce_point(action.get("start"))
        end = _coerce_point(action.get("end"))
        if start is not None and end is not None:
            direction = "up" if end[1] < start[1] else "down"
            return {"_type": "scroll", "direction": direction, "amount": 3}
        return {"_type": "noop"}

    if action_name == "double tap":
        point = _coerce_point(action.get("element"))
        if point is not None:
            return {"_type": "double_click", "x": point[0], "y": point[1]}
        return {"_type": "noop"}

    if action_name == "long press":
        point = _coerce_point(action.get("element"))
        duration_ms = _coerce_int(action.get("duration_ms", 800))
        if point is not None and duration_ms is not None:
            return {
                "_type": "long_press",
                "x": point[0],
                "y": point[1],
                "duration_ms": duration_ms,
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


def _coerce_point(value: Any) -> tuple[int, int] | None:
    if not _is_point(value):
        return None
    x = _coerce_int(value[0])
    y = _coerce_int(value[1])
    if x is None or y is None:
        return None
    return x, y


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_wait_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


__all__ = ["parse_action", "parse_unified_action"]
