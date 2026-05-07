from autoagent.profiles.schemas import (
    AndroidProfile,
    AndroidResponseExtraction,
    Locator,
    UiTreeStable,
)

_BASE = dict(
    name="qwen_android",
    platform="android",
    package="com.aliyun.tongyi",
    serial="ABC",
    input_locator=Locator(type="resource_id", value="com.aliyun.tongyi:id/input"),
    send_button_locator=Locator(type="text", value="Send"),
    response_extraction=AndroidResponseExtraction(
        method="ui_tree_only",
        response_container_locator=Locator(type="resource_id", value="com.aliyun.tongyi:id/list"),
        scroll_container_locator=Locator(type="resource_id", value="com.aliyun.tongyi:id/list"),
        latest_bubble_match=Locator(type="last_child_with_class", value="android.widget.TextView"),
    ),
    complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=2, max_wait_sec=180),
)


def test_android_profile_llm_disabled_by_default():
    p = AndroidProfile(**_BASE)
    assert p.base_url is None
    assert p.model is None
    assert p.api_key is None
    assert p.llm_response_enabled() is False


def test_android_profile_llm_enabled_when_triple_complete():
    p = AndroidProfile(
        **_BASE,
        base_url="https://example/v1",
        model="qwen-plus",
        api_key="sk-xxx",
    )
    assert p.llm_response_enabled() is True


def test_android_profile_llm_disabled_when_any_field_missing():
    for missing in ("base_url", "model", "api_key"):
        kwargs = {"base_url": "u", "model": "m", "api_key": "k"}
        kwargs[missing] = None
        p = AndroidProfile(**_BASE, **kwargs)
        assert p.llm_response_enabled() is False, f"{missing} missing should disable"


def test_android_profile_ignores_unknown_fields():
    p = AndroidProfile(**_BASE, ready_check={"type": "ui_tree_contains", "text": "发消息"})
    assert not hasattr(p, "ready_check")
