from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user

pytestmark = pytest.mark.playwright


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


async def test_web_builder_response_pick_promotes_to_latest_message_container(
    client: AsyncClient, tmp_path: Path
) -> None:
    fixture = tmp_path / "web_builder_response_fixture.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
<body>
  <div id="responses">
    <div class="answerItem">
      <div class="qk-markdown">
        <div class="qk-md-text">older reply</div>
      </div>
    </div>
    <div class="answerItem">
      <div class="qk-markdown">
        <div class="qk-md-text">intro first paragraph</div>
        <div class="qk-md-text">intro second paragraph</div>
      </div>
    </div>
  </div>
  <textarea id="input" placeholder="Ask"></textarea>
  <button id="send">Send</button>
</body>
</html>
""",
        encoding="utf-8",
    )

    headers = await _login(client)
    create = await client.post(
        "/api/v1/web-profile-builder/sessions",
        json={"url": fixture.resolve().as_uri(), "headless": True},
        headers=headers,
    )
    assert create.status_code == 200, create.text
    session_id = create.json()["id"]

    from autoagent.api import web_profile_builder as builder_mod

    page = builder_mod._sessions[session_id]["page"]
    input_box = await page.locator("#input").bounding_box()
    send_box = await page.locator("#send").bounding_box()
    response_box = await page.locator(".answerItem:last-child .qk-md-text").nth(1).bounding_box()

    assert input_box is not None
    assert send_box is not None
    assert response_box is not None

    picks = [
        (
            "input",
            input_box["x"] + input_box["width"] / 2,
            input_box["y"] + input_box["height"] / 2,
        ),
        (
            "send",
            send_box["x"] + send_box["width"] / 2,
            send_box["y"] + send_box["height"] / 2,
        ),
        (
            "response",
            response_box["x"] + response_box["width"] / 2,
            response_box["y"] + response_box["height"] / 2,
        ),
    ]
    for field, x, y in picks:
        pick = await client.post(
            f"/api/v1/web-profile-builder/sessions/{session_id}/pick",
            json={"field": field, "x": x, "y": y},
            headers=headers,
        )
        assert pick.status_code == 200, pick.text

    generated = await client.post(
        f"/api/v1/web-profile-builder/sessions/{session_id}/generate",
        json={"name": "fixture_profile"},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    profile = yaml.safe_load(generated.json()["yaml"])

    assert profile["response_container_selector"] == ".answerItem:last-child .qk-markdown"

    close = await client.delete(
        f"/api/v1/web-profile-builder/sessions/{session_id}",
        headers=headers,
    )
    assert close.status_code == 200


async def test_web_builder_input_pick_promotes_to_textbox_container(
    client: AsyncClient, tmp_path: Path
) -> None:
    fixture = tmp_path / "web_builder_textbox_fixture.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
<body>
  <div role="textbox" contenteditable="true" aria-label="Chat input">
    <p><span>Type here</span></p>
  </div>
  <button id="send">Send</button>
  <div class="answerItem">
    <div class="qk-markdown">reply</div>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )

    headers = await _login(client)
    create = await client.post(
        "/api/v1/web-profile-builder/sessions",
        json={"url": fixture.resolve().as_uri(), "headless": True},
        headers=headers,
    )
    assert create.status_code == 200, create.text
    session_id = create.json()["id"]

    from autoagent.api import web_profile_builder as builder_mod

    page = builder_mod._sessions[session_id]["page"]
    input_box = await page.locator('[role="textbox"] > p > span').bounding_box()
    send_box = await page.locator("#send").bounding_box()
    response_box = await page.locator(".qk-markdown").bounding_box()

    assert input_box is not None
    assert send_box is not None
    assert response_box is not None

    for field, box in (
        ("input", input_box),
        ("send", send_box),
        ("response", response_box),
    ):
        pick = await client.post(
            f"/api/v1/web-profile-builder/sessions/{session_id}/pick",
            json={
                "field": field,
                "x": box["x"] + box["width"] / 2,
                "y": box["y"] + box["height"] / 2,
            },
            headers=headers,
        )
        assert pick.status_code == 200, pick.text

    generated = await client.post(
        f"/api/v1/web-profile-builder/sessions/{session_id}/generate",
        json={"name": "textbox_fixture"},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    profile = yaml.safe_load(generated.json()["yaml"])

    assert profile["input_selector"].startswith('[role="textbox"]')
    assert "nth-of-type" not in profile["input_selector"]
    assert "> p" not in profile["input_selector"]
    assert profile["ready_check"]["selector"] == profile["input_selector"]

    close = await client.delete(
        f"/api/v1/web-profile-builder/sessions/{session_id}",
        headers=headers,
    )
    assert close.status_code == 200


async def test_web_builder_chat_like_response_pick_prefers_message_container_over_deep_div_path(
    client: AsyncClient, tmp_path: Path
) -> None:
    fixture = tmp_path / "web_builder_chat_like_fixture.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
<body>
  <main>
    <div role="textbox" contenteditable="true" aria-label="Chat input">
      <p><span>Type here</span></p>
    </div>
    <div class="segment-assistant">
      <div class="toolbar">copy regen</div>
      <div class="message-shell">
        <div class="markdown">older answer</div>
      </div>
    </div>
    <div class="segment-assistant">
      <div class="toolbar">copy regen</div>
      <div class="message-shell">
        <div class="markdown">latest answer paragraph</div>
      </div>
    </div>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )

    headers = await _login(client)
    create = await client.post(
        "/api/v1/web-profile-builder/sessions",
        json={"url": fixture.resolve().as_uri(), "headless": True},
        headers=headers,
    )
    assert create.status_code == 200, create.text
    session_id = create.json()["id"]

    from autoagent.api import web_profile_builder as builder_mod

    page = builder_mod._sessions[session_id]["page"]
    input_box = await page.locator('[role="textbox"] > p > span').bounding_box()
    response_box = await page.locator(".segment-assistant:last-of-type .markdown").bounding_box()

    assert input_box is not None
    assert response_box is not None

    for field, box in (
        ("input", input_box),
        ("response", response_box),
    ):
        pick = await client.post(
            f"/api/v1/web-profile-builder/sessions/{session_id}/pick",
            json={
                "field": field,
                "x": box["x"] + box["width"] / 2,
                "y": box["y"] + box["height"] / 2,
            },
            headers=headers,
        )
        assert pick.status_code == 200, pick.text

    session = await client.get(
        f"/api/v1/web-profile-builder/sessions/{session_id}",
        headers=headers,
    )
    assert session.status_code == 200, session.text
    body = session.json()

    assert body["selections"]["input"]["selector"].startswith('[role="textbox"]')
    assert body["selections"]["response"]["selector"].startswith(".segment-assistant:last-child")
    assert ".markdown" in body["selections"]["response"]["selector"]
    assert "nth-of-type" not in body["selections"]["response"]["selector"]

    close = await client.delete(
        f"/api/v1/web-profile-builder/sessions/{session_id}",
        headers=headers,
    )
    assert close.status_code == 200


async def test_web_builder_response_pick_avoids_leaf_text_selector_in_nested_qwen_like_dom(
    client: AsyncClient, tmp_path: Path
) -> None:
    fixture = tmp_path / "web_builder_qwen_like_response_fixture.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
<body>
  <div class="content-MqQgCb">
    <div>
      <div class="messageItem">
        <div class="qk-markdown">
          <div class="qk-md-text">older reply line</div>
        </div>
      </div>
      <div class="messageItem">
        <div class="qk-markdown">
          <div class="qk-md-text">intro first paragraph</div>
          <div class="qk-md-text">intro second paragraph</div>
          <div class="qk-md-text">intro final paragraph</div>
        </div>
      </div>
    </div>
  </div>
  <textarea id="input" placeholder="Ask"></textarea>
  <button id="send">Send</button>
</body>
</html>
""",
        encoding="utf-8",
    )

    headers = await _login(client)
    create = await client.post(
        "/api/v1/web-profile-builder/sessions",
        json={"url": fixture.resolve().as_uri(), "headless": True},
        headers=headers,
    )
    assert create.status_code == 200, create.text
    session_id = create.json()["id"]

    from autoagent.api import web_profile_builder as builder_mod

    page = builder_mod._sessions[session_id]["page"]
    input_box = await page.locator("#input").bounding_box()
    send_box = await page.locator("#send").bounding_box()
    response_box = await page.locator(".messageItem:last-child .qk-md-text").nth(2).bounding_box()

    assert input_box is not None
    assert send_box is not None
    assert response_box is not None

    for field, box in (
        ("input", input_box),
        ("send", send_box),
        ("response", response_box),
    ):
        pick = await client.post(
            f"/api/v1/web-profile-builder/sessions/{session_id}/pick",
            json={
                "field": field,
                "x": box["x"] + box["width"] / 2,
                "y": box["y"] + box["height"] / 2,
            },
            headers=headers,
        )
        assert pick.status_code == 200, pick.text

    generated = await client.post(
        f"/api/v1/web-profile-builder/sessions/{session_id}/generate",
        json={"name": "fixture_profile_qwen_like"},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    profile = yaml.safe_load(generated.json()["yaml"])

    assert profile["response_container_selector"].endswith(".qk-markdown")
    assert ".qk-md-text" not in profile["response_container_selector"]

    close = await client.delete(
        f"/api/v1/web-profile-builder/sessions/{session_id}",
        headers=headers,
    )
    assert close.status_code == 200


async def test_web_builder_response_pick_uses_markdown_container_when_repeated_items_are_plain_divs(
    client: AsyncClient, tmp_path: Path
) -> None:
    fixture = tmp_path / "web_builder_qwen_plain_div_fixture.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
<body>
  <div class="content-MqQgCb">
    <div>
      <div>
        <div class="qk-markdown">
          <div class="qk-md-text">older reply line</div>
        </div>
      </div>
      <div>
        <div class="qk-markdown">
          <div class="qk-md-text">intro first paragraph</div>
          <div class="qk-md-text">intro second paragraph</div>
          <div class="qk-md-text">intro final paragraph</div>
        </div>
      </div>
    </div>
  </div>
  <textarea id="input" placeholder="Ask"></textarea>
  <button id="send">Send</button>
</body>
</html>
""",
        encoding="utf-8",
    )

    headers = await _login(client)
    create = await client.post(
        "/api/v1/web-profile-builder/sessions",
        json={"url": fixture.resolve().as_uri(), "headless": True},
        headers=headers,
    )
    assert create.status_code == 200, create.text
    session_id = create.json()["id"]

    from autoagent.api import web_profile_builder as builder_mod

    page = builder_mod._sessions[session_id]["page"]
    input_box = await page.locator("#input").bounding_box()
    send_box = await page.locator("#send").bounding_box()
    response_box = (
        await page.locator(".content-MqQgCb > div > div:last-child .qk-md-text")
        .nth(2)
        .bounding_box()
    )

    assert input_box is not None
    assert send_box is not None
    assert response_box is not None

    for field, box in (
        ("input", input_box),
        ("send", send_box),
        ("response", response_box),
    ):
        pick = await client.post(
            f"/api/v1/web-profile-builder/sessions/{session_id}/pick",
            json={
                "field": field,
                "x": box["x"] + box["width"] / 2,
                "y": box["y"] + box["height"] / 2,
            },
            headers=headers,
        )
        assert pick.status_code == 200, pick.text

    generated = await client.post(
        f"/api/v1/web-profile-builder/sessions/{session_id}/generate",
        json={"name": "fixture_profile_qwen_plain_div"},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    profile = yaml.safe_load(generated.json()["yaml"])

    assert profile["response_container_selector"].endswith(".qk-markdown")
    assert ".qk-md-text" not in profile["response_container_selector"]

    close = await client.delete(
        f"/api/v1/web-profile-builder/sessions/{session_id}",
        headers=headers,
    )
    assert close.status_code == 200


async def test_web_builder_response_pick_promotes_past_single_text_wrapper_to_markdown_container(
    client: AsyncClient, tmp_path: Path
) -> None:
    fixture = tmp_path / "web_builder_single_text_wrapper_fixture.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
<body>
  <div class="content-MqQgCb">
    <div>
      <div>
        <div class="qk-markdown">
          <div class="qk-md-text">
            <div>older reply line</div>
          </div>
        </div>
      </div>
      <div>
        <div class="qk-markdown">
          <div class="qk-md-text">
            <div>intro first paragraph</div>
            <div>intro second paragraph</div>
            <div>intro final paragraph</div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <textarea id="input" placeholder="Ask"></textarea>
  <button id="send">Send</button>
</body>
</html>
""",
        encoding="utf-8",
    )

    headers = await _login(client)
    create = await client.post(
        "/api/v1/web-profile-builder/sessions",
        json={"url": fixture.resolve().as_uri(), "headless": True},
        headers=headers,
    )
    assert create.status_code == 200, create.text
    session_id = create.json()["id"]

    from autoagent.api import web_profile_builder as builder_mod

    page = builder_mod._sessions[session_id]["page"]
    input_box = await page.locator("#input").bounding_box()
    send_box = await page.locator("#send").bounding_box()
    response_box = (
        await page.locator(".content-MqQgCb > div > div:last-child .qk-md-text > div")
        .nth(2)
        .bounding_box()
    )

    assert input_box is not None
    assert send_box is not None
    assert response_box is not None

    for field, box in (
        ("input", input_box),
        ("send", send_box),
        ("response", response_box),
    ):
        pick = await client.post(
            f"/api/v1/web-profile-builder/sessions/{session_id}/pick",
            json={
                "field": field,
                "x": box["x"] + box["width"] / 2,
                "y": box["y"] + box["height"] / 2,
            },
            headers=headers,
        )
        assert pick.status_code == 200, pick.text

    generated = await client.post(
        f"/api/v1/web-profile-builder/sessions/{session_id}/generate",
        json={"name": "fixture_profile_single_text_wrapper"},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    profile = yaml.safe_load(generated.json()["yaml"])

    assert profile["response_container_selector"].endswith(".qk-markdown")
    assert ".qk-md-text" not in profile["response_container_selector"]

    close = await client.delete(
        f"/api/v1/web-profile-builder/sessions/{session_id}",
        headers=headers,
    )
    assert close.status_code == 200


# ── inject_llm tests ──────────────────────────────────────────────────────────

_FAKE_SESSION_SELECTIONS = {
    "input": {"selector": "[role='textbox']", "info": {}},
    "send": {
        "selector": "[role='textbox']",
        "info": {},
        "send_type": "keyboard",
        "keyboard_key": "Enter",
    },
    "response": {"selector": ".reply", "info": {}},
}


def _make_fake_session(sid: str) -> dict:
    return {
        "id": sid,
        "url": "https://example.com",
        "channel": "chromium",
        "headless": False,
        "user_data_dir": None,
        "pw": None,
        "context": None,
        "page": None,
        "selections": dict(_FAKE_SESSION_SELECTIONS),
    }


@pytest.mark.asyncio
async def test_generate_inject_llm_false_omits_llm_fields(client: AsyncClient) -> None:
    """inject_llm=False (default) → YAML has no LLM fields."""
    import uuid

    from autoagent.api.web_profile_builder import _sessions
    from autoagent.storage.configs import put_config

    await put_config("vlm", {"base_url": "https://api/v1", "model": "m", "api_key": "k"})

    headers = await _login(client)
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = _make_fake_session(sid)

    try:
        resp = await client.post(
            f"/api/v1/web-profile-builder/sessions/{sid}/generate",
            json={"name": "test_profile", "inject_llm": False},
            headers=headers,
        )
        assert resp.status_code == 200
        import yaml as yaml_lib

        profile = yaml_lib.safe_load(resp.json()["yaml"])
        assert "base_url" not in profile
        assert "model" not in profile
        assert "api_key" not in profile
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_generate_inject_llm_true_includes_llm_fields(client: AsyncClient) -> None:
    """inject_llm=True with complete VLMConfig → YAML contains all three LLM fields."""
    import uuid

    from autoagent.api.web_profile_builder import _sessions
    from autoagent.storage.configs import put_config

    await put_config(
        "vlm", {"base_url": "https://api/v1", "model": "my-model", "api_key": "sk-test"}
    )

    headers = await _login(client)
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = _make_fake_session(sid)

    try:
        resp = await client.post(
            f"/api/v1/web-profile-builder/sessions/{sid}/generate",
            json={"name": "test_profile", "inject_llm": True},
            headers=headers,
        )
        assert resp.status_code == 200
        import yaml as yaml_lib

        profile = yaml_lib.safe_load(resp.json()["yaml"])
        assert profile["base_url"] == "https://api/v1"
        assert profile["model"] == "my-model"
        assert profile["api_key"] == "sk-test"
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_generate_inject_llm_true_incomplete_vlm_returns_400(client: AsyncClient) -> None:
    """inject_llm=True with missing VLMConfig → 400 llm_config_incomplete."""
    import uuid

    from autoagent.api.web_profile_builder import _sessions
    from autoagent.storage.configs import put_config

    await put_config("vlm", {"base_url": None, "model": None, "api_key": None})

    headers = await _login(client)
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = _make_fake_session(sid)

    try:
        resp = await client.post(
            f"/api/v1/web-profile-builder/sessions/{sid}/generate",
            json={"name": "test_profile", "inject_llm": True},
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "llm_config_incomplete"
    finally:
        _sessions.pop(sid, None)
