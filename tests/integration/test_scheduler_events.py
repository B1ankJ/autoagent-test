from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.events.bus import get_event_bus, reset_bus_for_tests
from autoagent.executors.base import Executor
from autoagent.main import app
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ApiConfig, ApiProfile
from autoagent.scheduler.batch_scheduler import BatchScheduler
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


class _FastExec(Executor):
    async def execute(self, sample, profile, ctx):  # noqa: ANN001
        return ["ok"]


def _profile() -> ApiProfile:
    return ApiProfile(
        name="fast",
        platform="api",
        api=ApiConfig(base_url="http://x", model="m", api_key_env="NOTHING"),
    )


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()


async def test_scheduler_publishes_sample_and_batch_events() -> None:
    await init_db()
    bus = get_event_bus()
    executor = _FastExec()
    scheduler = BatchScheduler(
        executor_factory=lambda _m: executor,
        profile_lookup=lambda _n: _profile(),
    )

    samples = [
        Sample(id=f"s{i}", prompts=["hi"], mode="api", target_profile="fast", dry_run=True)
        for i in range(2)
    ]

    batch_id = await scheduler.submit(name="t", mode="api", concurrency=2, samples=samples)
    await scheduler.wait_done(batch_id, timeout_sec=10)

    events = bus.replay_since(batch_id, after_seq=0)
    kinds = [event.kind for event in events]
    assert "sample_update" in kinds
    assert "batch_progress" in kinds
    assert kinds[-1] == "batch_done"
    assert bus.last_seq(batch_id) >= 1


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


async def test_batch_detail_endpoint_exposes_seq(client: AsyncClient) -> None:
    bus = get_event_bus()
    executor = _FastExec()
    scheduler = BatchScheduler(
        executor_factory=lambda _m: executor,
        profile_lookup=lambda _n: _profile(),
    )

    samples = [Sample(id="s1", prompts=["hi"], mode="api", target_profile="fast", dry_run=True)]
    batch_id = await scheduler.submit(name="t", mode="api", concurrency=1, samples=samples)
    await asyncio.wait_for(scheduler.wait_done(batch_id, timeout_sec=10), timeout=10)

    headers = await _login(client)
    response = await client.get(f"/api/v1/batches/{batch_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["seq"] == bus.last_seq(batch_id)
