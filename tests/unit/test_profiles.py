import pytest
from pydantic import ValidationError

from autoagent.profiles.schemas import parse_profile, ApiProfile, WebProfile, AndroidProfile


def test_parse_api_profile():
    p = parse_profile({
        "name": "openai_gpt4",
        "platform": "api",
        "api": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_KEY",
        },
    })
    assert isinstance(p, ApiProfile)
    assert p.api.model == "gpt-4o"


def test_parse_web_profile():
    p = parse_profile({
        "name": "chatgpt_web",
        "platform": "web",
        "url": "https://chat.openai.com",
        "ready_check": {"type": "dom_selector", "selector": "textarea"},
        "recovery_path": [],
        "input_selector": "textarea",
        "send_method": {"type": "keyboard", "key": "Enter"},
        "response_container_selector": "div.assistant",
        "complete_detection": {"type": "dom_stable", "stable_sec": 2, "max_wait_sec": 120},
    })
    assert isinstance(p, WebProfile)


def test_parse_android_profile():
    p = parse_profile({
        "name": "wechat_bot",
        "platform": "android",
        "package": "com.tencent.mm",
        "ready_check": {"type": "ui_tree_contains", "text": "Bot"},
        "recovery_path": [],
        "input_locator": {"type": "resource_id", "value": "com.tencent.mm:id/edit"},
        "send_button_locator": {"type": "text", "value": "Send"},
        "response_extraction": {
            "method": "ui_tree_then_ocr",
            "response_container_locator": {"type": "resource_id", "value": "x"},
            "scroll_container_locator": {"type": "resource_id", "value": "x"},
            "latest_bubble_match": {"type": "last_child_with_class", "value": "TextView"},
        },
        "complete_detection": {"type": "pixel_stable", "stable_sec": 3, "max_wait_sec": 180},
    })
    assert isinstance(p, AndroidProfile)


def test_invalid_platform_rejected():
    with pytest.raises(ValidationError):
        parse_profile({"name": "x", "platform": "ios"})
