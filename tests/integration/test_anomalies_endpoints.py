import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.anomalies import store
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
async def test_list_filter_count_acknowledge(client):
    h = await _login(client)
    await store.record_anomaly(
        type="duration",
        batch_id="b1",
        sample_id="s1",
        target_profile="p1",
        device_serial="d1",
        summary="dur",
        detail={"direction": "high"},
    )
    await store.record_anomaly(
        type="anr",
        batch_id="b2",
        sample_id="s2",
        target_profile="p2",
        device_serial=None,
        summary="anr",
        detail={},
    )

    r = await client.get("/api/v1/anomalies", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and len(body["items"]) == 2

    r = await client.get("/api/v1/anomalies?type=duration", headers=h)
    assert r.json()["total"] == 1

    r = await client.get("/api/v1/anomalies/count?acknowledged=false", headers=h)
    assert r.json()["count"] == 2

    target_id = body["items"][0]["id"]
    r = await client.post(f"/api/v1/anomalies/{target_id}/acknowledge", headers=h)
    assert r.status_code == 200
    # idempotent
    r = await client.post(f"/api/v1/anomalies/{target_id}/acknowledge", headers=h)
    assert r.status_code == 200
    r = await client.post("/api/v1/anomalies/999999/acknowledge", headers=h)
    assert r.status_code == 404

    r = await client.get("/api/v1/anomalies/count?acknowledged=false", headers=h)
    assert r.json()["count"] == 1


@pytest.mark.asyncio
async def test_limit_cap(client):
    h = await _login(client)
    r = await client.get("/api/v1/anomalies?limit=500", headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client):
    r = await client.get("/api/v1/anomalies")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_anomalies_time_params(client):
    h = await _login(client)
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    r = await client.get("/api/v1/anomalies?created_after=2099-01-01T00:00:00Z", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 0
    r = await client.get("/api/v1/anomalies?created_after=2000-01-01T00:00:00Z", headers=h)
    assert r.json()["total"] == 1


@pytest.mark.asyncio
async def test_backfill_endpoint(client):
    from datetime import datetime, timedelta, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(25):
        await upsert_sample(
            "b",
            SampleResult(id=f"h{i}", status="done", mode="api", target_profile="p",
                         duration_ms=1000 + i, ended_at=base + timedelta(minutes=i)),
        )
    await upsert_sample(
        "b",
        SampleResult(id="out", status="done", mode="api", target_profile="p",
                     duration_ms=50000, ended_at=base + timedelta(hours=2)),
    )
    r = await client.post("/api/v1/anomalies/backfill", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["scanned"] == 26 and body["created"] == 1
