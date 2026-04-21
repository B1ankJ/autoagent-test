from __future__ import annotations

import asyncio
import logging

import httpx

from autoagent.models.api import SampleResult

log = logging.getLogger(__name__)


async def send_webhook(
    url: str, result: SampleResult, *, max_retries: int = 3, base_delay: float = 0.5,
) -> bool:
    delay = base_delay
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.post(
                    url,
                    json=result.model_dump(mode="json"),
                    headers={"Content-Type": "application/json"},
                )
                if 200 <= resp.status_code < 300:
                    return True
                log.warning("webhook %s returned %s (attempt %d)", url, resp.status_code, attempt)
            except httpx.RequestError as e:
                log.warning("webhook %s error: %s (attempt %d)", url, e, attempt)
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay *= 2
    return False
