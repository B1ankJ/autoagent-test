from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import httpx

from autoagent.models.api import VLMConfig

LLM_DRAFT_TIMEOUT_SEC = 30.0

_LOCATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string"},
        "value": {"type": "string"},
    },
    "required": ["type", "value"],
}

_LLM_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "draft_overrides": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "package": {"type": "string"},
                "activity": {"type": ["string", "null"]},
                "serial": {"type": "string"},
                "input_method": {"type": "string"},
                "ready_check": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string"},
                        "text": {"type": "string"},
                        "timeout_sec": {"type": "integer"},
                    },
                },
                "input_locator": _LOCATOR_SCHEMA,
                "send_button_locator": _LOCATOR_SCHEMA,
                "response_extraction": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "method": {"type": "string"},
                        "response_container_locator": _LOCATOR_SCHEMA,
                        "scroll_container_locator": _LOCATOR_SCHEMA,
                        "latest_bubble_match": _LOCATOR_SCHEMA,
                    },
                },
                "complete_detection": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {"type": "string"},
                        "stable_sec": {"type": "integer"},
                        "max_wait_sec": {"type": "integer"},
                    },
                },
            },
        },
        "review_decisions": {
            "type": "object",
            "additionalProperties": False,
            "propertyNames": {"pattern": "^[A-Za-z0-9_]+$"},
            "patternProperties": {"^[A-Za-z0-9_]+$": {"type": "integer", "minimum": 0}},
        },
    },
}

_SYSTEM_PROMPT = (
    "You enrich Android chat profile drafts. "
    "Return only JSON matching the provided schema. "
    "Do not invent new keys. "
    "Only include fields you want to override from the rule draft. "
    "For review_decisions, choose only among the provided review item options by zero-based index."
)


def _has_llm_config(vlm: VLMConfig) -> bool:
    return bool(vlm.base_url and vlm.model and vlm.api_key)


def _merge_values(base: Any, override: Any) -> Any:
    if override in (None, "", [], {}):
        return deepcopy(base)
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {key: deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            if key in merged:
                merged[key] = _merge_values(merged[key], value)
            elif value not in (None, "", [], {}):
                merged[key] = deepcopy(value)
        return merged
    return deepcopy(override)


def merge_llm_draft(
    rule_draft: Mapping[str, Any],
    llm_output: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not llm_output:
        return deepcopy(dict(rule_draft))
    overrides = llm_output.get("draft_overrides", llm_output)
    if not isinstance(overrides, Mapping):
        return deepcopy(dict(rule_draft))
    return _merge_values(dict(rule_draft), dict(overrides))


def _review_options(item: Mapping[str, Any]) -> list[Any]:
    return [item.get("recommended_option"), *list(item.get("alternative_candidates", []))]


def _review_payload(field: str, value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {field: deepcopy(value)}
    if isinstance(value, Mapping) and {"type", "value"}.issubset(value.keys()):
        return {field: deepcopy(dict(value))}
    if isinstance(value, Mapping):
        resolved_latest = value.get("resolved_latest_bubble_match") or value.get("latest_bubble_match")
        return {
            "response_extraction": {
                "response_container_locator": deepcopy(value.get("response_container_locator")),
                "scroll_container_locator": deepcopy(value.get("scroll_container_locator")),
                "latest_bubble_match": deepcopy(resolved_latest),
            }
        }
    return {}


def apply_review_decisions(
    draft: Mapping[str, Any],
    review_items: list[Mapping[str, Any]],
    review_decisions: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, int], list[str]]:
    resolved = deepcopy(dict(draft))
    applied: dict[str, int] = {}
    pending: list[str] = []
    decisions = dict(review_decisions or {})
    for item in review_items:
        field = item.get("field")
        if not isinstance(field, str):
            continue
        choice = decisions.get(field)
        if not isinstance(choice, int):
            pending.append(field)
            continue
        options = _review_options(item)
        if choice < 0 or choice >= len(options):
            pending.append(field)
            continue
        payload = _review_payload(field, options[choice])
        resolved = merge_llm_draft(resolved, payload)
        applied[field] = choice
    return resolved, applied, pending


def resolve_smart_draft(
    *,
    rule_draft: Mapping[str, Any],
    review_items: list[Mapping[str, Any]],
    llm_output: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = merge_llm_draft(rule_draft, llm_output)
    explicit_decisions = (
        dict(llm_output.get("review_decisions", {})) if isinstance(llm_output, Mapping) else {}
    )
    review_decisions: dict[str, int] = {}
    for item in review_items:
        field = item.get("field")
        if isinstance(field, str):
            review_decisions[field] = int(explicit_decisions.get(field, 0))
    resolved, applied, pending = apply_review_decisions(merged, review_items, review_decisions)
    return {
        "draft": resolved,
        "applied_review_choices": applied,
        "pending_review_fields": pending,
        "requires_manual_review": bool(pending),
        "auto_review_source": "llm" if review_items else "manual",
    }


def _candidate_summary(candidates: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "input_candidates": list(candidates.get("input_candidates", []))[:3],
        "send_candidates": list(candidates.get("send_candidates", []))[:3],
        "response_candidates": list(candidates.get("response_candidates", []))[:3],
        "review_items": list(candidates.get("review_items", []))[:5],
    }


def _request_payload(
    *,
    vlm: VLMConfig,
    rule_draft: Mapping[str, Any],
    candidates: Mapping[str, Any],
    captures: Mapping[str, Any],
) -> dict[str, Any]:
    user_payload = {
        "task": "Optionally improve the rule-based Android profile draft.",
        "requirements": [
            "Prefer deterministic rule fields unless there is stronger evidence in the candidates.",
            "Keep output sparse; omit any field that should remain unchanged.",
            "Never invent selectors that are not grounded in the supplied evidence.",
            "When you choose a review item, return its zero-based option index in review_decisions.",
        ],
        "rule_draft": rule_draft,
        "candidate_summary": _candidate_summary(candidates),
        "captures": captures,
    }
    return {
        "model": vlm.model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "profile_builder_llm_draft",
                "strict": True,
                "schema": _LLM_DRAFT_SCHEMA,
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
    raise ValueError("llm draft response content missing text")


def _normalize_llm_output(parsed: Mapping[str, Any]) -> dict[str, Any]:
    if "draft_overrides" in parsed or "review_decisions" in parsed:
        draft_overrides = parsed.get("draft_overrides", {})
        review_decisions = parsed.get("review_decisions", {})
        return {
            "draft_overrides": dict(draft_overrides) if isinstance(draft_overrides, Mapping) else {},
            "review_decisions": dict(review_decisions) if isinstance(review_decisions, Mapping) else {},
        }
    return {
        "draft_overrides": dict(parsed),
        "review_decisions": {},
    }


async def _request_llm_draft(
    *,
    vlm: VLMConfig,
    rule_draft: Mapping[str, Any],
    candidates: Mapping[str, Any],
    captures: Mapping[str, Any],
) -> dict[str, Any]:
    url = vlm.base_url.rstrip("/") + "/chat/completions"  # type: ignore[union-attr]
    headers = {
        "Authorization": f"Bearer {vlm.api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(LLM_DRAFT_TIMEOUT_SEC)
    payload = _request_payload(
        vlm=vlm,
        rule_draft=rule_draft,
        candidates=candidates,
        captures=captures,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"unexpected llm response shape: {data}") from exc

    parsed = json.loads(_content_to_text(content))
    if not isinstance(parsed, dict):
        raise ValueError("llm draft response must decode to an object")
    return _normalize_llm_output(parsed)


async def maybe_generate_llm_draft(
    *,
    rule_draft: Mapping[str, Any],
    candidates: Mapping[str, Any],
    captures: Mapping[str, Any],
    vlm: VLMConfig | None = None,
) -> dict[str, Any] | None:
    if vlm is None or not _has_llm_config(vlm):
        return None
    try:
        return await _request_llm_draft(
            vlm=vlm,
            rule_draft=rule_draft,
            candidates=candidates,
            captures=captures,
        )
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return None
