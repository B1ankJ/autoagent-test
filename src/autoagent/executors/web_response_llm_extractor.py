from __future__ import annotations

import json
import time
from typing import Any

import httpx

from autoagent.executors.response_llm_extractor import LLMExtractionResult

_SYSTEM_PROMPT = (
    "你是一个网页内容提取助手。用户会给你：\n"
    "1) 本轮用户发送给 AI 产品的 prompt 文本；\n"
    "2) 本轮页面的 HTML 片段（可能是响应容器的 outerHTML，也可能是整页 body）。\n\n"
    "你的唯一任务：从 HTML 中找出 AI 助手对用户 prompt 的最新一条回复，"
    "把该回复的纯文本内容原样抽取出来。\n\n"
    "规则：\n"
    "- 只返回助手最新一条回复的文本，不要包含用户自己的 prompt、历史消息、"
    "按钮文字、占位符、界面提示、加载动画文字等 UI 元素的内容。\n"
    "- 若 HTML 中找不到可识别的助手回复，返回空字符串。\n"
    "- 不做改写、不做总结、不加前后缀、不输出解释。\n"
    "- 严格按给定 JSON schema 返回。"
)

_RESPONSE_SCHEMA = {
    "name": "web_response_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"response": {"type": "string"}},
        "required": ["response"],
    },
}


async def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _truncate_html(html: str, max_chars: int) -> tuple[str, bool]:
    if len(html) <= max_chars:
        return html, False
    part = max_chars // 3
    head = html[:part]
    mid_start = (len(html) - part) // 2
    middle = html[mid_start : mid_start + part]
    tail = html[-part:]
    return (
        f"{head}\n<!-- truncated -->\n{middle}\n<!-- truncated -->\n{tail}",
        True,
    )


def _parse_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = [c.get("text", "") for c in content if isinstance(c, dict)]
        return "".join(chunks)
    raise ValueError("unsupported content shape")


def _clip_debug_text(value: str, max_chars: int = 4000) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}\n...<truncated {len(value) - max_chars} chars>"


async def extract_web_response_via_llm(
    *,
    prompt: str,
    html: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
    max_html_chars: int = 120_000,
) -> LLMExtractionResult:
    trimmed, truncated = _truncate_html(html, max_html_chars)
    user_payload = {"prompt": prompt, "html": trimmed}
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/chat/completions"
    timeout = httpx.Timeout(timeout_sec)

    started = time.monotonic()
    try:
        async with await _make_client(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return LLMExtractionResult(
            "",
            "timeout",
            int((time.monotonic() - started) * 1000),
            truncated_input=truncated,
        )
    except httpx.HTTPError:
        return LLMExtractionResult(
            "",
            "connect",
            int((time.monotonic() - started) * 1000),
            truncated_input=truncated,
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    raw_response_text = _clip_debug_text(resp.text)

    if resp.status_code in (401, 403):
        return LLMExtractionResult(
            "",
            "auth",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
            truncated_input=truncated,
        )
    if resp.status_code >= 400:
        return LLMExtractionResult(
            "",
            "response_shape",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
            truncated_input=truncated,
        )

    raw_message_content: str | None = None
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        text = _parse_content(content)
        raw_message_content = _clip_debug_text(text)
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), str):
            return LLMExtractionResult(
                "",
                "response_shape",
                latency_ms,
                status_code=resp.status_code,
                raw_response_text=raw_response_text,
                raw_message_content=raw_message_content,
                truncated_input=truncated,
            )
    except (KeyError, IndexError, TypeError, ValueError):
        return LLMExtractionResult(
            "",
            "response_shape",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
            raw_message_content=raw_message_content,
            truncated_input=truncated,
        )

    return LLMExtractionResult(
        text=parsed["response"],
        error="truncated" if truncated else None,
        latency_ms=latency_ms,
        status_code=resp.status_code,
        raw_response_text=raw_response_text,
        raw_message_content=raw_message_content,
        truncated_input=truncated,
    )
