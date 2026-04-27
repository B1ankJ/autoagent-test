from pathlib import Path

import httpx

from autoagent.executors.profile_builder_new_session import (
    RecommendationProviderError,
    _request_payload,
    recommend_tap_point,
)
from autoagent.models.api import VLMConfig


def test_request_payload_defines_new_session_as_brand_new_thread(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"png")
    payload = _request_payload(
        screenshot_path=screenshot_path,
        xml_text="<hierarchy/>",
        step_index=0,
        step_count=2,
        vlm=VLMConfig(
            base_url="http://vlm.test",
            model="demo",
            api_key="secret",
        ),
    )

    assert payload["messages"][0]["content"] == (
        "You analyze Android UI captures and return only JSON matching the schema. "
        "A new session means creating a brand-new conversation thread, not focusing the "
        "existing message input box."
    )
    prompt = payload["messages"][1]["content"][0]["text"]
    assert "brand-new conversation thread" in prompt
    assert "Do not choose the current message input box" in prompt
    assert "For early steps in a multi-step flow" in prompt


def test_recommend_tap_point_includes_http_400_response_body(monkeypatch, tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"png")
    request = httpx.Request("POST", "http://vlm.test/chat/completions")
    response = httpx.Response(
        status_code=400,
        request=request,
        text='{"message":"model does not support image input"}',
    )

    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.httpx.post",
        lambda *args, **kwargs: response,
    )

    try:
        recommend_tap_point(
            screenshot_path=screenshot_path,
            xml_text="<hierarchy/>",
            step_index=0,
            step_count=1,
            vlm=VLMConfig(
                base_url="http://vlm.test",
                model="demo",
                api_key="secret",
            ),
        )
    except RecommendationProviderError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected RecommendationProviderError")

    assert "http 400" in message
    assert "model does not support image input" in message
