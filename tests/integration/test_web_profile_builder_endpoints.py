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
    response_box = await page.locator(".content-MqQgCb > div > div:last-child .qk-md-text").nth(2).bounding_box()

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
    response_box = await page.locator(".content-MqQgCb > div > div:last-child .qk-md-text > div").nth(2).bounding_box()

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
