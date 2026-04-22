from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "fake_chat.html").resolve()
FIXTURE_URL = FIXTURE.as_uri()

pytestmark = pytest.mark.playwright


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    save_profile_yaml(
        "fake_site",
        f"""
name: fake_site
platform: web
url: "{FIXTURE_URL}"
browser:
  headless: true
ready_check:
  type: dom_selector
  selector: '#input'
  timeout_sec: 10
recovery_path:
  - {{ action: goto, url: "{FIXTURE_URL}" }}
input_selector: '#input'
send_method:
  type: click_button
  selector: '#send'
response_container_selector: "#responses > div[data-role='assistant']:last-child"
new_session_action:
  - {{ action: click, selector: '#new-chat' }}
complete_detection:
  type: dom_stable
  stable_sec: 0.8
  max_wait_sec: 30
""",
    )
    from autoagent.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=120,
    ) as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


async def test_tests_sync_routes_to_web_executor(client: AsyncClient) -> None:
    headers = await _login(client)
    payload = {
        "id": "t1",
        "prompts": ["hi"],
        "mode": "gui_pc_web",
        "target_profile": "fake_site",
        "retry": 0,
        "timeout_sec": 60,
    }
    response = await client.post("/api/v1/tests/sync", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["responses"] == ["echo: hi"]
