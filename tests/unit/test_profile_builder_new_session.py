from pathlib import Path

import httpx

from autoagent.executors.profile_builder_new_session import (
    RecommendationProviderError,
    recommend_tap_point,
)
from autoagent.models.api import VLMConfig


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
