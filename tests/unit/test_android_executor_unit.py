from unittest.mock import MagicMock

import pytest

from autoagent.executors.android_executor import AndroidExecutor
from autoagent.executors.base import ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    AndroidProfile,
    AndroidReadyCheckTree,
    AndroidResponseExtraction,
    Locator,
    UiTreeStable,
)


@pytest.mark.asyncio
async def test_execute_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    device = MagicMock()
    device.dump_hierarchy.return_value = (
        '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'
    )
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
        ready_check=AndroidReadyCheckTree(type="ui_tree_contains", text="echo", timeout_sec=1),
        recovery_path=[],
        input_locator=Locator(type="resource_id", value="demo:id/input"),
        send_button_locator=Locator(type="text", value="Send"),
        response_extraction=AndroidResponseExtraction(
            method="ui_tree_only",
            response_container_locator=Locator(type="resource_id", value="demo:id/list"),
            scroll_container_locator=Locator(type="resource_id", value="demo:id/list"),
            latest_bubble_match=Locator(
                type="last_child_with_class",
                value="android.widget.TextView",
            ),
        ),
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.0, max_wait_sec=1),
    )
    sample = Sample(
        id="s1",
        prompts=["hi"],
        mode="gui_android",
        target_profile="fake_android",
        retry=0,
    )

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(
        sample,
        profile,
        ExecutorContext(device_serial="emulator-5554", verbose_logs=True),
    )

    assert out == ["echo: hi"]
