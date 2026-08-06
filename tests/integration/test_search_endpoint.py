import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.mark.asyncio
async def test_search_endpoint(client):
    from datetime import datetime, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    now = datetime.now(timezone.utc)
    await upsert_sample(
        "b",
        SampleResult(id="s1", status="done", mode="api", target_profile="p",
                     responses=["hello 抱歉我无法 world"], ended_at=now),
    )
    r = await client.get("/api/v1/samples/search?q=抱歉我无法", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["sample_id"] == "s1" and body["items"][0]["source"] == "response"


@pytest.mark.asyncio
async def test_search_rejects_short_query(client):
    h = await _login(client)
    r = await client.get("/api/v1/samples/search?q=a", headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_requires_auth(client):
    r = await client.get("/api/v1/samples/search?q=abc")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_search_endpoint_new_params(client):
    from datetime import datetime, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    now = datetime.now(timezone.utc)
    await upsert_sample(
        "b",
        SampleResult(id="pq", status="done", mode="api", target_profile="p",
                     prompts_sent=["提示 关键字K"], responses=["无关"], ended_at=now),
    )
    await upsert_sample(
        "b",
        SampleResult(id="rq", status="failed", mode="api", target_profile="p",
                     prompts_sent=["无关"], responses=["答案 关键字K"], ended_at=now),
    )

    r = await client.get("/api/v1/samples/search?q=关键字K&fields=prompt", headers=h)
    assert r.json()["total"] == 1 and r.json()["items"][0]["source"] == "prompt"
    r = await client.get("/api/v1/samples/search?q=关键字K&status=failed", headers=h)
    assert r.json()["total"] == 1 and r.json()["items"][0]["sample_id"] == "rq"
