import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoagent.executors.android_executor import AndroidExecutor
from autoagent.executors.base import ExecutorContext
from autoagent.executors.copy_button_vlm import CopyButtonLocateResult
from autoagent.executors.response_llm_extractor import LLMExtractionResult
from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    AndroidProfile,
    AndroidResponseExtraction,
    CopyButtonVLMConfig,
    Locator,
    PixelStable,
    UiTreeStable,
)


@pytest.fixture(autouse=True)
def _mock_ensure_screen_awake(monkeypatch: pytest.MonkeyPatch) -> None:
    # ensure_screen_awake shells out to a real `adb` binary. It fails soft
    # (empty stdout, no exception) when adb exists but the device doesn't —
    # which is why this only ever broke in CI, not on a dev machine with
    # adb on PATH — but raises FileNotFoundError when adb isn't installed
    # at all, which every other executor dependency in these tests already
    # mocks around.
    monkeypatch.setattr("autoagent.executors.android_executor.ensure_screen_awake", lambda _s: None)


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
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
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

    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: None,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
        new_session=True,
        retry=0,
    )

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(
        sample,
        profile,
        ExecutorContext(device_serial="emulator-5554", verbose_logs=True),
    )

    assert out == ["echo: hi", "echo: bb"]
    device.app_start.assert_called_once_with("demo.app", None, False)
    assert input_target.click.call_count == 2
    device.shell.assert_any_call(["input", "text", "hi"])
    device.shell.assert_any_call(["input", "text", "bb"])
    assert send_target.click.call_count == 2
    reset_target.click.assert_called_once()
    log_text = (tmp_path / "ad_hoc" / "s1" / "executor.log").read_text(encoding="utf-8")
    assert "start: device=emulator-5554 package=demo.app activity=None" in log_text
    assert "prompt 1 set_text start: method=u2_send_keys" in log_text
    assert "locator=resource_id:demo:id/input" in log_text
    assert "captured after_input screenshot: file=after_input_1.jpg" in log_text
    assert "prompt 1 extraction done: method=ui_tree_only text='echo: hi'" in log_text
    assert (tmp_path / "ad_hoc" / "s1" / "before_input_1.jpg").is_file()
    assert (tmp_path / "ad_hoc" / "s1" / "after_input_1.jpg").is_file()
    assert (tmp_path / "ad_hoc" / "s1" / "after_send_1.jpg").is_file()
    assert (tmp_path / "ad_hoc" / "s1" / "after_result_1.xml").is_file()
    assert (tmp_path / "ad_hoc" / "s1" / "after_result_1.jpg").is_file()


@pytest.mark.asyncio
async def test_execute_activates_adb_keyboard_before_new_session_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()
    new_chat_target = MagicMock()
    events: list[str] = []

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        if kwargs == {"resourceId": "demo:id/newChat"}:
            return new_chat_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: True,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: events.append("ensure") or "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: events.append("restore"),
    )
    new_chat_target.click.side_effect = lambda *_, **__: events.append("new_session")
    input_target.click.side_effect = RuntimeError("focused by entry action")
    device.shell.side_effect = lambda args: events.append(args[0])

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
        input_focus_action=[],
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.0, max_wait_sec=1),
    )
    sample = Sample(
        id="s1",
        prompts=["hello"],
        mode="gui_android",
        target_profile="fake_android",
        new_session=True,
        retry=0,
    )

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(
        sample,
        profile,
        ExecutorContext(device_serial="emulator-5554", verbose_logs=True),
    )

    assert out == ["echo: hi"]
    assert events[:3] == ["ensure", "new_session", "am"]
    assert events[-1] == "restore"


@pytest.mark.asyncio
async def test_execute_skips_new_session_action_when_sample_does_not_request_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()
    new_chat_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        if kwargs == {"resourceId": "demo:id/newChat"}:
            return new_chat_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: None,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
    new_chat_target.click.assert_not_called()


@pytest.mark.asyncio
async def test_execute_waits_two_seconds_between_new_session_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    first_target = MagicMock()
    second_target = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()
    events: list[str] = []
    sleeps: list[float] = []

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/step1"}:
            return first_target
        if kwargs == {"resourceId": "demo:id/step2"}:
            return second_target
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_executor.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.set_ime",
        lambda _serial, _ime: None,
    )
    first_target.click.side_effect = lambda *_, **__: events.append("step1")
    second_target.click.side_effect = lambda *_, **__: events.append("step2")

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
                "locator": {"type": "resource_id", "value": "demo:id/step1"},
            },
            {
                "action": "click_locator",
                "locator": {"type": "resource_id", "value": "demo:id/step2"},
            },
        ],
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.0, max_wait_sec=1),
    )
    sample = Sample(
        id="s1",
        prompts=["hi"],
        mode="gui_android",
        target_profile="fake_android",
        new_session=True,
        retry=0,
    )

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(
        sample,
        profile,
        ExecutorContext(device_serial="emulator-5554", verbose_logs=True),
    )

    assert out == ["echo: hi"]
    assert events[:2] == ["step1", "step2"]
    assert sleeps == [2.0, 2.0, 3.0, 10]


@pytest.mark.asyncio
async def test_execute_prefers_send_action_over_send_button_locator(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    input_target = MagicMock()
    events: list[tuple[int, int] | str] = []

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"resourceId": "missing:id/send"}:
            raise AssertionError("send locator should not be resolved when send_action is present")
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    device.click.side_effect = lambda x, y: events.append((x, y))
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
        send_action=[{"action": "tap_xy", "x": 909, "y": 2038}],
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.0, max_wait_sec=1),
    )
    sample = Sample(
        id="s-send-action",
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
    assert events == [(909, 2038)]


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
    device.dump_hierarchy.return_value = "<hierarchy/>"
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

    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )
    device.screenshot.return_value = b"raw-frame"

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
async def test_execute_skips_llm_when_profile_does_not_enable_it(monkeypatch, tmp_path) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
    ctx = ExecutorContext(device_serial="emulator-5554", verbose_logs=True)

    fake_extract = AsyncMock()
    monkeypatch.setattr("autoagent.executors.android_executor.extract_response_via_llm", fake_extract)

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(sample, profile, ctx)

    assert out == ["echo: hi"]
    fake_extract.assert_not_awaited()
    assert ctx.llm_responses == []
    assert ctx.llm_errors == []


@pytest.mark.asyncio
async def test_execute_calls_llm_per_round_when_profile_enables_it(monkeypatch, tmp_path) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
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
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
        base_url="u",
        model="m",
        api_key="k",
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
        prompts=["hi", "bb"],
        mode="gui_android",
        target_profile="fake_android",
        retry=0,
    )
    ctx = ExecutorContext(device_serial="emulator-5554", verbose_logs=True)

    fake_extract = AsyncMock(
        side_effect=[
            LLMExtractionResult(
                text="LLM_A",
                error=None,
                latency_ms=10,
                status_code=200,
                raw_message_content='{"response":"LLM_A"}',
            ),
            LLMExtractionResult(
                text="",
                error="auth",
                latency_ms=5,
                status_code=401,
                raw_message_content='{"response":""}',
            ),
        ]
    )
    monkeypatch.setattr("autoagent.executors.android_executor.extract_response_via_llm", fake_extract)

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(sample, profile, ctx)

    assert out == ["echo: hi", "echo: bb"]
    assert fake_extract.await_count == 2
    assert ctx.llm_responses == ["LLM_A", ""]
    assert ctx.llm_errors == [None, "auth"]
    llm_debug = json.loads(
        (tmp_path / "ad_hoc" / "s1" / "llm_extract_1.json").read_text(encoding="utf-8")
    )
    assert llm_debug["text"] == "LLM_A"
    assert llm_debug["status_code"] == 200
    assert llm_debug["raw_message_content"] == '{"response":"LLM_A"}'
    llm_debug_2 = json.loads(
        (tmp_path / "ad_hoc" / "s1" / "llm_extract_2.json").read_text(encoding="utf-8")
    )
    assert llm_debug_2["error"] == "auth"
    log_text = (tmp_path / "ad_hoc" / "s1" / "executor.log").read_text(encoding="utf-8")
    assert "prompt 1 llm extraction: status=200 error=None" in log_text


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
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
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
    assert (tmp_path / "ad_hoc" / "s1" / "on_error.jpg").is_file()


@pytest.mark.asyncio
async def test_execute_reuses_existing_logs_dir_without_nesting(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
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
    existing_logs_dir = tmp_path / "b1" / "s1"
    existing_logs_dir.mkdir(parents=True)

    ctx = ExecutorContext(
        device_serial="emulator-5554",
        verbose_logs=True,
        logs_dir=str(existing_logs_dir),
    )
    out = await AndroidExecutor(screenshots_root=tmp_path).execute(sample, profile, ctx)

    assert out == ["echo: hi"]
    assert ctx.logs_dir == str(existing_logs_dir.resolve())
    assert (existing_logs_dir / "executor.log").is_file()
    assert not (existing_logs_dir / "s1").exists()


@pytest.mark.asyncio
async def test_copy_button_vlm_dismisses_blocking_dialog_then_finds_button(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A blocking consent/auth dialog (detect_auth_dialog=True) should be
    tapped and retried on a fresh screenshot, not treated as a miss that
    trips a wrong-coordinate tap on the next default_coords/attempt."""
    device = MagicMock()
    input_target = MagicMock()
    send_target = MagicMock()

    def lookup(**kwargs):
        if kwargs == {"resourceId": "demo:id/input"}:
            return input_target
        if kwargs == {"text": "Send"}:
            return send_target
        raise AssertionError(f"unexpected selector: {kwargs}")

    device.side_effect = lookup
    device.dump_hierarchy.return_value = "<hierarchy/>"
    device.screenshot.return_value = b"raw-frame"
    device.clipboard = ""
    clicks: list[tuple[int, int]] = []
    real_coords = (10, 20)

    def _click(x, y):
        clicks.append((x, y))
        if (x, y) == real_coords:
            device.clipboard = "copied response"

    device.click = _click

    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    async def fake_wait_for_ui_tree_stable(*_args, **_kwargs):
        return "<hierarchy/>"

    monkeypatch.setattr(
        "autoagent.executors.android_executor.wait_for_ui_tree_stable",
        fake_wait_for_ui_tree_stable,
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_input.is_package_installed",
        lambda _serial, _pkg: False,
    )
    monkeypatch.setattr("autoagent.executors.android_input.set_ime", lambda _serial, _ime: None)

    dialog_coords = (360, 752)
    vlm_results = iter(
        [
            CopyButtonLocateResult(None, "", 1, dialog_coords=dialog_coords),
            CopyButtonLocateResult(real_coords, "", 1),
        ]
    )

    async def fake_locate(_shot, _config):
        return next(vlm_results)

    monkeypatch.setattr(
        "autoagent.executors.android_executor.locate_copy_button_via_vlm", fake_locate
    )

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
        input_locator=Locator(type="resource_id", value="demo:id/input"),
        send_button_locator=Locator(type="text", value="Send"),
        response_extraction=AndroidResponseExtraction(
            method="ui_tree_only",
            response_container_locator=Locator(type="resource_id", value="demo:id/list"),
            scroll_container_locator=Locator(type="resource_id", value="demo:id/list"),
            latest_bubble_match=Locator(
                type="last_child_with_class", value="android.widget.TextView"
            ),
            copy_button_vlm=CopyButtonVLMConfig(
                base_url="https://x",
                model="m",
                api_key="k",
                detect_auth_dialog=True,
                dialog_dismiss_wait_sec=0.01,
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
        sample, profile, ExecutorContext(device_serial="emulator-5554", verbose_logs=True)
    )

    assert out == ["copied response"]
    # Dialog tapped first, then the real copy button on the retry.
    assert clicks == [dialog_coords, real_coords]
