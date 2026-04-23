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
