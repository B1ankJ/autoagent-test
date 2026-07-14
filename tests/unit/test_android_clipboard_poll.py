"""_poll_clipboard: copy-button tap -> clipboard check used by both the
default_coords fast path and the VLM-guided loop in android_executor.py.

Replaced a single fixed-delay read (tap, sleep 0.5s, read once) which raced
apps whose copy action populates the clipboard slightly late — a false
"miss" sent the caller on to tap a *different* coordinate while the correct
tap's copy was still in flight, sometimes overwriting it with the wrong
content. Polling keeps the same total budget but returns as soon as the
clipboard actually has something.
"""
from __future__ import annotations

import pytest

from autoagent.executors.android_executor import _poll_clipboard


class _FakeDevice:
    """clipboard becomes non-empty after `arrives_after` property reads."""

    def __init__(self, *, text: str = "copied text", arrives_after: int = 0):
        self._text = text
        self._arrives_after = arrives_after
        self.reads = 0

    @property
    def clipboard(self) -> str:
        self.reads += 1
        if self.reads > self._arrives_after:
            return self._text
        return ""


async def test_returns_immediately_when_already_populated():
    device = _FakeDevice(text="hello", arrives_after=0)
    result = await _poll_clipboard(device, budget_sec=0.1, interval_sec=0.02)
    assert result == "hello"
    assert device.reads == 1


async def test_returns_text_that_arrives_after_a_few_polls():
    # Simulates a copy action that lands slightly late — a single check at
    # t=0 would have missed it; polling should still catch it.
    device = _FakeDevice(text="late copy", arrives_after=2)
    result = await _poll_clipboard(device, budget_sec=0.5, interval_sec=0.02)
    assert result == "late copy"
    assert device.reads >= 3


async def test_returns_empty_string_when_budget_exhausted():
    device = _FakeDevice(text="never read this", arrives_after=10_000)
    result = await _poll_clipboard(device, budget_sec=0.05, interval_sec=0.02)
    assert result == ""


async def test_strips_whitespace_only_clipboard_as_empty():
    class _WhitespaceDevice:
        clipboard = "   \n  "

    result = await _poll_clipboard(_WhitespaceDevice(), budget_sec=0.03, interval_sec=0.01)
    assert result == ""


@pytest.mark.parametrize("budget_sec", [0.03, 0.05])
async def test_never_exceeds_budget_by_much(budget_sec):
    import time

    device = _FakeDevice(text="x", arrives_after=10_000)
    started = time.monotonic()
    await _poll_clipboard(device, budget_sec=budget_sec, interval_sec=0.01)
    elapsed = time.monotonic() - started
    # Generous slack for scheduler jitter — this just guards against the
    # loop ignoring the budget entirely (e.g. a stray infinite loop).
    assert elapsed < budget_sec + 0.2
