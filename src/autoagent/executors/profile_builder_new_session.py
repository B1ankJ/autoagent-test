from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx

from autoagent.models.api import VLMConfig

_RECOMMEND_TIMEOUT_SEC = 30.0
logger = logging.getLogger(__name__)


class RecommendationProviderError(RuntimeError):
    pass


_RECOMMEND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_text": {"type": "string"},
        "target_hint": {"type": "string"},
        "target_bounds": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "minItems": 4,
            "maxItems": 4,
        },
        "reason": {"type": "string"},
    },
    "required": ["reason"],
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
        "task": (
            "Recommend the best tap point for the next step of creating a brand-new "
            "conversation thread in an Android chat app."
        ),
        "step_index": step_index,
        "step_count": step_count,
        "requirements": [
            "A new session means a brand-new conversation thread, not continuing the current chat.",
            "Return exactly one tap point that advances the new-session flow.",
            "Ground the recommendation in the screenshot and XML only.",
            "Do not choose the current message input box unless it is clearly the control that creates a new conversation.",
            "Prefer controls that open navigation drawers, chat history, overflow menus, compose buttons, or explicit new conversation actions.",
            "For early steps in a multi-step flow, prefer entry points that reveal a new-conversation action instead of the existing input area.",
            "Prefer returning target_text for the exact control label so the tap point can be calibrated from XML bounds.",
            "If XML text matching is ambiguous, return target_bounds for the chosen control so the tap point can still be centered programmatically.",
            "Do not return raw x/y coordinates. Always identify the control by target_text or target_bounds.",
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
                    "You analyze Android UI captures and return only JSON matching the schema. "
                    "A new session means creating a brand-new conversation thread, not focusing the "
                    "existing message input box."
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


def _parse_bounds(raw: str | None) -> tuple[int, int, int, int] | None:
    if not raw or not raw.startswith("["):
        return None
    normalized = raw.replace("][", ",").replace("[", "").replace("]", "")
    parts = normalized.split(",")
    if len(parts) != 4:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _normalize_match_text(raw: str | None) -> str:
    return " ".join((raw or "").split()).strip().lower()


def _node_strings(node: ElementTree.Element) -> list[str]:
    return [
        _normalize_match_text(node.attrib.get("text")),
        _normalize_match_text(node.attrib.get("content-desc")),
        _normalize_match_text(node.attrib.get("resource-id")),
    ]


def _center_from_bounds(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _bounds_from_payload(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    if not all(isinstance(item, int) for item in value):
        return None
    x1, y1, x2, y2 = value
    if x2 < x1 or y2 < y1:
        return None
    return (x1, y1, x2, y2)


def _best_tap_node(
    node: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> ElementTree.Element | None:
    current: ElementTree.Element | None = node
    fallback: ElementTree.Element | None = None
    while current is not None:
        if _parse_bounds(current.attrib.get("bounds")) is not None and fallback is None:
            fallback = current
        if current.attrib.get("clickable") == "true" and _parse_bounds(current.attrib.get("bounds")):
            return current
        current = parents.get(current)
    return fallback


def _calibrate_tap_point_from_xml(
    xml_text: str,
    *,
    target_text: str | None,
    target_hint: str | None,
) -> tuple[int, int] | None:
    candidates = [
        text for text in (
            _normalize_match_text(target_text),
            _normalize_match_text(target_hint),
        ) if text
    ]
    if not candidates:
        return None
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None

    parents = {child: parent for parent in root.iter() for child in parent}

    exact_matches: list[ElementTree.Element] = []
    fuzzy_matches: list[ElementTree.Element] = []
    for node in root.iter():
        strings = [value for value in _node_strings(node) if value]
        if not strings:
            continue
        if any(candidate == value for candidate in candidates for value in strings):
            exact_matches.append(node)
            continue
        if any(candidate in value or value in candidate for candidate in candidates for value in strings):
            fuzzy_matches.append(node)

    for matches in (exact_matches, fuzzy_matches):
        for node in matches:
            tap_node = _best_tap_node(node, parents)
            if tap_node is None:
                continue
            bounds = _parse_bounds(tap_node.attrib.get("bounds"))
            if bounds is not None:
                return _center_from_bounds(bounds)
    return None


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
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        response_text = exc.response.text.strip()
        if len(response_text) > 500:
            response_text = response_text[:500] + "..."
        logger.warning(
            "new-session recommendation request failed: status=%s body=%s",
            status_code,
            response_text or "<empty>",
        )
        raise RecommendationProviderError(
            f"http {status_code}: {response_text or exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RecommendationProviderError(str(exc)) from exc
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(_content_to_text(content))
        if not isinstance(parsed, dict):
            raise ValueError("new-session recommendation must decode to an object")
        if not isinstance(parsed.get("reason"), str) or not parsed["reason"].strip():
            raise ValueError("new-session recommendation requires reason")
        calibrated_point = _calibrate_tap_point_from_xml(
            xml_text,
            target_text=parsed.get("target_text") if isinstance(parsed.get("target_text"), str) else None,
            target_hint=parsed.get("target_hint") if isinstance(parsed.get("target_hint"), str) else None,
        )
        if calibrated_point is not None:
            x, y = calibrated_point
        else:
            target_bounds = _bounds_from_payload(parsed.get("target_bounds"))
            if target_bounds is not None:
                x, y = _center_from_bounds(target_bounds)
            else:
                raise ValueError("new-session recommendation requires target_text or target_bounds")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecommendationProviderError(
            f"malformed new-session recommendation response: {exc}"
        ) from exc
    return {
        "x": x,
        "y": y,
        "reason": parsed["reason"].strip(),
    }
