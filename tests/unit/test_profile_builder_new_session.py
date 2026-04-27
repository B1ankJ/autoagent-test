import json
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


def test_recommend_tap_point_calibrates_to_xml_bounds_from_target_text(monkeypatch, tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"png")
    xml_text = """
    <hierarchy>
      <node text="" clickable="false" bounds="[0,0][1080,2400]">
        <node text="新建对话" clickable="true" bounds="[100,200][500,300]" />
      </node>
    </hierarchy>
    """.strip()
    response = httpx.Response(
        status_code=200,
        request=httpx.Request("POST", "http://vlm.test/chat/completions"),
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "target_text": "新建对话",
                                "reason": "The explicit new conversation button is visible.",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        },
    )

    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.httpx.post",
        lambda *args, **kwargs: response,
    )

    result = recommend_tap_point(
        screenshot_path=screenshot_path,
        xml_text=xml_text,
        step_index=1,
        step_count=2,
        vlm=VLMConfig(
            base_url="http://vlm.test",
            model="demo",
            api_key="secret",
        ),
    )

    assert result == {
        "x": 300,
        "y": 250,
        "reason": "The explicit new conversation button is visible.",
    }
