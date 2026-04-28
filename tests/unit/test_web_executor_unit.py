from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoagent.executors.base import ExecutorContext
from autoagent.executors.web_executor import WebExecutor
from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    ActionStep,
    DomStable,
    WebBrowserConfig,
    WebProfile,
    WebReadyCheck,
    WebSendMethodClick,
    WebSendMethodKeyboard,
)


def _profile(user_data_dir: str | None = None) -> WebProfile:
    return WebProfile(
        name="fake_site",
        platform="web",
        url="file:///tmp/fake_chat.html",
        browser=WebBrowserConfig(headless=True, user_data_dir=user_data_dir),
        ready_check=WebReadyCheck(type="dom_selector", selector="#input", timeout_sec=5),
        recovery_path=[ActionStep(action="goto", url="file:///tmp/fake_chat.html")],
        input_selector="#input",
        send_method=WebSendMethodKeyboard(type="keyboard", key="Enter"),
        response_container_selector="#responses > div[data-role='assistant']:last-child",
        new_session_action=[ActionStep(action="click", selector="#new-chat")],
        complete_detection=DomStable(type="dom_stable", stable_sec=0.1, max_wait_sec=5),
    )


def _sample(prompts: list[str], *, new_session: bool = True, retry: int = 0) -> Sample:
    return Sample(
        id="s1",
        prompts=prompts,
        mode="gui_pc_web",
        target_profile="fake_site",
        new_session=new_session,
        retry=retry,
    )


def _patch_playwright(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock()
    page.inner_text = AsyncMock(return_value="echo: hi")
    page.is_disabled = AsyncMock(return_value=False)
    # evaluate is used by _collect_text; raise to trigger inner_text fallback in tests
    page.evaluate = AsyncMock(side_effect=NotImplementedError("mock: use inner_text"))

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)
    chromium.launch_persistent_context = AsyncMock(return_value=context)

    pw = AsyncMock()
    pw.chromium = chromium
    pw.stop = AsyncMock()

    playwright_handle = MagicMock()
    playwright_handle.start = AsyncMock(return_value=pw)

    from autoagent.executors import web_executor as we

    monkeypatch.setattr(we, "async_playwright", lambda: playwright_handle)
    return page


async def test_happy_path_single_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _patch_playwright(monkeypatch)
    page.inner_text = AsyncMock(side_effect=["echo: hi", "echo: hi", "echo: hi"])
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir=None, verbose_logs=False)

    out = await executor.execute(_sample(["hi"]), _profile(), ctx)

    assert out == ["echo: hi"]
    page.goto.assert_awaited()
    page.fill.assert_awaited_with("#input", "hi", timeout=5000)
    page.keyboard.press.assert_awaited_with("Enter")


async def test_multi_prompt_loops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _patch_playwright(monkeypatch)
    page.inner_text = AsyncMock(side_effect=["a", "a", "a", "b", "b", "b", "c", "c", "c"])
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    out = await executor.execute(_sample(["1", "2", "3"]), _profile(), ctx)
    assert len(out) == 3
    assert page.fill.await_count == 3


async def test_new_session_triggers_new_session_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"], new_session=True), _profile(), ctx)
    page.click.assert_any_await("#new-chat", timeout=5000)


async def test_new_session_false_skips_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"], new_session=False), _profile(), ctx)
    for call in page.click.await_args_list:
        args, _kwargs = call
        assert args[0] != "#new-chat"


async def test_persistent_context_when_user_data_dir_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"]), _profile(user_data_dir=str(tmp_path)), ctx)
    page.fill.assert_awaited()


async def test_persistent_context_retries_after_cleaning_stale_singleton_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock()
    page.inner_text = AsyncMock(side_effect=["echo: hi", "echo: hi", "echo: hi"])
    page.is_disabled = AsyncMock(return_value=False)
    page.evaluate = AsyncMock(side_effect=NotImplementedError("mock: use inner_text"))

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    user_data_dir = tmp_path / "profile"
    user_data_dir.mkdir()
    broken_target = user_data_dir / "missing-socket-target"
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (user_data_dir / name).symlink_to(broken_target)

    chromium = AsyncMock()
    chromium.launch = AsyncMock()
    chromium.launch_persistent_context = AsyncMock(
        side_effect=[RuntimeError("TargetClosedError: BrowserType.launch_persistent_context"), context]
    )

    pw = AsyncMock()
    pw.chromium = chromium
    pw.stop = AsyncMock()

    playwright_handle = MagicMock()
    playwright_handle.start = AsyncMock(return_value=pw)

    from autoagent.executors import web_executor as we

    monkeypatch.setattr(we, "async_playwright", lambda: playwright_handle)

    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    out = await executor.execute(_sample(["hi"]), _profile(user_data_dir=str(user_data_dir)), ctx)

    assert out == ["echo: hi"]
    assert chromium.launch_persistent_context.await_count == 2
    assert not (user_data_dir / "SingletonLock").exists()
    assert not (user_data_dir / "SingletonCookie").exists()
    assert not (user_data_dir / "SingletonSocket").exists()


async def test_persistent_context_falls_back_to_system_chrome_for_google_profile_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock()
    page.inner_text = AsyncMock(side_effect=["echo: hi", "echo: hi", "echo: hi"])
    page.is_disabled = AsyncMock(return_value=False)
    page.evaluate = AsyncMock(side_effect=NotImplementedError("mock: use inner_text"))

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    user_data_dir = tmp_path / "Library" / "Application Support" / "Google" / "ChromePlaywright"
    user_data_dir.mkdir(parents=True)

    chromium = AsyncMock()
    chromium.launch = AsyncMock()
    chromium.launch_persistent_context = AsyncMock(
        side_effect=[RuntimeError("TargetClosedError: BrowserType.launch_persistent_context"), context]
    )

    pw = AsyncMock()
    pw.chromium = chromium
    pw.stop = AsyncMock()

    playwright_handle = MagicMock()
    playwright_handle.start = AsyncMock(return_value=pw)

    from autoagent.executors import web_executor as we

    monkeypatch.setattr(we, "async_playwright", lambda: playwright_handle)

    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    out = await executor.execute(_sample(["hi"]), _profile(user_data_dir=str(user_data_dir)), ctx)

    assert out == ["echo: hi"]
    assert chromium.launch_persistent_context.await_count == 2
    assert chromium.launch_persistent_context.await_args_list[0].kwargs["channel"] == "chromium"
    assert chromium.launch_persistent_context.await_args_list[1].kwargs["channel"] == "chrome"


async def test_click_button_send_method(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _patch_playwright(monkeypatch)
    prof = _profile().model_copy(
        update={"send_method": WebSendMethodClick(type="click_button", selector="#send")}
    )
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"]), prof, ctx)
    page.click.assert_any_await("#send", timeout=5000)
    page.keyboard.press.assert_not_awaited()


async def test_retry_on_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _patch_playwright(monkeypatch)
    calls = {"n": 0}

    async def flaky_fill(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("flaky")

    page.fill = AsyncMock(side_effect=flaky_fill)

    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    with pytest.raises(RuntimeError):
        await executor.execute(_sample(["hi"], retry=1), _profile(), ctx)
    # First attempt navigates; after error session is invalidated; retry navigates again
    assert page.goto.await_count >= 2


async def test_session_reused_across_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """new_session=False on second call must not re-navigate."""
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    prof = _profile()

    # First sample creates the session
    await executor.execute(_sample(["hello"], new_session=False), prof, ctx)
    goto_count_after_first = page.goto.await_count

    # Second sample with new_session=False should reuse session — no extra goto
    await executor.execute(_sample(["world"], new_session=False), prof, ctx)
    assert page.goto.await_count == goto_count_after_first


async def test_verbose_logs_captures_per_action_screenshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=True)
    await executor.execute(_sample(["hi"]), _profile(), ctx)
    assert page.screenshot.await_count >= 5
