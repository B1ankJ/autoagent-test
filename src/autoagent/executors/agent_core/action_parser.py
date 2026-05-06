from __future__ import annotations

import logging
import re

_log = logging.getLogger(__name__)

# Matches: Action: name(args)
_ACTION_RE = re.compile(r"Action:\s*(\w+)\(([^)]*)\)", re.DOTALL)


def parse_action(text: str) -> dict:
    """Parse a VLM response into a structured action dict.

    Expected format:  Action: click(850, 420)
    On parse failure: returns {"_type": "noop"}
    """
    match = _ACTION_RE.search(text)
    if not match:
        _log.debug("action_parser: no action found in %r", text[:100])
        return {"_type": "noop"}

    name = match.group(1).lower()
    raw_args = match.group(2).strip()

    try:
        return _dispatch(name, raw_args)
    except Exception:  # noqa: BLE001
        _log.debug("action_parser: failed to parse args for %r: %r", name, raw_args)
        return {"_type": "noop"}


def _dispatch(name: str, raw_args: str) -> dict:
    if name == "click":
        parts = [p.strip() for p in raw_args.split(",")]
        return {"_type": "click", "x": int(parts[0]), "y": int(parts[1])}

    if name == "type":
        text = _unquote(raw_args)
        return {"_type": "type", "text": text}

    if name == "finish":
        message = _unquote(raw_args)
        return {"_type": "finish", "message": message}

    if name == "scroll":
        parts = [p.strip() for p in raw_args.split(",")]
        direction = parts[0].strip("\"'")
        amount = int(parts[1]) if len(parts) > 1 else 3
        return {"_type": "scroll", "direction": direction, "amount": amount}

    if name == "press":
        key = _unquote(raw_args) if raw_args.startswith(('"', "'")) else raw_args.strip()
        return {"_type": "press", "key": key}

    return {"_type": "noop"}


def _unquote(s: str) -> str:
    """Strip surrounding single or double quotes."""
    s = s.strip()
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        return s[1:-1]
    return s
