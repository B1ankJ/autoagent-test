"""Shared HTTP POST with 429/5xx-aware retry for LLM/VLM calls.

The dashscope-compatible endpoints these hit rate-limit under bursty load
(multi-device batches + copy_button_vlm + response_vlm + rule-2 judge all
share the same key). A single 429 used to fail the whole extraction; now
we honor Retry-After and back off before retrying.
"""
from __future__ import annotations

import asyncio
import email.utils
import logging
import time

import httpx

_log = logging.getLogger(__name__)

_DEFAULT_MAX_ATTEMPTS = 3
_BACKOFF_SEC = (1.0, 2.0, 4.0)
# Never sleep longer than this on a Retry-After, even if the server asks —
# a sample shouldn't hang for minutes on one 429.
_MAX_RETRY_AFTER_SEC = 30.0


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After is either delta-seconds or an HTTP-date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    delta = dt.timestamp() - time.time()
    return max(0.0, delta)


async def post_json_with_retry(
    *,
    url: str,
    headers: dict[str, str],
    json: dict,
    timeout_sec: float,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> httpx.Response:
    """POST json, retrying on 429 (Retry-After honored) and 5xx / network.

    Returns the final httpx.Response so callers keep their own status
    handling. Re-raises the last network error only if every attempt failed
    to get a response at all.
    """
    timeout = httpx.Timeout(timeout_sec)
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=json)
        except httpx.HTTPError as e:
            last_exc = e
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(_BACKOFF_SEC[min(attempt, len(_BACKOFF_SEC) - 1)])
            continue

        retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
        if not retryable or attempt == max_attempts - 1:
            return resp

        if resp.status_code == 429:
            wait = _parse_retry_after(resp.headers.get("Retry-After"))
            if wait is None:
                wait = _BACKOFF_SEC[min(attempt, len(_BACKOFF_SEC) - 1)]
            wait = min(wait, _MAX_RETRY_AFTER_SEC)
        else:
            wait = _BACKOFF_SEC[min(attempt, len(_BACKOFF_SEC) - 1)]
        _log.info(
            "http %s from %s (attempt %d/%d), retrying in %.1fs",
            resp.status_code,
            url,
            attempt + 1,
            max_attempts,
            wait,
        )
        await asyncio.sleep(wait)

    # Unreachable (loop returns or raises), but keeps type checkers happy.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("post_json_with_retry exhausted without a response")
