from __future__ import annotations

import httpx
import pytest

from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.agent_screenshot_extractor import (
    extract_response_from_screenshot,
    verify_text_entry_in_screenshot,
)


def _mock(handler):
    return httpx.MockTransport(handler)


def _shot() -> Screenshot:
    return Screenshot(base64_data="abc123==", width=1080, height=1920)


@pytest.mark.asyncio
async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"response": "Hello from screen"}'}}]},
        )

    async def _f(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.agent_screenshot_extractor._make_client", _f)

    result = await extract_response_from_screenshot(
        screenshot=_shot(),
        response_hint="latest reply",
        base_url="https://api.example.com/v1",
        model="m",
        api_key="k",
    )

    assert result.text == "Hello from screen"
    assert result.error is None
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_extract_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async def _f(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.agent_screenshot_extractor._make_client", _f)

    result = await extract_response_from_screenshot(
        screenshot=_shot(),
        response_hint="latest reply",
        base_url="https://api.example.com/v1",
        model="m",
        api_key="bad",
    )

    assert result.text == ""
    assert result.error == "auth"
    assert result.status_code == 401


@pytest.mark.asyncio
async def test_extract_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _f(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=_mock(lambda _req: (_ for _ in ()).throw(httpx.ConnectError("refused"))),
            timeout=timeout,
        )

    monkeypatch.setattr("autoagent.executors.agent_screenshot_extractor._make_client", _f)

    result = await extract_response_from_screenshot(
        screenshot=_shot(),
        response_hint="latest reply",
        base_url="https://api.example.com/v1",
        model="m",
        api_key="k",
    )

    assert result.text == ""
    assert result.error == "connect"


@pytest.mark.asyncio
async def test_verify_text_entry_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"present": true, "reason": "text visible in input field"}'
                        }
                    }
                ]
            },
        )

    async def _f(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.agent_screenshot_extractor._make_client", _f)

    result = await verify_text_entry_in_screenshot(
        screenshot=_shot(),
        expected_text="hello",
        base_url="https://api.example.com/v1",
        model="m",
        api_key="k",
    )

    assert result.matched is True
    assert result.message == "text visible in input field"
