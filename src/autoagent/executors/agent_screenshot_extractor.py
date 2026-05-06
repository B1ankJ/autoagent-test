from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.response_llm_extractor import LLMExtractionResult

_SYSTEM_PROMPT = (
    "你是一个截图内容提取助手。用户会给你一张屏幕截图和一段定位描述。\n"
    "你的唯一任务：根据描述定位到目标消息气泡或文本区域，然后将该区域内的【全部文字】\n"
    "一字不差地原样返回，包括所有段落、换行和标点，不得截断、跳段或总结。\n"
    "如果目标区域包含多个段落，全部拼接后一起返回。\n"
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

_TEXT_ENTRY_SCHEMA = {
    "name": "screenshot_text_entry_verification",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "present": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["present", "reason"],
    },
}


@dataclass
class TextEntryVerificationResult:
    matched: bool
    message: str
    error: str | None = None
    latency_ms: int = 0
    status_code: int | None = None


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
                    {
                        "type": "text",
                        "text": (
                            f"定位目标：{response_hint}\n"
                            "请将该目标区域内的所有文字完整提取，包括每一段、每一行，"
                            "不要只取最后一段或做任何摘要。"
                        ),
                    },
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


async def verify_text_entry_in_screenshot(
    *,
    screenshot: Screenshot,
    expected_text: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
) -> TextEntryVerificationResult:
    timeout = httpx.Timeout(timeout_sec)
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个截图校验助手。用户会给你一张截图和一段期望输入文本。\n"
                    "你的任务：判断这段文本是否已经真实出现在输入框或可编辑文本区域中。\n"
                    "不要把聊天回复区、历史消息、按钮文案或其他位置的相同文本算作输入成功。\n"
                    "严格按给定 JSON schema 返回。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot.base64_data}"},
                    },
                    {
                        "type": "text",
                        "text": f"请判断输入框中是否已经出现这段文字：{expected_text}",
                    },
                ],
            },
        ],
        "response_format": {"type": "json_schema", "json_schema": _TEXT_ENTRY_SCHEMA},
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
        return TextEntryVerificationResult(False, "", error="timeout")
    except httpx.HTTPError:
        return TextEntryVerificationResult(False, "", error="connect")

    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code >= 400:
        error = "auth" if resp.status_code in (401, 403) else "response_shape"
        return TextEntryVerificationResult(
            False,
            "",
            error=error,
            latency_ms=latency_ms,
            status_code=resp.status_code,
        )

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        text = _parse_content(content)
        parsed = json.loads(text)
        present = bool(parsed["present"])
        reason = str(parsed["reason"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return TextEntryVerificationResult(
            False,
            "",
            error="response_shape",
            latency_ms=latency_ms,
            status_code=resp.status_code,
        )

    return TextEntryVerificationResult(
        matched=present,
        message=reason,
        error=None,
        latency_ms=latency_ms,
        status_code=resp.status_code,
    )
