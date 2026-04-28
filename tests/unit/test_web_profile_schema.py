from autoagent.profiles.schemas import WebProfile


def _base_profile(**extra):
    return {
        "name": "test_web",
        "platform": "web",
        "url": "https://example.com",
        "ready_check": {"type": "dom_selector", "selector": "[role='textbox']"},
        "recovery_path": [],
        "input_selector": "[role='textbox']",
        "send_method": {"type": "keyboard", "key": "Enter"},
        "response_container_selector": ".reply",
        "complete_detection": {"type": "dom_stable", "stable_sec": 2, "max_wait_sec": 120},
        **extra,
    }


def test_llm_disabled_by_default():
    p = WebProfile(**_base_profile())
    assert p.llm_response_enabled() is False


def test_llm_disabled_when_partial():
    p = WebProfile(**_base_profile(base_url="https://api/v1", model="m"))
    assert p.llm_response_enabled() is False


def test_llm_enabled_when_all_set():
    p = WebProfile(**_base_profile(
        base_url="https://api/v1", model="my-model", api_key="sk-123"
    ))
    assert p.llm_response_enabled() is True


def test_llm_disabled_when_empty_string():
    p = WebProfile(**_base_profile(base_url="", model="m", api_key="k"))
    assert p.llm_response_enabled() is False
