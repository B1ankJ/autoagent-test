import pytest
import yaml
from pydantic import ValidationError

from autoagent.profiles.registry import (
    delete_profile,
    list_profile_names,
    load_profile,
    save_profile_yaml,
    validate_yaml,
)
from autoagent.profiles.schemas import AndroidProfile, ApiProfile, WebProfile, parse_profile


def test_parse_api_profile():
    p = parse_profile(
        {
            "name": "openai_gpt4",
            "platform": "api",
            "api": {
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
                "api_key": "OPENAI_KEY",
            },
        }
    )
    assert isinstance(p, ApiProfile)
    assert p.api.model == "gpt-4o"


def test_parse_web_profile():
    p = parse_profile(
        {
            "name": "chatgpt_web",
            "platform": "web",
            "url": "https://chat.openai.com",
            "ready_check": {"type": "dom_selector", "selector": "textarea"},
            "recovery_path": [],
            "input_selector": "textarea",
            "send_method": {"type": "keyboard", "key": "Enter"},
            "response_container_selector": "div.assistant",
            "complete_detection": {"type": "dom_stable", "stable_sec": 2, "max_wait_sec": 120},
        }
    )
    assert isinstance(p, WebProfile)


def test_parse_android_profile():
    p = parse_profile(
        {
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
        }
    )
    assert isinstance(p, AndroidProfile)
    assert p.input_method == "auto"
    assert p.serial is None


def test_invalid_platform_rejected():
    with pytest.raises(ValidationError):
        parse_profile({"name": "x", "platform": "ios"})


def _api_yaml(name="openai_gpt4") -> str:
    return yaml.safe_dump(
        {
            "name": name,
            "platform": "api",
            "api": {"base_url": "https://x", "model": "m", "api_key": "K"},
        }
    )


def test_save_and_load_profile():
    save_profile_yaml("openai_gpt4", _api_yaml())
    names = list_profile_names()
    assert "openai_gpt4" in names
    p = load_profile("openai_gpt4")
    assert p.platform == "api"


def test_load_missing_returns_none():
    assert load_profile("ghost") is None


def test_delete_profile():
    save_profile_yaml("to_delete", _api_yaml("to_delete"))
    assert "to_delete" in list_profile_names()
    delete_profile("to_delete")
    assert "to_delete" not in list_profile_names()


def test_validate_yaml_accepts_good():
    ok, err = validate_yaml(_api_yaml())
    assert ok is True and err is None


def test_validate_yaml_rejects_bad():
    bad = "name: x\nplatform: unknown\n"
    ok, err = validate_yaml(bad)
    assert ok is False and err is not None
