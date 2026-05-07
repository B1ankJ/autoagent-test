# src/autoagent/executors/response_llm_extractor.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

_SYSTEM_PROMPT = (
    "你是一个 Android 聊天 App 响应抽取器。用户会给你：\n"
    "1) 本轮用户发送的 prompt 文本；\n"
    "2) 本轮执行结束时 App 的 UI 层级 XML（Android uiautomator dump 格式，"
    "只读，代表页面当前可见节点树）。\n\n"
    "你的唯一任务：从 XML 中找到用户发送的 prompt 所对应的助手回复，"
    "把该回复的纯文本原样提取出来。\n\n"
    "定位步骤（严格按顺序）：\n"
    "1. 在 XML 各节点的 text 属性中搜索与用户 prompt 完全相同或高度相似的文本，"
    "确认该节点是用户发送的消息。\n"
    "2. 在该节点之后（XML 中排列更靠后、bounds 的 y 坐标更大的位置）寻找"
    "第一条助手回复文本。这才是本轮的目标回复，不是更早的任何历史消息。\n"
    "3. 同一条助手回复可能由多个相邻 TextView 组成，"
    "按 XML 出现顺序将它们拼接为一段文本，段落间用换行分隔。\n\n"
    "规则：\n"
    "- 只返回本轮 prompt 对应的助手回复文本；\n"
    "  不包含用户 prompt 本身、历史对话、UI 说明、按钮文案、"
    "  占位符、输入建议、底部功能栏、Toast 等无关内容。\n"
    "- 若 XML 中找不到 prompt 对应的助手回复，返回空字符串。\n"
    "- 不做改写、不做总结、不加前后缀、不输出解释。\n"
    "- 严格按给定 JSON schema 返回。"
)

_RESPONSE_SCHEMA = {
    "name": "android_response_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"response": {"type": "string"}},
        "required": ["response"],
    },
}


@dataclass
class LLMExtractionResult:
    text: str
    error: str | None
    latency_ms: int
    status_code: int | None = None
    raw_response_text: str | None = None
    raw_message_content: str | None = None
    truncated_input: bool = False


async def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _truncate_xml(xml: str, max_chars: int) -> tuple[str, bool]:
    if len(xml) <= max_chars:
        return xml, False
    part = max_chars // 3
    head = xml[:part]
    mid_start = (len(xml) - part) // 2
    middle = xml[mid_start : mid_start + part]
    tail = xml[-part:]
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


async def extract_response_via_llm(
    *,
    prompt: str,
    xml: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
    max_xml_chars: int = 120_000,
) -> LLMExtractionResult:
    trimmed, truncated = _truncate_xml(xml, max_xml_chars)
    user_payload = {"prompt": prompt, "xml": trimmed}
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
        async with (await _make_client(timeout=timeout)) as client:
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
