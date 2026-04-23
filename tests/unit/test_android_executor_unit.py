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
    PixelStable,
    UiTreeStable,
)


@pytest.mark.asyncio
async def test_execute_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()
    reset_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        if kwargs == {"resourceId": "demo:id/newChat"}:
            return reset_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)
    xmls = iter(
        [
            '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>',
            '<hierarchy><node class="android.widget.TextView" text="echo: bb"/></hierarchy>',
        ]
    )

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return next(xmls)

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )

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
        new_session_action=[
            {
                "action": "click_locator",
                "locator": {"type": "resource_id", "value": "demo:id/newChat"},
            }
        ],
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.0, max_wait_sec=1),
    )
    sample = Sample(
        id="s1",
        prompts=["hi", "bb"],
        mode="gui_android",
        target_profile="fake_android",
        retry=0,
    )

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(
        sample,
        profile,
        ExecutorContext(device_serial="emulator-5554", verbose_logs=True),
    )

    assert out == ["echo: hi", "echo: bb"]
    device.app_start.assert_called_once_with("demo.app", None, True)
    input_target.set_text.assert_any_call("hi")
    input_target.set_text.assert_any_call("bb")
    assert send_target.click.call_count == 2
    reset_target.click.assert_called_once()


@pytest.mark.asyncio
async def test_execute_ocr_mode_uses_pixel_stable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()
    reset_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        if kwargs == {"resourceId": "demo:id/newChat"}:
            return reset_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)
    wait_pixel = MagicMock()
    wait_ui = MagicMock()

    async def fake_wait_for_pixel_stable(*_args, **_kwargs):
        wait_pixel()

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        wait_ui()
        return '<hierarchy><node class="android.widget.TextView" text="ui fallback"/></hierarchy>'

    class FakeOcrExtractor:
        async def extract(self, frames):
            assert frames == [b"raw-frame"]
            return type("R", (), {"text": "ocr result"})()

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_pixel_stable",
        fake_wait_for_pixel_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_executor.OcrExtractor",
        lambda: FakeOcrExtractor(),
    )
    device.screenshot.return_value = b"raw-frame"

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
        ready_check=AndroidReadyCheckTree(type="ui_tree_contains", text="echo", timeout_sec=1),
        recovery_path=[],
        input_locator=Locator(type="resource_id", value="demo:id/input"),
        send_button_locator=Locator(type="text", value="Send"),
        response_extraction=AndroidResponseExtraction(
            method="ocr_only",
            response_container_locator=Locator(type="resource_id", value="demo:id/list"),
            scroll_container_locator=Locator(type="resource_id", value="demo:id/list"),
            latest_bubble_match=Locator(
                type="last_child_with_class",
                value="android.widget.TextView",
            ),
        ),
        new_session_action=[
            {
                "action": "click_locator",
                "locator": {"type": "resource_id", "value": "demo:id/newChat"},
            }
        ],
        complete_detection=PixelStable(type="pixel_stable", stable_sec=0.0, max_wait_sec=1),
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

    assert out == ["ocr result"]
    wait_pixel.assert_called_once()
    wait_ui.assert_not_called()
