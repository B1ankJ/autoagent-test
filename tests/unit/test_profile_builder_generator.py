import pytest
from pytest_httpx import HTTPXMock

from autoagent.config.settings import Settings
from autoagent.executors.profile_builder_generator import (
    maybe_generate_llm_draft,
    merge_llm_draft,
)


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


@pytest.mark.asyncio
async def test_maybe_generate_llm_draft_returns_none_without_config():
    settings = Settings(
        profile_builder_llm_base_url=None,
        profile_builder_llm_model=None,
        profile_builder_llm_api_key=None,
    )

    result = await maybe_generate_llm_draft(
        settings=settings,
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

    assert result is None


@pytest.mark.asyncio
async def test_maybe_generate_llm_draft_parses_json_response(httpx_mock: HTTPXMock):
    settings = Settings(
        profile_builder_llm_base_url="https://llm.example.com/v1",
        profile_builder_llm_model="test-model",
        profile_builder_llm_api_key="sk-test",
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
        settings=settings,
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
        "send_button_locator": {
            "type": "xpath",
            "value": '//*[@bounds="[909,2009][1020,2120]"]',
        }
    }
