from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from autoagent.models.api import VLMConfig

_RECOMMEND_TIMEOUT_SEC = 30.0


class RecommendationProviderError(RuntimeError):
    pass


_RECOMMEND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "x": {"type": "integer", "minimum": 0},
        "y": {"type": "integer", "minimum": 0},
        "reason": {"type": "string"},
    },
    "required": ["x", "y", "reason"],
}


def _has_vlm_config(vlm: VLMConfig | None) -> bool:
    return bool(vlm and vlm.base_url and vlm.model and vlm.api_key)


def _screenshot_data_url(screenshot_path: Path) -> str:
    encoded = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _request_payload(
    *,
    screenshot_path: Path,
    xml_text: str,
    step_index: int,
    step_count: int,
    vlm: VLMConfig,
) -> dict[str, Any]:
    prompt = {
        "task": "Recommend the best tap point for the next step of Android app new-session authoring.",
        "step_index": step_index,
        "step_count": step_count,
        "requirements": [
            "Return exactly one tap point that advances the new-session flow.",
            "Ground the recommendation in the screenshot and XML only.",
            "Keep the reason short and concrete.",
        ],
        "xml": xml_text,
    }
    return {
        "model": vlm.model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You analyze Android UI captures and return only JSON matching the schema."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
                    {
                        "type": "image_url",
                        "image_url": {"url": _screenshot_data_url(screenshot_path)},
                    },
                ],
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "profile_builder_new_session_recommendation",
                "strict": True,
                "schema": _RECOMMEND_SCHEMA,
            },
        },
    }


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_chunks = [item.get("text", "") for item in content if isinstance(item, dict)]
        combined = "".join(chunk for chunk in text_chunks if chunk)
        if combined:
            return combined
    raise ValueError("new-session recommendation response content missing text")


def recommend_tap_point(
    *,
    screenshot_path: Path,
    xml_text: str,
    step_index: int,
    step_count: int,
    vlm: VLMConfig | None,
) -> dict[str, Any]:
    if not _has_vlm_config(vlm):
        raise RecommendationProviderError("vlm unavailable")

    url = vlm.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {vlm.api_key}",
        "Content-Type": "application/json",
    }
    payload = _request_payload(
        screenshot_path=screenshot_path,
        xml_text=xml_text,
        step_index=step_index,
        step_count=step_count,
        vlm=vlm,
    )

    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=_RECOMMEND_TIMEOUT_SEC)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RecommendationProviderError(str(exc)) from exc
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(_content_to_text(content))
        if not isinstance(parsed, dict):
            raise ValueError("new-session recommendation must decode to an object")
        if not isinstance(parsed.get("x"), int) or not isinstance(parsed.get("y"), int):
            raise ValueError("new-session recommendation requires integer x/y")
        if not isinstance(parsed.get("reason"), str) or not parsed["reason"].strip():
            raise ValueError("new-session recommendation requires reason")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecommendationProviderError(
            f"malformed new-session recommendation response: {exc}"
        ) from exc
    return {
        "x": parsed["x"],
        "y": parsed["y"],
        "reason": parsed["reason"].strip(),
    }
