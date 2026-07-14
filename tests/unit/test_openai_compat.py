from __future__ import annotations

import pytest

from autoagent.models.api import SampleResult
from autoagent.openai_compat.chat_completions import (
    OpenAICompatError,
    build_chat_completion_response,
    build_sample_from_request,
    ensure_supported_request,
    mode_for_profile,
    parse_chat_completions_request,
    resolve_profile,
    select_effective_response,
    select_message_content,
)
from autoagent.openai_compat.schemas import ChatCompletionsRequest
from autoagent.profiles.schemas import ApiProfile, WebProfile


def _api_profile() -> ApiProfile:
    return ApiProfile.model_validate(
        {
            "name": "p_api",
            "platform": "api",
            "api": {
                "base_url": "https://api.example.com/v1",
                "model": "m",
                "api_key": "OPENAI_TEST_KEY",
            },
        }
    )


def _web_profile_with_llm() -> WebProfile:
    return WebProfile.model_validate(
        {
            "name": "p_web",
            "platform": "web",
            "url": "file:///tmp/fake.html",
            "ready_check": {"type": "dom_selector", "selector": "#input"},
            "recovery_path": [],
            "input_selector": "#input",
            "send_method": {"type": "keyboard"},
            "response_container_selector": "#responses",
            "complete_detection": {"type": "dom_stable"},
            "base_url": "https://llm.example.com/v1",
            "model": "vlm",
            "api_key": "secret",
        }
    )


def test_request_rejects_stream_true():
    body = ChatCompletionsRequest.model_validate(
        {
            "model": "p_api",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }
    )

    with pytest.raises(OpenAICompatError) as exc:
        ensure_supported_request(body)

    assert exc.value.status_code == 400
    assert exc.value.param == "stream"


def test_parser_wraps_validation_error_as_compat_error():
    with pytest.raises(OpenAICompatError) as exc:
        parse_chat_completions_request({"messages": [{"role": "user", "content": "hi"}]})

    assert exc.value.status_code == 400
    assert exc.value.param == "model"


def test_request_ignores_sampling_params():
    body = ChatCompletionsRequest.model_validate(
        {
            "model": "p_api",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.7,
            "max_tokens": 256,
            "max_completion_tokens": 256,
            "top_p": 0.9,
            "stop": ["\n"],
            "user": "abc",
        }
    )

    ensure_supported_request(body)


def test_build_sample_uses_last_user_message():
    body = ChatCompletionsRequest.model_validate(
        {
            "model": "p_api",
            "messages": [
                {"role": "system", "content": "ignore"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "also ignore"},
                {"role": "user", "content": "last"},
            ],
            "new_session": True,
            "timeout_sec": 123,
            "retry": 1,
            "dry_run": True,
            "metadata": {"tag": "sdk"},
        }
    )

    sample = build_sample_from_request(body, _api_profile())

    assert sample.prompts == ["last"]
    assert sample.target_profile == "p_api"
    assert sample.mode == "api"
    assert sample.new_session is True
    assert sample.timeout_sec == 123
    assert sample.retry == 1
    assert sample.dry_run is True
    assert sample.metadata == {"tag": "sdk"}


def test_build_sample_accepts_assistant_as_last_message():
    body = ChatCompletionsRequest.model_validate(
        {
            "model": "p_api",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "assistant prompt"},
            ],
        }
    )

    sample = build_sample_from_request(body, _api_profile())

    assert sample.prompts == ["assistant prompt"]


def test_mode_for_profile_maps_web_to_gui_pc_web():
    assert mode_for_profile(_web_profile_with_llm()) == "gui_pc_web"


def test_select_message_content_prefers_successful_llm_result():
    result = SampleResult(
        id="s1",
        status="done",
        prompts_sent=["hi"],
        responses=["static result"],
        llm_responses=["llm result"],
        llm_errors=[None],
        mode="gui_pc_web",
        target_profile="p_web",
    )

    assert select_message_content(result, _web_profile_with_llm()) == "llm result"


def test_select_message_content_falls_back_when_llm_failed():
    result = SampleResult(
        id="s2",
        status="done",
        prompts_sent=["hi"],
        responses=["static result"],
        llm_responses=[""],
        llm_errors=["auth"],
        mode="gui_pc_web",
        target_profile="p_web",
    )

    assert select_message_content(result, _web_profile_with_llm()) == "static result"


def test_select_message_content_falls_back_when_llm_error_slot_missing():
    result = SampleResult(
        id="s_missing_err",
        status="done",
        prompts_sent=["hi"],
        responses=["static result"],
        llm_responses=["llm result"],
        llm_errors=[],
        mode="gui_pc_web",
        target_profile="p_web",
    )

    assert select_message_content(result, _web_profile_with_llm()) == "static result"


def test_select_message_content_ignores_llm_data_when_profile_disables_it():
    # api profile has no llm_response_enabled() at all — matches the
    # `getattr(..., lambda: False)` fallback in select_message_content.
    result = SampleResult(
        id="s3",
        status="done",
        prompts_sent=["hi"],
        responses=["static result"],
        llm_responses=["llm result"],
        llm_errors=[None],
        mode="api",
        target_profile="p_api",
    )

    assert select_message_content(result, _api_profile()) == "static result"


# --- select_effective_response: shared by select_message_content and the
# batch-list preview (api/batches.py::_single_sample_preview), so both agree
# on what "the response" is for a sample. ---


def test_select_effective_response_prefers_llm_when_successful():
    assert select_effective_response(["raw"], ["llm"], [None]) == "llm"


def test_select_effective_response_falls_back_on_llm_error():
    assert select_effective_response(["raw"], [""], ["auth"]) == "raw"


def test_select_effective_response_falls_back_when_llm_lists_empty():
    assert select_effective_response(["raw"], [], []) == "raw"


def test_select_effective_response_falls_back_when_llm_text_empty():
    assert select_effective_response(["raw"], [""], [None]) == "raw"


def test_select_effective_response_empty_when_no_responses_at_all():
    assert select_effective_response([], [], []) == ""


def test_non_text_message_content_is_rejected_by_compat_layer():
    body = ChatCompletionsRequest.model_validate(
        {
            "model": "p_api",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "hi"}],
                }
            ],
        }
    )

    with pytest.raises(OpenAICompatError) as exc:
        ensure_supported_request(body)

    assert exc.value.status_code == 400
    assert exc.value.param == "messages"


def test_build_chat_completion_response_includes_x_autoagent():
    body = ChatCompletionsRequest.model_validate(
        {"model": "p_api", "messages": [{"role": "user", "content": "hi"}]}
    )
    result = SampleResult(
        id="chatcmpl_s3",
        status="done",
        prompts_sent=["hi"],
        responses=["hello"],
        mode="api",
        target_profile="p_api",
    )

    response = build_chat_completion_response(body, result, _api_profile())

    assert response.id == "chatcmpl_s3"
    assert response.choices[0].message.content == "hello"
    assert response.x_autoagent.sample_id == "chatcmpl_s3"
    assert response.x_autoagent.responses == ["hello"]


def test_resolve_profile_invalid_name_returns_compat_error():
    with pytest.raises(OpenAICompatError) as exc:
        resolve_profile("../bad")

    assert exc.value.status_code == 400
    assert exc.value.param == "model"
