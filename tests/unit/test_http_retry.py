from __future__ import annotations

import httpx
import pytest

from autoagent.utils import http_retry
from autoagent.utils.http_retry import _parse_retry_after, post_json_with_retry


def test_parse_retry_after_seconds():
    assert _parse_retry_after("5") == 5.0
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("garbage") is None


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds(monkeypatch):
    sleeps: list[float] = []

    async def _no_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(http_retry.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    # Patch AsyncClient so post() runs through the MockTransport handler.
    real_client = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_retry.httpx, "AsyncClient", _client_factory)

    resp = await post_json_with_retry(
        url="https://x/v1/chat/completions", headers={}, json={}, timeout_sec=5
    )
    assert resp.status_code == 200
    assert calls["n"] == 2
    # Honored the Retry-After of 2s.
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_returns_last_429_after_exhausting(monkeypatch):
    async def _no_sleep(_s):
        pass

    monkeypatch.setattr(http_retry.asyncio, "sleep", _no_sleep)

    def handler(_request):
        return httpx.Response(429, text="always busy")

    real_client = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_retry.httpx, "AsyncClient", _client_factory)

    resp = await post_json_with_retry(
        url="https://x/v1", headers={}, json={}, timeout_sec=5, max_attempts=2
    )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_4xx_not_retried(monkeypatch):
    calls = {"n": 0}

    def handler(_request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    real_client = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_retry.httpx, "AsyncClient", _client_factory)

    resp = await post_json_with_retry(url="https://x/v1", headers={}, json={}, timeout_sec=5)
    assert resp.status_code == 400
    assert calls["n"] == 1  # 400 is a hard fail, no retry
