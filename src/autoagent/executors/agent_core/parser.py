from __future__ import annotations

import ast
import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)
_ACTION_RE = re.compile(r"Action:\s*(\w+)\(([^)]*)\)", re.DOTALL)


def parse_action(text: str) -> dict[str, Any]:
    """Parse an agent response into the unified action contract."""
    original = text or ""
    candidate = _normalize_text(original)
    if not candidate:
        return _noop(original)

    if candidate.startswith("do("):
        action = _parse_do_action(candidate)
        return action if action is not None else _noop(original)

    if candidate.startswith("finish("):
        action = _parse_finish_action(candidate)
        return action if action is not None else _noop(original)

    action = _parse_legacy_action(candidate)
    if action is not None:
        return action

    _log.debug("parser: no action found in %r", original[:200])
    return _noop(original)


def _normalize_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""

    answer_match = _ANSWER_RE.search(stripped)
    if answer_match:
        return answer_match.group(1).strip()

    starts = [
        index
        for index in (
            stripped.find("do(action="),
            stripped.find("finish(message="),
            stripped.find("Action:"),
        )
        if index >= 0
    ]
    if starts:
        return stripped[min(starts) :].strip()
    return stripped


def _parse_do_action(text: str) -> dict[str, Any] | None:
    values = _parse_call_keywords(text, "do")
    if values is None:
        return None

    action = values.get("action")
    if not isinstance(action, str) or not action.strip():
        return None

    payload = {"_metadata": "do"}
    payload.update(values)
    return payload


def _parse_finish_action(text: str) -> dict[str, Any] | None:
    values = _parse_call_keywords(text, "finish")
    if values is not None:
        message = values.get("message")
        if isinstance(message, str):
            return {"_metadata": "finish", "message": message}

    fallback = re.fullmatch(r"finish\s*\(\s*message\s*=\s*(.+)\s*\)", text, re.DOTALL)
    if fallback is None:
        return None
    return {"_metadata": "finish", "message": _unquote(fallback.group(1))}


def _parse_call_keywords(text: str, expected_name: str) -> dict[str, Any] | None:
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        _log.debug("parser: failed to parse %s action %r", expected_name, text[:200])
        return None

    if not isinstance(tree.body, ast.Call):
        return None

    call = tree.body
    if not isinstance(call.func, ast.Name) or call.func.id != expected_name or call.args:
        return None

    try:
        return {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords if kw.arg is not None}
    except (ValueError, SyntaxError):
        _log.debug("parser: failed to evaluate %s action keywords %r", expected_name, text[:200])
        return None


def _parse_legacy_action(text: str) -> dict[str, Any] | None:
    match = _ACTION_RE.search(text)
    if not match:
        return None

    name = match.group(1).lower()
    raw_args = match.group(2).strip()

    try:
        if name == "click":
            x, y = _parse_click_args(raw_args)
            return {"_metadata": "do", "action": "Tap", "element": [x, y]}

        if name == "type":
            return {"_metadata": "do", "action": "Type", "text": _unquote(raw_args)}

        if name == "press":
            key = _parse_press_arg(raw_args)
            if key == "back":
                return {"_metadata": "do", "action": "Back"}
            if key == "home":
                return {"_metadata": "do", "action": "Home"}
            return {"_metadata": "do", "action": "Press", "key": key}

        if name == "scroll":
            direction, clicks = _parse_scroll_args(raw_args)
            return {
                "_metadata": "do",
                "action": "Scroll",
                "direction": direction,
                "clicks": clicks,
            }

        if name == "finish":
            return {"_metadata": "finish", "message": _unquote(raw_args)}
    except (TypeError, ValueError, IndexError):
        _log.debug("parser: failed to parse legacy action %r", text[:200])
        return None

    return None


def _parse_click_args(raw_args: str) -> tuple[int, int]:
    named = dict(re.findall(r"([a-zA-Z_]+)\s*=\s*(-?\d+)", raw_args))
    if "x" in named and "y" in named:
        return int(named["x"]), int(named["y"])

    parts = [part.strip() for part in raw_args.split(",")]
    if len(parts) < 2:
        raise ValueError("click requires x and y")
    return int(parts[0]), int(parts[1])


def _parse_press_arg(raw_args: str) -> str:
    if "=" in raw_args:
        _key, value = raw_args.split("=", 1)
        return _unquote(value).strip().lower()

    value = _unquote(raw_args) if raw_args.startswith(('"', "'")) else raw_args
    return value.strip().lower()


def _parse_scroll_args(raw_args: str) -> tuple[str, int]:
    named = dict(re.findall(r"([a-zA-Z_]+)\s*=\s*([a-zA-Z0-9_'\"-]+)", raw_args))
    if "direction" in named:
        direction = named["direction"].strip("\"'").lower()
        clicks = int(named.get("clicks", named.get("amount", 3)))
        return direction, clicks

    parts = [part.strip() for part in raw_args.split(",")]
    if not parts or not parts[0]:
        raise ValueError("scroll requires a direction")
    direction = parts[0].strip("\"'").lower()
    clicks = int(parts[1]) if len(parts) > 1 else 3
    return direction, clicks


def _unquote(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] in ('"', "'") and stripped[-1] == stripped[0]:
        return stripped[1:-1]
    return stripped


def _noop(raw: str) -> dict[str, str]:
    return {"_metadata": "noop", "raw": raw}
