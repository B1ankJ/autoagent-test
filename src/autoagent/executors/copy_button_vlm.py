from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from autoagent.profiles.schemas import CopyButtonVLMConfig
from autoagent.utils.http_retry import post_json_with_retry

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
_BLOCKING_DIALOG_RE = re.compile(r'["\']?blocking_dialog["\']?\s*:\s*true', re.IGNORECASE)
_DIALOG_XY_RE = re.compile(
    r'["\']?dialog_x["\']?\s*[:=]\s*(-?\d+).{0,40}?["\']?dialog_y["\']?\s*[:=]\s*(-?\d+)',
    re.DOTALL | re.IGNORECASE,
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


def _extract_dialog_coords(content: str) -> tuple[int, int] | None:
    """Best-effort parse of the optional blocking_dialog/dialog_x/dialog_y
    fields (only sent/expected when detect_auth_dialog is on)."""
    if not content or not _BLOCKING_DIALOG_RE.search(content):
        return None
    try:
        m = _BRACE_RE.search(content)
        parsed = json.loads(m.group(0)) if m else None
        if isinstance(parsed, dict) and parsed.get("blocking_dialog") is True:
            coords = _coerce_xy(
                {"x": parsed.get("dialog_x"), "y": parsed.get("dialog_y")}
            )
            if coords is not None:
                return coords
    except (ValueError, TypeError):
        pass
    m = _DIALOG_XY_RE.search(content)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


_DEFAULT_PROMPT = (
    "请在这张 Android 截图中找到最新一条 AI 回复下方的“复制”按钮。"
    "它可能呈现为：(1) 文字“复制”或“Copy”；"
    "(2) 两个矩形重叠的图标（剪贴板/复制图标，常与“点赞/点踩/重新生成/分享”等图标排在同一行）；"
    "(3) 一张折角文档图标，紧挨着其它操作按钮。"
    "如果同一截图里出现多个复制按钮，请返回属于最新一条 AI 回复的那个（通常位于屏幕下半部分）。"
    "返回严格 JSON，不要任何额外文字。"
    "找到则返回 {\"found\": true, \"x\": 横坐标像素, \"y\": 纵坐标像素}；"
    "未找到则返回 {\"found\": false}。"
    "坐标基于截图原始像素，左上角为 (0, 0)，应指向按钮的中心。"
)

# Prepended to the prompt only when detect_auth_dialog is on. Kept separate
# from _DEFAULT_PROMPT (and from a custom config.prompt) so existing profiles
# that don't opt in never see a changed prompt.
_DIALOG_DETECTION_CLAUSE = (
    "在寻找复制按钮之前，先检查当前截图是否被一个**阻挡对话的授权/同意弹窗**遮挡"
    "（例如“请确认以下信息”“同意协议”“请授权”这类卡片，通常带一个醒目的确认按钮，"
    "如“同意协议”“同意并继续”“允许”）——这种弹窗不是复制按钮，也不代表复制按钮不存在，"
    "只是暂时被挡住了。如果存在这种弹窗，请只返回 "
    "{\"blocking_dialog\": true, \"dialog_x\": 确认按钮横坐标, \"dialog_y\": 确认按钮纵坐标}，"
    "不要在这种情况下寻找复制按钮。如果没有这种弹窗，忽略以上内容，按下面的规则正常寻找复制按钮。\n\n"
)


@dataclass
class CopyButtonLocateResult:
    coords: tuple[int, int] | None
    raw_response: str
    latency_ms: int
    error: str | None = None
    # Set instead of `coords` when detect_auth_dialog is on and the VLM
    # reports a blocking consent/authorization dialog rather than a copy
    # button. The caller should tap this, wait, and retry — not treat it as
    # a miss.
    dialog_coords: tuple[int, int] | None = None


async def locate_copy_button_via_vlm(
    screenshot_png: bytes,
    config: CopyButtonVLMConfig,
) -> CopyButtonLocateResult:
    import time

    b64 = base64.b64encode(screenshot_png).decode("ascii")
    prompt = config.prompt or _DEFAULT_PROMPT
    if config.detect_auth_dialog:
        prompt = _DIALOG_DETECTION_CLAUSE + prompt
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
        resp = await post_json_with_retry(
            url=url, headers=headers, json=body, timeout_sec=config.timeout_sec
        )
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

    if config.detect_auth_dialog:
        dialog_coords = _extract_dialog_coords(content or "")
        if dialog_coords is not None:
            return CopyButtonLocateResult(None, raw, latency_ms, dialog_coords=dialog_coords)

    coords, not_found_reason = _extract_coords(content or "")
    if coords is not None:
        return CopyButtonLocateResult(coords, raw, latency_ms)
    if not_found_reason == "not_found":
        return CopyButtonLocateResult(None, raw, latency_ms, error="not_found")
    _log.warning("vlm copy-button parse failed; content=%r", (content or "")[:500])
    return CopyButtonLocateResult(None, raw, latency_ms, error=not_found_reason or "parse")
