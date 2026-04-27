# src/autoagent/executors/llm_checker.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import httpx

Stage = Literal["connect", "auth", "model_not_found", "response_shape", "ok"]


@dataclass
class CheckResult:
    ok: bool
    stage: Stage
    message: str
    latency_ms: int


async def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    # Indirection so tests can monkeypatch the transport.
    return httpx.AsyncClient(timeout=timeout)


def _error_message(body: object, fallback: str) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(err, str):
            return err
    return fallback


async def check_llm_api(
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
) -> CheckResult:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 5,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    timeout = httpx.Timeout(timeout_sec)
    started = time.monotonic()
    try:
        async with (await _make_client(timeout=timeout)) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        return CheckResult(
            ok=False,
            stage="connect",
            message=f"timeout: {exc}",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError as exc:
        return CheckResult(
            ok=False,
            stage="connect",
            message=str(exc) or exc.__class__.__name__,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 401 or response.status_code == 403:
        return CheckResult(
            False, "auth", _error_message(body, f"http {response.status_code}"), latency_ms
        )
    if response.status_code == 404:
        return CheckResult(
            False, "model_not_found", _error_message(body, "model not found"), latency_ms
        )
    if response.status_code >= 400:
        msg = _error_message(body, f"http {response.status_code}")
        return CheckResult(False, "response_shape", msg, latency_ms)

    if not isinstance(body, dict):
        return CheckResult(False, "response_shape", "non-json body", latency_ms)
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return CheckResult(False, "response_shape", "empty choices", latency_ms)
    first = choices[0]
    if not isinstance(first, dict) or "message" not in first:
        return CheckResult(False, "response_shape", "missing message", latency_ms)

    return CheckResult(True, "ok", "ok", latency_ms)
