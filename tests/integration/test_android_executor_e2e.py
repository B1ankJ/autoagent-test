from __future__ import annotations

import os
import subprocess
from pathlib import Path

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

pytestmark = pytest.mark.android


def _adb(*args: str, serial: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


@pytest.fixture(scope="session")
def apk_path() -> Path:
    env_path = os.getenv("AUTOAGENT_FAKE_CHAT_APK")
    path = Path(env_path) if env_path else Path("tests/fixtures/fake_chat_apk/fake_chat-debug.apk")
    if not path.is_file():
        pytest.skip(f"fake chat apk not found at {path}")
    return path


@pytest.fixture(scope="session")
def android_serial() -> str:
    preferred = os.getenv("AUTOAGENT_ANDROID_SERIAL")
    if preferred:
        return preferred

    out = _adb("devices").stdout.splitlines()[1:]
    for line in out:
        cols = line.split()
        if len(cols) >= 2 and cols[1] == "device":
            return cols[0]
    pytest.skip("no adb device available for @pytest.mark.android")


@pytest.fixture(scope="session", autouse=True)
def install_fake_chat(apk_path: Path, android_serial: str) -> None:
    os.environ.setdefault("U2_UPDATE_AGENT", "0")
    _adb("install", "-r", str(apk_path), serial=android_serial)


@pytest.fixture(scope="session")
def android_profile() -> AndroidProfile:
    return AndroidProfile(
        name="fake_android",
        platform="android",
        package="com.autoagent.fakechat",
        activity=".MainActivity",
        ready_check=AndroidReadyCheckTree(type="ui_tree_contains", text="Send", timeout_sec=10),
        recovery_path=[],
        input_locator=Locator(type="resource_id", value="com.autoagent.fakechat:id/input"),
        send_button_locator=Locator(type="resource_id", value="com.autoagent.fakechat:id/send"),
        response_extraction=AndroidResponseExtraction(
            method="ui_tree_only",
            response_container_locator=Locator(
                type="resource_id",
                value="com.autoagent.fakechat:id/responses",
            ),
            scroll_container_locator=Locator(
                type="resource_id",
                value="com.autoagent.fakechat:id/responses",
            ),
            latest_bubble_match=Locator(
                type="last_child_with_class",
                value="android.widget.TextView",
            ),
        ),
        new_session_action=[
            {
                "action": "click_locator",
                "locator": {
                    "type": "resource_id",
                    "value": "com.autoagent.fakechat:id/newChat",
                },
            }
        ],
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.5, max_wait_sec=10),
    )


@pytest.mark.asyncio
async def test_fake_chat_apk_round_trip(
    android_profile: AndroidProfile,
    android_serial: str,
    tmp_path: Path,
) -> None:
    sample = Sample(
        id="s1",
        prompts=["hi", "bb", "ccc"],
        mode="gui_android",
        target_profile="fake_android",
        retry=0,
    )
    result = await AndroidExecutor(screenshots_root=tmp_path).run(
        sample,
        profile=android_profile,
        default_timeout_sec=180,
        ctx=ExecutorContext(device_serial=android_serial, verbose_logs=True),
    )
    assert result.status == "done"
    assert result.responses == ["echo: hi", "echo: bb", "echo: ccc"]
