"""VLM call: "are these screenshots still a normal agent chat page?"

Used by the same-response notification rule. Sends N screenshots in one
request and asks the model to decide whether the device is still on a
sane chat-style page or has drifted (login wall, error page, wrong app,
empty list, etc.).
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)
_TIMEOUT_SEC = 30.0

_SYSTEM_PROMPT = (
    "你是一个 Android 自动化测试的页面状态评估助手。用户会给你最近 N 张同一台设备"
    "的截图,这些截图对应连续 N 轮发起的对话,且对话回复内容完全相同。\n"
    "请判断这些截图里**当前的页面是否仍然是一个正常的、可继续发送/接收消息的聊天界面**。\n"
    "正常的聊天界面通常包含:消息气泡列表、底部输入框、发送按钮 / IME 等。\n"
    "异常的页面包括(但不限于):\n"
    "- 跳转到了登录页 / 验证码 / 错误页\n"
    "- 跳转到了完全无关的功能页(设置、个人中心、商品详情等)\n"
    "- 显示了不可恢复的弹窗 / Toast 拦住了输入\n"
    "- App 崩溃 / 黑屏 / 白屏\n\n"
    "严格按 JSON schema 返回。reason 用中文,简短(≤ 50 字)说明依据。"
)

_RESPONSE_SCHEMA = {
    "name": "chat_page_judgement",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "normal": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["normal", "reason"],
    },
}


@dataclass
class JudgementResult:
    normal: bool
    reason: str
    error: str | None = None
    latency_ms: int = 0


def _image_block(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}"},
    }


async def is_normal_chat_page(
    *,
    screenshot_paths: list[Path],
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = _TIMEOUT_SEC,
) -> JudgementResult:
    if not screenshot_paths:
        return JudgementResult(normal=False, reason="", error="no_screenshots")

    started = time.monotonic()
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "下面是这台设备最近 N 次同样回复对应的连续截图(按时间顺序)。"
                "请判断当前页面是否仍是正常的聊天页。"
            ),
        }
    ]
    for path in screenshot_paths:
        try:
            content.append(_image_block(path))
        except OSError as e:
            _log.warning("vlm judge: skip unreadable %s: %s", path, e)

    if len(content) == 1:
        # All paths were unreadable.
        return JudgementResult(normal=False, reason="", error="no_readable_screenshots")

    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "response_format": {"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return JudgementResult(
            normal=False, reason="", error="timeout",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError as e:
        return JudgementResult(
            normal=False, reason="", error=f"http:{type(e).__name__}",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code in (401, 403):
        return JudgementResult(normal=False, reason="", error="auth", latency_ms=latency_ms)
    if resp.status_code >= 400:
        return JudgementResult(
            normal=False, reason="", error=f"status:{resp.status_code}", latency_ms=latency_ms
        )

    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(c.get("text", "") for c in text if isinstance(c, dict))
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("unexpected payload shape")
        normal = bool(parsed.get("normal"))
        reason = str(parsed.get("reason") or "")
        return JudgementResult(normal=normal, reason=reason, latency_ms=latency_ms)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
        return JudgementResult(
            normal=False, reason="", error=f"response_shape:{type(e).__name__}",
            latency_ms=latency_ms,
        )
