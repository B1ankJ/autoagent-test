from __future__ import annotations

import ast
import logging
import re

_log = logging.getLogger(__name__)

# Matches: Action: name(args)
_ACTION_RE = re.compile(r"Action:\s*(\w+)\(([^)]*)\)", re.DOTALL)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)


def parse_action(text: str) -> dict:
    """Parse a VLM response into a structured action dict.

    Expected formats include:
    - Action: click(850, 420)
    - Action: click(x=850, y=420)
    - do(action="Tap", element=[850, 420])
    - finish(message="done")
    On parse failure: returns {"_type": "noop"}
    """
    if not text:
        return {"_type": "noop"}

    normalized = _normalize_text(text)

    try:
        if normalized.startswith("do("):
            return _parse_do_action(normalized)
        if normalized.startswith("finish("):
            return _parse_finish_action(normalized)
    except (SyntaxError, ValueError, TypeError):
        _log.debug("action_parser: failed to parse structured action %r", normalized[:200])

    match = _ACTION_RE.search(normalized)
    if not match:
        _log.debug("action_parser: no action found in %r", text[:100])
        return {"_type": "noop"}

    name = match.group(1).lower()
    raw_args = match.group(2).strip()

    try:
        return _dispatch(name, raw_args)
    except (ValueError, IndexError):
        _log.debug("action_parser: failed to parse args for %r: %r", name, raw_args)
        return {"_type": "noop"}


def _dispatch(name: str, raw_args: str) -> dict:
    if name == "click":
        return _parse_click_args(raw_args)

    if name == "type":
        text = _unquote(raw_args)
        return {"_type": "type", "text": text}

    if name == "finish":
        message = _unquote(raw_args)
        return {"_type": "finish", "message": message}

    if name == "scroll":
        direction, amount = _parse_scroll_args(raw_args)
        return {"_type": "scroll", "direction": direction, "amount": amount}

    if name == "press":
        key = _parse_press_arg(raw_args)
        return {"_type": "press", "key": key}

    return {"_type": "noop"}


def _normalize_text(text: str) -> str:
    stripped = text.strip()
    answer_match = _ANSWER_RE.search(stripped)
    if answer_match:
        return answer_match.group(1).strip()

    do_idx = stripped.find("do(action=")
    finish_idx = stripped.find("finish(message=")
    action_idx = stripped.find("Action:")
    candidates = [idx for idx in (do_idx, finish_idx, action_idx) if idx >= 0]
    if candidates:
        return stripped[min(candidates) :].strip()
    return stripped


def _parse_click_args(raw_args: str) -> dict:
    named = dict(re.findall(r"([a-zA-Z_]+)\s*=\s*(-?\d+)", raw_args))
    if "x" in named and "y" in named:
        return {"_type": "click", "x": int(named["x"]), "y": int(named["y"])}

    parts = [p.strip() for p in raw_args.split(",")]
    return {"_type": "click", "x": int(parts[0]), "y": int(parts[1])}


def _parse_scroll_args(raw_args: str) -> tuple[str, int]:
    named = dict(re.findall(r"([a-zA-Z_]+)\s*=\s*([a-zA-Z0-9_'\"-]+)", raw_args))
    if "direction" in named:
        direction = named["direction"].strip("\"'").lower()
        amount = int(named["amount"]) if "amount" in named else 3
        return direction, amount

    parts = [p.strip() for p in raw_args.split(",")]
    direction = parts[0].strip("\"'").lower()
    amount = int(parts[1]) if len(parts) > 1 else 3
    return direction, amount


def _parse_press_arg(raw_args: str) -> str:
    if "=" in raw_args:
        _key, value = raw_args.split("=", 1)
        return _unquote(value).strip().lower()
    return (_unquote(raw_args) if raw_args.startswith(('"', "'")) else raw_args.strip()).lower()


def _parse_do_action(text: str) -> dict:
    tree = ast.parse(text, mode="eval")
    if not isinstance(tree.body, ast.Call):
        raise ValueError("expected function call")

    call = tree.body
    values = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords if kw.arg}
    action_name = str(values.get("action", "")).strip().lower()

    if action_name in {"tap", "click"}:
        element = values.get("element")
        if isinstance(element, list) and len(element) >= 2:
            return {"_type": "click", "x": int(element[0]), "y": int(element[1])}

    if action_name == "double tap":
        element = values.get("element")
        if isinstance(element, list) and len(element) >= 2:
            return {"_type": "double_click", "x": int(element[0]), "y": int(element[1])}

    if action_name == "long press":
        element = values.get("element")
        duration_ms = int(values.get("duration_ms", 800))
        if isinstance(element, list) and len(element) >= 2:
            return {
                "_type": "long_press",
                "x": int(element[0]),
                "y": int(element[1]),
                "duration_ms": duration_ms,
            }

    if action_name == "type":
        text_value = values.get("text", "")
        return {"_type": "type", "text": str(text_value)}

    if action_name == "press":
        key = str(values.get("key", "")).lower()
        return {"_type": "press", "key": key}

    if action_name == "hotkey":
        keys = values.get("keys")
        if isinstance(keys, list) and keys:
            return {"_type": "hotkey", "keys": [str(key).lower() for key in keys]}

    if action_name == "back":
        return {"_type": "press", "key": "back"}

    if action_name == "home":
        return {"_type": "press", "key": "home"}

    if action_name == "swipe":
        start = values.get("start")
        end = values.get("end")
        if (
            isinstance(start, list)
            and len(start) >= 2
            and isinstance(end, list)
            and len(end) >= 2
        ):
            direction = "up" if int(end[1]) < int(start[1]) else "down"
            return {"_type": "scroll", "direction": direction, "amount": 3}

    if action_name == "scroll":
        clicks = int(values.get("clicks", 3))
        direction = str(values.get("direction", "down")).lower()
        return {"_type": "scroll", "direction": direction, "amount": clicks}

    if action_name == "wait":
        duration = values.get("duration", values.get("seconds", 1))
        seconds = _parse_wait_seconds(duration)
        return {"_type": "wait", "seconds": seconds}

    if action_name == "finish":
        return {"_type": "finish", "message": str(values.get("message", ""))}

    return {"_type": "noop"}


def _parse_finish_action(text: str) -> dict:
    finish_match = re.search(r"finish\s*\(\s*message\s*=\s*(.+?)\s*\)$", text, re.DOTALL)
    if not finish_match:
        raise ValueError("invalid finish action")
    return {"_type": "finish", "message": _unquote(finish_match.group(1))}


def _unquote(s: str) -> str:
    """Strip surrounding single or double quotes."""
    s = s.strip()
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        return s[1:-1]
    return s


def _parse_wait_seconds(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError("invalid wait duration")
    return float(match.group(0))
