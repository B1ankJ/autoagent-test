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
async def test_profile_health_endpoint(client):
    from datetime import datetime, timezone

    from autoagent.models.api import SampleResult
    from autoagent.profiles.registry import save_profile_yaml
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    save_profile_yaml(
        "ph", "name: ph\nplatform: api\napi:\n  base_url: http://x\n  model: m\n  api_key: K\n"
    )
    await upsert_sample(
        "b",
        SampleResult(
            id="s1",
            status="done",
            mode="api",
            target_profile="ph",
            duration_ms=100,
            ended_at=datetime.now(timezone.utc),
        ),
    )

    r = await client.get("/api/v1/profiles/health", headers=h)
    assert r.status_code == 200
    rows = {row["name"]: row for row in r.json()}
    assert rows["ph"]["status"] == "green"
    assert rows["ph"]["total_runs"] == 1
    assert rows["ph"]["success_rate"] == 1.0


@pytest.mark.asyncio
async def test_profile_health_requires_auth(client):
    r = await client.get("/api/v1/profiles/health")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_profile_trends_endpoint(client):
    from datetime import datetime, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="s1", status="done", mode="api",
                                          target_profile="pt", duration_ms=100, ended_at=now))
    r = await client.get("/api/v1/profiles/trends?days=30", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "pt" in body
    assert body["pt"][0]["success_rate"] == 1.0 and body["pt"][0]["sample_count"] == 1


@pytest.mark.asyncio
async def test_profile_trends_days_cap(client):
    h = await _login(client)
    r = await client.get("/api/v1/profiles/trends?days=999", headers=h)
    assert r.status_code == 422
