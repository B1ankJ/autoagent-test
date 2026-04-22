from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import Error

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
)

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "fake_chat.html").resolve()
FIXTURE_URL = FIXTURE.as_uri()

pytestmark = pytest.mark.playwright


def _profile() -> WebProfile:
    return WebProfile(
        name="fake",
        platform="web",
        url=FIXTURE_URL,
        browser=WebBrowserConfig(headless=True, user_data_dir=None),
        ready_check=WebReadyCheck(type="dom_selector", selector="#input", timeout_sec=10),
        recovery_path=[ActionStep(action="goto", url=FIXTURE_URL)],
        input_selector="#input",
        send_method=WebSendMethodClick(type="click_button", selector="#send"),
        response_container_selector="#responses > div[data-role='assistant']:last-child",
        new_session_action=[ActionStep(action="click", selector="#new-chat")],
        complete_detection=DomStable(type="dom_stable", stable_sec=0.8, max_wait_sec=30),
    )


async def test_single_prompt_e2e(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    responses = await executor.execute(
        Sample(id="s1", prompts=["hi"], mode="gui_pc_web", target_profile="fake"),
        _profile(),
        ctx,
    )
    assert responses == ["echo: hi"]


async def test_multi_prompt_e2e(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    responses = await executor.execute(
        Sample(id="s2", prompts=["a", "bb", "ccc"], mode="gui_pc_web", target_profile="fake"),
        _profile(),
        ctx,
    )
    assert responses == ["echo: a", "echo: bb", "echo: ccc"]


async def test_new_session_clears_history(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    responses = await executor.execute(
        Sample(
            id="s3",
            prompts=["fresh"],
            mode="gui_pc_web",
            target_profile="fake",
            new_session=True,
        ),
        _profile(),
        ctx,
    )
    assert responses == ["echo: fresh"]


async def test_bad_selector_triggers_recovery(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    bad = _profile().model_copy(update={"input_selector": "#does-not-exist"})
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    with pytest.raises(Error):
        await executor.execute(
            Sample(
                id="s4",
                prompts=["x"],
                mode="gui_pc_web",
                target_profile="fake",
                retry=0,
            ),
            bad,
            ctx,
        )
    files = list(tmp_path.rglob("*error*.png"))
    assert files, "expected at least one error_* screenshot under logs dir"
