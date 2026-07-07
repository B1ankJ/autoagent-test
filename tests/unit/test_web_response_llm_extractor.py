import httpx
import pytest

from autoagent.executors.web_response_llm_extractor import extract_web_response_via_llm


def _mock(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_extract_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"response": "Hello from AI"}'}}]},
        )

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_web_response_via_llm(
        prompt="hi",
        html="<div class='reply'>Hello from AI</div>",
        base_url="https://api/v1",
        model="m",
        api_key="k",
    )
    assert r.text == "Hello from AI"
    assert r.error is None
    assert r.latency_ms >= 0
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_extract_empty_response_is_not_error(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"response": ""}'}}]})

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error is None


@pytest.mark.asyncio
async def test_extract_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="bad"
    )
    assert r.text == ""
    assert r.error == "auth"
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_extract_response_shape_failure(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        return handler(httpx.Request("POST", url, json=json))

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error == "response_shape"


@pytest.mark.asyncio
async def test_extract_connect_error(monkeypatch):
    async def _post(*, url, headers, json, timeout_sec, max_attempts=3):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor.post_json_with_retry", _post
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error == "connect"


@pytest.mark.asyncio
async def test_extract_truncates_oversized_html(monkeypatch):
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
        "autoagent.executors.web_response_llm_extractor.post_json_with_retry", _post
    )
    huge = "x" * 300_000
    r = await extract_web_response_via_llm(
        prompt="hi",
        html=huge,
        base_url="https://api/v1",
        model="m",
        api_key="k",
        max_html_chars=120_000,
    )
    assert r.text == "ok"
    assert r.error == "truncated"
    assert r.truncated_input is True
    assert captured["len"] < 300_000 + 5000
