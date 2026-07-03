from unittest.mock import MagicMock

import pytest

from autoagent.executors.android_action_runner import AndroidActionRunner
from autoagent.profiles.schemas import ActionStep, Locator


@pytest.mark.asyncio
async def test_click_locator_dispatches_to_u2() -> None:
    device = MagicMock()
    target = MagicMock()
    target.click.return_value = None
    device.return_value = target

    runner = AndroidActionRunner(device=device, input_controller=MagicMock(), action_log=[])
    await runner.run(
        [ActionStep(action="click_locator", locator=Locator(type="text", value="发送"))]
    )

    target.click.assert_called_once()
    assert runner.log[0]["action"] == "click_locator"


@pytest.mark.asyncio
async def test_click_locator_supports_xpath() -> None:
    device = MagicMock()
    xpath_target = MagicMock()
    device.xpath.return_value = xpath_target

    runner = AndroidActionRunner(device=device, input_controller=MagicMock(), action_log=[])
    await runner.run(
        [
            ActionStep(
                action="click_locator",
                locator=Locator(type="xpath", value='//node[@class="android.widget.FrameLayout"]'),
            )
        ]
    )

    device.xpath.assert_called_once_with('//node[@class="android.widget.FrameLayout"]')
    xpath_target.click.assert_called_once()


@pytest.mark.asyncio
async def test_tap_xy_records_coordinates_in_action_log() -> None:
    device = MagicMock()

    runner = AndroidActionRunner(device=device, input_controller=MagicMock(), action_log=[])
    await runner.run([ActionStep(action="tap_xy", x=320, y=640)])

    device.click.assert_called_once_with(320, 640)
    assert runner.log[0]["action"] == "tap_xy"
    assert runner.log[0]["x"] == 320
    assert runner.log[0]["y"] == 640


@pytest.mark.asyncio
async def test_input_without_locator_types_into_focused_field() -> None:
    from unittest.mock import AsyncMock

    device = MagicMock()
    input_ctl = MagicMock()
    input_ctl.set_text = AsyncMock()

    runner = AndroidActionRunner(device=device, input_controller=input_ctl, action_log=[])
    # locator omitted — should NOT raise AttributeError, should pass None.
    await runner.run([ActionStep(action="input", text="你好世界")])

    input_ctl.set_text.assert_awaited_once_with(None, "你好世界")
    assert runner.log[0]["action"] == "input"
    assert runner.log[0]["ok"] is True


@pytest.mark.asyncio
async def test_input_with_locator_passes_it_through() -> None:
    from unittest.mock import AsyncMock

    input_ctl = MagicMock()
    input_ctl.set_text = AsyncMock()
    loc = Locator(type="resource_id", value="com.example:id/input")

    runner = AndroidActionRunner(device=MagicMock(), input_controller=input_ctl, action_log=[])
    await runner.run([ActionStep(action="input", locator=loc, text="测试")])

    input_ctl.set_text.assert_awaited_once_with(loc, "测试")
