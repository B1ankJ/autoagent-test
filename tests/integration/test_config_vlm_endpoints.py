from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.executors.llm_checker import CheckResult
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _h(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.mark.asyncio
async def test_post_vlm_test_returns_ok(client):
    h = await _h(client)
    fake = CheckResult(ok=True, stage="ok", message="ok", latency_ms=5)
    with patch(
        "autoagent.api.config.check_llm_api",
        new=AsyncMock(return_value=fake),
    ) as m:
        r = await client.post(
            "/api/v1/config/vlm/test",
            json={"base_url": "u", "model": "m", "api_key": "k"},
            headers=h,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["stage"] == "ok"
    m.assert_awaited_once_with("u", "m", "k")


@pytest.mark.asyncio
async def test_post_vlm_test_returns_failure_body_with_200(client):
    h = await _h(client)
    fake = CheckResult(ok=False, stage="auth", message="bad key", latency_ms=7)
    with patch(
        "autoagent.api.config.check_llm_api",
        new=AsyncMock(return_value=fake),
    ):
        r = await client.post(
            "/api/v1/config/vlm/test",
            json={"base_url": "u", "model": "m", "api_key": "k"},
            headers=h,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["stage"] == "auth"
    assert body["message"] == "bad key"


@pytest.mark.asyncio
async def test_post_vlm_test_requires_triple(client):
    h = await _h(client)
    r = await client.post(
        "/api/v1/config/vlm/test",
        json={"base_url": "u", "model": "m"},  # no api_key
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_put_vlm_rejects_bad_connectivity(client):
    h = await _h(client)
    fake = CheckResult(ok=False, stage="auth", message="bad key", latency_ms=9)
    with patch(
        "autoagent.api.config.check_llm_api",
        new=AsyncMock(return_value=fake),
    ) as m:
        r = await client.put(
            "/api/v1/config/vlm",
            json={"base_url": "u", "model": "m", "api_key": "bad"},
            headers=h,
        )
    assert r.status_code == 400
    assert r.json()["detail"]["stage"] == "auth"
    assert r.json()["detail"]["message"] == "bad key"
    m.assert_awaited_once_with("u", "m", "bad")


@pytest.mark.asyncio
async def test_put_vlm_allows_empty_triple_without_connectivity_check(client):
    h = await _h(client)
    with patch("autoagent.api.config.check_llm_api", new=AsyncMock()) as m:
        r = await client.put(
            "/api/v1/config/vlm",
            json={"base_url": None, "model": None, "api_key": None},
            headers=h,
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"base_url": None, "model": None, "api_key": None, "extra_headers": {}}
    m.assert_not_called()
