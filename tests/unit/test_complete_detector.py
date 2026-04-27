from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from autoagent.executors.complete_detector import wait_for_complete
from autoagent.profiles.schemas import DomStable, SendButtonReenable


async def test_dom_stable_returns_when_text_stops_changing() -> None:
    page = AsyncMock()
    texts = iter(["a", "ab", "abc", "abc", "abc", "abc", "abc"])
    page.inner_text = AsyncMock(side_effect=lambda *_a, **_kw: next(texts))
    page.evaluate = AsyncMock(side_effect=NotImplementedError("mock"))

    await wait_for_complete(
        page,
        DomStable(type="dom_stable", stable_sec=0.15, max_wait_sec=5),
        response_selector="#responses",
        poll_interval_sec=0.05,
    )
    assert page.inner_text.await_count >= 4


async def test_dom_stable_times_out() -> None:
    page = AsyncMock()
    counter = {"i": 0}

    async def never_stable(*_a, **_kw):
        counter["i"] += 1
        return f"text {counter['i']}"

    page.inner_text = never_stable
    page.evaluate = AsyncMock(side_effect=NotImplementedError("mock"))
    with pytest.raises(TimeoutError):
        await wait_for_complete(
            page,
            DomStable(type="dom_stable", stable_sec=0.2, max_wait_sec=0.4),
            response_selector="#responses",
            poll_interval_sec=0.05,
        )


async def test_send_button_reenable_waits_for_enabled() -> None:
    page = AsyncMock()
    states = iter([True, True, False, False])
    page.is_disabled = AsyncMock(side_effect=lambda *_a, **_kw: next(states))
    await wait_for_complete(
        page,
        SendButtonReenable(type="send_button_reenable"),
        response_selector="#responses",
        send_button_selector="#send",
        poll_interval_sec=0.05,
        max_wait_sec=5,
    )
    assert page.is_disabled.await_count >= 3


async def test_send_button_reenable_times_out() -> None:
    page = AsyncMock()
    page.is_disabled = AsyncMock(return_value=True)
    with pytest.raises(TimeoutError):
        await wait_for_complete(
            page,
            SendButtonReenable(type="send_button_reenable"),
            response_selector="#responses",
            send_button_selector="#send",
            poll_interval_sec=0.05,
            max_wait_sec=0.3,
        )


async def test_send_button_reenable_requires_button_selector() -> None:
    page = AsyncMock()
    with pytest.raises(ValueError, match="send_button_selector"):
        await wait_for_complete(
            page,
            SendButtonReenable(type="send_button_reenable"),
            response_selector="#responses",
            send_button_selector=None,
            poll_interval_sec=0.05,
            max_wait_sec=1,
        )
