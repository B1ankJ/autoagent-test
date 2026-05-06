from __future__ import annotations

import json
import time
from typing import Any

import httpx

from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.response_llm_extractor import LLMExtractionResult

_SYSTEM_PROMPT = (
    "你是一个截图内容提取助手。用户会给你一张屏幕截图和一段内容描述。\n"
    "你的唯一任务：从截图中找到并完整提取描述所指的文字内容，原样返回，不做改写或总结。\n"
    "如果找不到目标内容，返回空字符串。严格按给定 JSON schema 返回。"
)

_RESPONSE_SCHEMA = {
    "name": "screenshot_response_extraction",
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


def _parse_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = [c.get("text", "") for c in content if isinstance(c, dict)]
        return "".join(chunks)
    raise ValueError("unsupported content shape")


async def extract_response_from_screenshot(
    *,
    screenshot: Screenshot,
    response_hint: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
) -> LLMExtractionResult:
    timeout = httpx.Timeout(timeout_sec)
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot.base64_data}"},
                    },
                    {"type": "text", "text": f"请提取以下内容的文字：{response_hint}"},
                ],
            },
        ],
        "response_format": {"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/chat/completions"

    started = time.monotonic()
    try:
        async with await _make_client(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return LLMExtractionResult("", "timeout", int((time.monotonic() - started) * 1000))
    except httpx.HTTPError:
        return LLMExtractionResult("", "connect", int((time.monotonic() - started) * 1000))

    latency_ms = int((time.monotonic() - started) * 1000)
    raw_response_text = resp.text

    if resp.status_code in (401, 403):
        return LLMExtractionResult(
            "",
            "auth",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
        )
    if resp.status_code >= 400:
        return LLMExtractionResult(
            "",
            "response_shape",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
        )

    raw_message_content: str | None = None
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        text = _parse_content(content)
        raw_message_content = text
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), str):
            raise ValueError("bad response payload")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return LLMExtractionResult(
            "",
            "response_shape",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
            raw_message_content=raw_message_content,
        )

    return LLMExtractionResult(
        text=parsed["response"],
        error=None,
        latency_ms=latency_ms,
        status_code=resp.status_code,
        raw_response_text=raw_response_text,
        raw_message_content=raw_message_content,
    )
