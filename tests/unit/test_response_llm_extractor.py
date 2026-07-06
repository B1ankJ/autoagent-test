# tests/unit/test_response_llm_extractor.py
import httpx
import pytest

from autoagent.executors.response_llm_extractor import (
    LLMExtractionResult,  # noqa: F401
    extract_response_via_llm,
)


def _mock(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_extract_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"response": "你好，我是助手。"}'}}]},
        )

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == "你好，我是助手。"
    assert r.error is None
    assert r.latency_ms >= 0
    assert r.status_code == 200
    assert r.raw_message_content == '{"response": "你好，我是助手。"}'
    assert '"choices"' in (r.raw_response_text or "")


@pytest.mark.asyncio
async def test_extract_empty_response_is_not_error(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"response": ""}'}}]}
        )

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error is None
    assert r.raw_message_content == '{"response": ""}'


@pytest.mark.asyncio
async def test_extract_response_shape_failure(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error == "response_shape"
    assert r.raw_message_content == "not-json"


@pytest.mark.asyncio
async def test_extract_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="bad"
    )
    assert r.text == ""
    assert r.error == "auth"
    assert r.status_code == 401
    assert '"bad key"' in (r.raw_response_text or "")


@pytest.mark.asyncio
async def test_extract_truncates_oversized_xml(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        captured["len"] = len(body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"response": "ok"}'}}]}
        )

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor.post_json_with_retry", _post
    )
    huge = "x" * 300_000
    r = await extract_response_via_llm(
        prompt="hi", xml=huge, base_url="https://api/v1", model="m", api_key="k",
        max_xml_chars=120_000,
    )
    assert r.text == "ok"
    assert r.error is None
    assert r.truncated_input is True
    assert captured["len"] < 300_000 + 5000  # truncated, not full huge
