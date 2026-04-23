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
    async def fake_wait_for_ready_text(*_args, **_kwargs):
        return True
    monkeypatch.setattr(
        "autoagent.executors.android_executor._wait_for_ready_text",
        fake_wait_for_ready_text,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: None,
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
    assert input_target.click.call_count == 2
    device.shell.assert_any_call(["input", "text", "hi"])
    device.shell.assert_any_call(["input", "text", "bb"])
    assert send_target.click.call_count == 2
    reset_target.click.assert_called_once()
    log_text = (tmp_path / "ad_hoc" / "s1" / "executor.log").read_text(encoding="utf-8")
    assert "start: device=emulator-5554 package=demo.app activity=None" in log_text
    assert "prompt 1 set_text start: method=u2_send_keys" in log_text
    assert "locator=resource_id:demo:id/input" in log_text
    assert "prompt 1 extraction done: method=ui_tree_only text='echo: hi'" in log_text


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
    async def fake_wait_for_ready_text(*_args, **_kwargs):
        return True
    monkeypatch.setattr(
        "autoagent.executors.android_executor._wait_for_ready_text",
        fake_wait_for_ready_text,
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


@pytest.mark.asyncio
async def test_execute_runs_recovery_path_when_ready_check_initially_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()
    recovery_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        if kwargs == {"text": "Chat"}:
            return recovery_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    ready_states = iter(
        [
            False,
            True,
        ]
    )
    async def fake_wait_for_ready_text(*_args, **_kwargs):
        return next(ready_states)
    monkeypatch.setattr(
        "autoagent.executors.android_executor._wait_for_ready_text",
        fake_wait_for_ready_text,
    )

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
        ready_check=AndroidReadyCheckTree(type="ui_tree_contains", text="发消息", timeout_sec=1),
        recovery_path=[
            {
                "action": "click_locator",
                "locator": {"type": "text", "value": "Chat"},
            }
        ],
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
        new_session_action=[],
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
    recovery_target.click.assert_called_once()
    input_target.click.assert_called_once()
    device.shell.assert_called_once_with(["input", "text", "hi"])


@pytest.mark.asyncio
async def test_execute_writes_exception_to_executor_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    input_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ready_text(*_args, **_kwargs):
        return True

    monkeypatch.setattr(
        "autoagent.executors.android_executor._wait_for_ready_text",
        fake_wait_for_ready_text,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: None,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
        ready_check=AndroidReadyCheckTree(type="ui_tree_contains", text="发消息", timeout_sec=1),
        recovery_path=[],
        input_locator=Locator(type="resource_id", value="demo:id/input"),
        send_button_locator=Locator(type="resource_id", value="missing:id/send"),
        response_extraction=AndroidResponseExtraction(
            method="ui_tree_only",
            response_container_locator=Locator(type="resource_id", value="demo:id/list"),
            scroll_container_locator=Locator(type="resource_id", value="demo:id/list"),
            latest_bubble_match=Locator(
                type="last_child_with_class",
                value="android.widget.TextView",
            ),
        ),
        new_session_action=[],
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.0, max_wait_sec=1),
    )
    sample = Sample(
        id="s1",
        prompts=["你好"],
        mode="gui_android",
        target_profile="fake_android",
        retry=0,
    )

    with pytest.raises(AssertionError):
        await AndroidExecutor(screenshots_root=tmp_path).execute(
            sample,
            profile,
            ExecutorContext(device_serial="emulator-5554", verbose_logs=True),
        )

    log_text = (tmp_path / "ad_hoc" / "s1" / "executor.log").read_text(encoding="utf-8")
    assert "prompt 1 send click: locator=resource_id:missing:id/send" in log_text
    assert "android sample s1 failed" in log_text
