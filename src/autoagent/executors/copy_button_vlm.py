from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass

import httpx

from autoagent.profiles.schemas import CopyButtonVLMConfig

_log = logging.getLogger(__name__)

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
        parsed = json.loads(content)
        if not parsed.get("found"):
            return CopyButtonLocateResult(None, raw, latency_ms, error="not_found")
        x = int(parsed["x"])
        y = int(parsed["y"])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        _log.warning("vlm copy-button response parse failed: %s", e)
        return CopyButtonLocateResult(None, raw, latency_ms, error="parse")

    return CopyButtonLocateResult((x, y), raw, latency_ms)
