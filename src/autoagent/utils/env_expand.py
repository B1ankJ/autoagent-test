from __future__ import annotations

import os
import re

ENV_VAR_RE = re.compile(r"^\$([A-Z_][A-Z0-9_]*)$")


def expand_env_value(text: str) -> str:
    match = ENV_VAR_RE.match(text)
    if not match:
        return text
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(f"environment variable {name} is not set")
    return value
