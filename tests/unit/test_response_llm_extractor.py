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

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == "你好，我是助手。"
    assert r.error is None
    assert r.latency_ms >= 0


@pytest.mark.asyncio
async def test_extract_empty_response_is_not_error(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"response": ""}'}}]}
        )

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error is None


@pytest.mark.asyncio
async def test_extract_response_shape_failure(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error == "response_shape"


@pytest.mark.asyncio
async def test_extract_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="bad"
    )
    assert r.text == ""
    assert r.error == "auth"


@pytest.mark.asyncio
async def test_extract_truncates_oversized_xml(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        captured["len"] = len(body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"response": "ok"}'}}]}
        )

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    huge = "x" * 300_000
    r = await extract_response_via_llm(
        prompt="hi", xml=huge, base_url="https://api/v1", model="m", api_key="k",
        max_xml_chars=120_000,
    )
    assert r.text == "ok"
    assert r.error == "truncated"
    assert captured["len"] < 300_000 + 5000  # truncated, not full huge
