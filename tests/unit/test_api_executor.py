import pytest
from pytest_httpx import HTTPXMock

from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.base import ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ApiProfile


def _make_profile(**kwargs) -> ApiProfile:
    base = {
        "name": "openai_gpt4",
        "platform": "api",
        "api": {
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4o",
            "api_key": "sk-test",
        },
    }
    base.update(kwargs)
    return ApiProfile.model_validate(base)


def _mock_chat_response(mock: HTTPXMock, content: str) -> None:
    mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={
            "id": "cmpl-1",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


async def test_single_turn(httpx_mock: HTTPXMock):
    _mock_chat_response(httpx_mock, "hello there")
    sample = Sample(id="t1", prompts=["hi"], mode="api", target_profile="openai_gpt4")
    profile = _make_profile()
    result = await ApiExecutor().execute(sample, profile, ExecutorContext())
    assert result == ["hello there"]


async def test_multi_turn_history(httpx_mock: HTTPXMock):
    _mock_chat_response(httpx_mock, "r1")
    _mock_chat_response(httpx_mock, "r2")
    sample = Sample(id="t1", prompts=["p1", "p2"], mode="api", target_profile="openai_gpt4")
    profile = _make_profile(multi_turn_mode="history")
    result = await ApiExecutor().execute(sample, profile, ExecutorContext())
    assert result == ["r1", "r2"]

    # Second request must carry prior messages
    reqs = httpx_mock.get_requests()
    import json as _json

    body2 = _json.loads(reqs[1].content)
    assert len(body2["messages"]) >= 3  # user, assistant, user


async def test_multi_turn_single_resets_history(httpx_mock: HTTPXMock):
    _mock_chat_response(httpx_mock, "a")
    _mock_chat_response(httpx_mock, "b")
    sample = Sample(id="t1", prompts=["p1", "p2"], mode="api", target_profile="openai_gpt4")
    profile = _make_profile(multi_turn_mode="single")
    await ApiExecutor().execute(sample, profile, ExecutorContext())
    import json as _json

    req2 = httpx_mock.get_requests()[1]
    body2 = _json.loads(req2.content)
    assert len(body2["messages"]) == 1


async def test_missing_api_key_raises():
    sample = Sample(id="t1", prompts=["hi"], mode="api", target_profile="openai_gpt4")
    profile_no_key = ApiProfile.model_validate(
        {
            "name": "openai_gpt4",
            "platform": "api",
            "api": {
                "base_url": "https://api.example.com/v1",
                "model": "gpt-4o",
                "api_key": "",
            },
        }
    )
    with pytest.raises(RuntimeError, match="api_key is not set"):
        await ApiExecutor().execute(sample, profile_no_key, ExecutorContext())
