from unittest.mock import MagicMock

import pytest

from autoagent.executors.android_input import AndroidInput, resolve_input_method
from autoagent.profiles.schemas import Locator


def test_auto_uses_adb_keyboard_for_non_ascii() -> None:
    assert resolve_input_method("auto", "你好") == "adb_keyboard"


@pytest.mark.asyncio
async def test_set_text_supports_xpath_locator() -> None:
    device = MagicMock()
    xpath_target = MagicMock()
    device.xpath.return_value = xpath_target

    async with AndroidInput(device, "auto") as ctl:
        await ctl.set_text(
            Locator(type="xpath", value='//node[@class="android.widget.EditText"]'),
            "hello",
        )

    device.xpath.assert_called_once_with('//node[@class="android.widget.EditText"]')
    xpath_target.click.assert_called_once()
    device.shell.assert_called_once_with(["input", "text", "hello"])


@pytest.mark.asyncio
async def test_set_text_escapes_shell_input_spaces() -> None:
    device = MagicMock()
    target = MagicMock()
    device.return_value = target

    async with AndroidInput(device, "u2_send_keys") as ctl:
        await ctl.set_text(
            Locator(type="resource_id", value="demo:id/input"),
            "hello world",
        )

    target.click.assert_called_once()
    device.shell.assert_called_once_with(["input", "text", "hello%sworld"])
