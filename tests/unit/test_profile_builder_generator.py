import pytest
from pytest_httpx import HTTPXMock

from autoagent.executors.profile_builder_generator import (
    _has_llm_config,
    apply_review_decisions,
    maybe_generate_llm_draft,
    merge_llm_draft,
    resolve_smart_draft,
)
from autoagent.models.api import VLMConfig


def test_has_llm_config_requires_triple():
    assert _has_llm_config(VLMConfig()) is False
    assert _has_llm_config(VLMConfig(base_url="u", model="m")) is False
    assert _has_llm_config(VLMConfig(base_url="u", model="m", api_key="k")) is True


def test_merge_llm_draft_none_returns_copy_of_rule_draft():
    base = {"package": "p", "activity": "a"}
    out = merge_llm_draft(base, None)
    assert out == base
    assert out is not base


def test_merge_llm_draft_overrides_only_non_empty_fields():
    base = {"package": "p", "activity": "a"}
    override = {"activity": "b", "extra": ""}
    out = merge_llm_draft(base, override)
    assert out == {"package": "p", "activity": "b"}


def test_merge_llm_draft_prefers_rule_candidates_when_llm_field_is_missing():
    rule_draft = {
        "input_locator": {"type": "xpath", "value": '//*[@class="android.widget.EditText"]'},
        "send_button_locator": {"type": "xpath", "value": '//*[@bounds="[909,2009][1020,2120]"]'},
    }
    llm_output = {
        "input_locator": {"type": "xpath", "value": '//*[@class="android.widget.EditText"]'},
    }

    merged = merge_llm_draft(rule_draft, llm_output)

    assert merged["input_locator"]["value"] == '//*[@class="android.widget.EditText"]'
    assert merged["send_button_locator"]["value"] == '//*[@bounds="[909,2009][1020,2120]"]'


def test_apply_review_decisions_updates_draft_from_review_items():
    draft = {
        "input_locator": {"type": "xpath", "value": '//*[@bounds="[1,1][2,2]"]'},
        "send_action": [{"action": "tap_xy", "x": 10, "y": 20}],
    }
    review_items = [
        {
            "field": "input_locator",
            "recommended_option": {"type": "xpath", "value": '//*[@bounds="[1,1][2,2]"]'},
            "alternative_candidates": [
                {"type": "xpath", "value": '//*[@bounds="[3,3][4,4]"]'},
            ],
        },
        {
            "field": "send_action",
            "recommended_option": [{"action": "tap_xy", "x": 10, "y": 20}],
            "alternative_candidates": [
                [{"action": "tap_xy", "x": 30, "y": 40}],
            ],
        },
    ]

    resolved, applied, pending = apply_review_decisions(
        draft,
        review_items,
        {"input_locator": 1, "send_action": 0},
    )

    assert resolved["input_locator"]["value"] == '//*[@bounds="[3,3][4,4]"]'
    assert resolved["send_action"] == [{"action": "tap_xy", "x": 10, "y": 20}]
    assert applied == {"input_locator": 1, "send_action": 0}
    assert pending == []


def test_apply_review_decisions_leaves_invalid_choices_pending():
    draft = {"input_locator": {"type": "xpath", "value": '//*[@bounds="[1,1][2,2]"]'}}
    review_items = [
        {
            "field": "input_locator",
            "recommended_option": {"type": "xpath", "value": '//*[@bounds="[1,1][2,2]"]'},
            "alternative_candidates": [],
        }
    ]

    resolved, applied, pending = apply_review_decisions(
        draft,
        review_items,
        {"input_locator": 5},
    )

    assert resolved == draft
    assert applied == {}
    assert pending == ["input_locator"]


def test_resolve_smart_draft_merges_overrides_and_review_decisions():
    rule_draft = {
        "package": "com.aliyun.tongyi",
        "input_locator": {"type": "xpath", "value": '//*[@bounds="[1,1][2,2]"]'},
    }
    review_items = [
        {
            "field": "input_locator",
            "recommended_option": {"type": "xpath", "value": '//*[@bounds="[1,1][2,2]"]'},
            "alternative_candidates": [
                {"type": "xpath", "value": '//*[@bounds="[3,3][4,4]"]'},
            ],
        }
    ]

    result = resolve_smart_draft(
        rule_draft=rule_draft,
        review_items=review_items,
        llm_output={
            "draft_overrides": {"package": "override.pkg"},
            "review_decisions": {"input_locator": 1},
        },
    )

    assert result["draft"]["package"] == "override.pkg"
    assert result["draft"]["input_locator"]["value"] == '//*[@bounds="[3,3][4,4]"]'
    assert result["applied_review_choices"] == {"input_locator": 1}
    assert result["requires_manual_review"] is False
    assert result["auto_review_source"] == "llm"


@pytest.mark.asyncio
async def test_maybe_generate_returns_none_when_vlm_incomplete():
    out = await maybe_generate_llm_draft(
        rule_draft={"package": "p"},
        candidates={},
        captures={},
        vlm=VLMConfig(base_url="u", model="m"),
    )
    assert out is None


@pytest.mark.asyncio
async def test_maybe_generate_llm_draft_returns_none_without_config():
    out = await maybe_generate_llm_draft(
        vlm=VLMConfig(),
        rule_draft={
            "input_locator": {"type": "xpath", "value": '//*[@class="android.widget.EditText"]'}
        },
        candidates={
            "input_candidates": [],
            "send_candidates": [],
            "response_candidates": [],
            "review_items": [],
        },
        captures={},
    )
    assert out is None


@pytest.mark.asyncio
async def test_maybe_generate_llm_draft_parses_json_response(httpx_mock: HTTPXMock):
    vlm = VLMConfig(
        base_url="https://llm.example.com/v1",
        model="test-model",
        api_key="sk-test",
    )
    httpx_mock.add_response(
        url="https://llm.example.com/v1/chat/completions",
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"send_button_locator":{"type":"xpath",'
                            '"value":"//*[@bounds=\\"[909,2009][1020,2120]\\"]"}}'
                        )
                    }
                }
            ]
        },
    )

    result = await maybe_generate_llm_draft(
        vlm=vlm,
        rule_draft={
            "input_locator": {"type": "xpath", "value": '//*[@class="android.widget.EditText"]'}
        },
        candidates={
            "input_candidates": [],
            "send_candidates": [],
            "response_candidates": [],
            "review_items": [],
        },
        captures={},
    )

    assert result == {
        "draft_overrides": {
            "send_button_locator": {
                "type": "xpath",
                "value": '//*[@bounds="[909,2009][1020,2120]"]',
            }
        },
        "review_decisions": {},
    }
