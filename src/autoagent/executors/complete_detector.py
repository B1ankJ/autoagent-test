from __future__ import annotations

import asyncio
import time
from typing import Any

from autoagent.profiles.schemas import CompleteDetection, DomStable, SendButtonReenable


async def wait_for_complete(
    page: Any,
    strategy: CompleteDetection,
    *,
    response_selector: str,
    send_button_selector: str | None = None,
    poll_interval_sec: float = 0.2,
    max_wait_sec: float | None = None,
) -> None:
    """Block until the chosen strategy reports completion. Raises TimeoutError on timeout."""

    if isinstance(strategy, DomStable):
        await _dom_stable(
            page,
            response_selector=response_selector,
            stable_sec=float(strategy.stable_sec),
            max_wait_sec=float(strategy.max_wait_sec if max_wait_sec is None else max_wait_sec),
            poll_interval_sec=poll_interval_sec,
        )
    elif isinstance(strategy, SendButtonReenable):
        if send_button_selector is None:
            raise ValueError("send_button_reenable requires send_button_selector")
        await _send_button_reenable(
            page,
            selector=send_button_selector,
            max_wait_sec=float(max_wait_sec if max_wait_sec is not None else 180),
            poll_interval_sec=poll_interval_sec,
        )
    else:
        raise ValueError(f"unsupported completion strategy: {type(strategy).__name__}")


async def _dom_stable(
    page: Any,
    *,
    response_selector: str,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float,
) -> None:
    deadline = time.monotonic() + max_wait_sec
    last_text: str | None = None
    stable_since: float | None = None

    while time.monotonic() < deadline:
        text = await page.inner_text(response_selector)
        now = time.monotonic()
        if text == last_text:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_sec:
                return
        else:
            last_text = text
            stable_since = None
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"dom_stable not reached within {max_wait_sec}s")


async def _send_button_reenable(
    page: Any,
    *,
    selector: str,
    max_wait_sec: float,
    poll_interval_sec: float,
) -> None:
    deadline = time.monotonic() + max_wait_sec
    saw_disabled = False

    while time.monotonic() < deadline:
        disabled = await page.is_disabled(selector)
        if disabled:
            saw_disabled = True
        elif saw_disabled:
            return
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"send_button_reenable not reached within {max_wait_sec}s")
