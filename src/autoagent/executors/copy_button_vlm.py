from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from autoagent.profiles.schemas import CopyButtonVLMConfig

_log = logging.getLogger(__name__)

# Strip ```json ... ``` / ``` ... ``` / <answer>...</answer> wrappers.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_ANSWER_RE = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.DOTALL | re.IGNORECASE)
# Greedy braces: matches the outermost {...} in the cleaned text.
_BRACE_RE = re.compile(r"\{.*\}", re.DOTALL)
# Fallbacks: x=123,y=456 or "x":123,"y":456 in any order, or [123,456].
_XY_NAMED_RE = re.compile(
    r"['\"]?x['\"]?\s*[:=]\s*(-?\d+).{0,40}?['\"]?y['\"]?\s*[:=]\s*(-?\d+)",
    re.DOTALL | re.IGNORECASE,
)
_YX_NAMED_RE = re.compile(
    r"['\"]?y['\"]?\s*[:=]\s*(-?\d+).{0,40}?['\"]?x['\"]?\s*[:=]\s*(-?\d+)",
    re.DOTALL | re.IGNORECASE,
)
_LIST_RE = re.compile(r"[\[(]\s*(-?\d+)\s*,\s*(-?\d+)\s*[\])]")
# "found": false / "找不到" / "no button" → signal explicit not-found.
_NOT_FOUND_RE = re.compile(
    r'"found"\s*:\s*false|找不到|未找到|不存在|no\s+(?:copy\s+)?button',
    re.IGNORECASE,
)


def _extract_coords(content: str) -> tuple[tuple[int, int] | None, str | None]:
    """Best-effort coordinate extraction from a possibly-messy LLM reply.

    Returns (coords, explicit_not_found_reason). coords is None if nothing
    parseable was found. The reason is set only when the model explicitly
    said "not found" — distinguishing real absence from a parse failure.
    """
    if not content:
        return None, "empty"
    text = content.strip()

    # Unwrap <answer>...</answer> and ```json ... ``` fences if present.
    m = _ANSWER_RE.search(text)
    if m:
        text = m.group(1).strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()

    # Try JSON first — most reliable when the model behaves.
    parsed: Any = None
    m = _BRACE_RE.search(text)
    if m:
        for candidate in (m.group(0), text):
            try:
                parsed = json.loads(candidate)
                break
            except (ValueError, TypeError):
                continue

    if isinstance(parsed, dict):
        if parsed.get("found") is False:
            return None, "not_found"
        # Accept x/y at top level or nested under common keys.
        coords = _coerce_xy(parsed)
        if coords is None:
            for key in ("coordinates", "coord", "position", "point", "bbox"):
                nested = parsed.get(key)
                coords = _coerce_xy(nested) if nested is not None else None
                if coords is not None:
                    break
        if coords is not None:
            return coords, None

    # Regex fallbacks for messier responses.
    m = _XY_NAMED_RE.search(text) or _YX_NAMED_RE.search(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        # If the y-first pattern matched, swap so result is always (x, y).
        if _YX_NAMED_RE.search(text) and not _XY_NAMED_RE.search(text):
            a, b = b, a
        return (a, b), None
    m = _LIST_RE.search(text)
    if m:
        return (int(m.group(1)), int(m.group(2))), None

    if _NOT_FOUND_RE.search(text):
        return None, "not_found"
    return None, "parse"


def _coerce_xy(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        x = value.get("x")
        y = value.get("y")
        try:
            return int(x), int(y)
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None

_DEFAULT_PROMPT = (
    "请在这张 Android 截图中找到“复制”按钮的位置。"
    "返回严格 JSON，不要任何额外文字。"
    "如果找到，返回 {\"found\": true, \"x\": 横坐标像素, \"y\": 纵坐标像素}；"
    "如果没有可见的复制按钮，返回 {\"found\": false}。"
    "坐标基于截图原始像素，左上角为 (0, 0)。"
)


@dataclass
class CopyButtonLocateResult:
    coords: tuple[int, int] | None
    raw_response: str
    latency_ms: int
    error: str | None = None


async def locate_copy_button_via_vlm(
    screenshot_png: bytes,
    config: CopyButtonVLMConfig,
) -> CopyButtonLocateResult:
    import time

    b64 = base64.b64encode(screenshot_png).decode("ascii")
    prompt = config.prompt or _DEFAULT_PROMPT
    body = {
        "model": config.model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    url = config.base_url.rstrip("/") + "/chat/completions"

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=config.timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return CopyButtonLocateResult(
            None, "", int((time.monotonic() - started) * 1000), error="timeout"
        )
    except httpx.HTTPError as e:
        return CopyButtonLocateResult(
            None, "", int((time.monotonic() - started) * 1000), error=f"http:{e}"
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    raw = resp.text[:2000]
    if resp.status_code >= 400:
        return CopyButtonLocateResult(None, raw, latency_ms, error=f"status:{resp.status_code}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    except (KeyError, IndexError, TypeError, ValueError) as e:
        _log.warning("vlm copy-button response shape unexpected: %s", e)
        return CopyButtonLocateResult(None, raw, latency_ms, error="response_shape")

    coords, not_found_reason = _extract_coords(content or "")
    if coords is not None:
        return CopyButtonLocateResult(coords, raw, latency_ms)
    if not_found_reason == "not_found":
        return CopyButtonLocateResult(None, raw, latency_ms, error="not_found")
    _log.warning("vlm copy-button parse failed; content=%r", (content or "")[:500])
    return CopyButtonLocateResult(None, raw, latency_ms, error=not_found_reason or "parse")
