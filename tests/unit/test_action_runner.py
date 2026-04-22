from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from autoagent.executors.action_runner import ActionRunner
from autoagent.profiles.schemas import ActionStep
from autoagent.utils.env_expand import expand_env_value


def _mk_page() -> AsyncMock:
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    return page


async def test_goto_passes_url_and_timeout() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="goto", url="https://example.com", timeout_sec=5)])
    page.goto.assert_awaited_once_with("https://example.com", timeout=5000)


async def test_wait_for_calls_wait_for_selector() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="wait_for", selector="#send", timeout_sec=3)])
    page.wait_for_selector.assert_awaited_once_with("#send", timeout=3000)


async def test_click_calls_click() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="click", selector="#send")])
    page.click.assert_awaited_once()


async def test_sleep_sleeps_for_ms() -> None:
    import time as _time

    page = _mk_page()
    runner = ActionRunner(page)
    t0 = _time.monotonic()
    await runner.run([ActionStep(action="sleep", ms=50)])
    elapsed = _time.monotonic() - t0
    assert elapsed >= 0.04


async def test_fill_uses_selector_and_text() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="fill", selector="#input", text="hello")])
    page.fill.assert_awaited_once_with("#input", "hello", timeout=5000)


async def test_fill_expands_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOO_PASSWORD", "s3cret")
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="fill", selector="#pw", text="$FOO_PASSWORD")])
    page.fill.assert_awaited_once_with("#pw", "s3cret", timeout=5000)


async def test_fill_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_ENV_Q", raising=False)
    page = _mk_page()
    runner = ActionRunner(page)
    with pytest.raises(ValueError, match="MISSING_ENV_Q"):
        await runner.run([ActionStep(action="fill", selector="#x", text="$MISSING_ENV_Q")])


def test_expand_env_value_reads_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_TOKEN", "abc")
    assert expand_env_value("$CHAT_TOKEN") == "abc"


async def test_press_key() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="press", key="Enter")])
    page.keyboard.press.assert_awaited_once_with("Enter")


async def test_unknown_action_raises() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    with pytest.raises(ValueError, match="unknown action"):
        await runner.run([ActionStep(action="yell", text="oops")])


async def test_log_records_each_step() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run(
        [
            ActionStep(action="goto", url="https://x"),
            ActionStep(action="click", selector="#y"),
        ]
    )
    assert [entry["action"] for entry in runner.log] == ["goto", "click"]
    assert all(entry["ok"] is True for entry in runner.log)


async def test_log_captures_failure() -> None:
    page = _mk_page()
    page.click.side_effect = RuntimeError("boom")
    runner = ActionRunner(page)
    with pytest.raises(RuntimeError):
        await runner.run([ActionStep(action="click", selector="#y")])
    assert runner.log[0]["ok"] is False
    assert "boom" in runner.log[0]["error"]
