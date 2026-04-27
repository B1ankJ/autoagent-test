import asyncio
import json

import anyio
import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    # Manually drive the ASGI lifespan so init_db + admin bootstrap run.
    # We use a background task for the lifespan coroutine and coordinate via
    # anyio events/streams, but we must NOT yield inside the task group because
    # pytest teardown runs in a different asyncio task, which breaks anyio's
    # cancel-scope ownership check.  Instead we start the lifespan task with
    # asyncio directly and cancel it after the test.
    import asyncio

    from autoagent.main import app

    send_queue, receive_queue = anyio.create_memory_object_stream(1)
    startup_complete = anyio.Event()
    shutdown_send, shutdown_receive = anyio.create_memory_object_stream(1)

    async def run_lifespan():
        scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

        async def receive():
            return await receive_queue.receive()

        async def send(message):
            if message["type"] == "lifespan.startup.complete":
                startup_complete.set()
            elif message["type"] == "lifespan.shutdown.complete":
                await shutdown_send.send(message)

        await app(scope, receive, send)

    loop = asyncio.get_event_loop()
    lifespan_task = loop.create_task(run_lifespan())
    await send_queue.send({"type": "lifespan.startup"})
    await startup_complete.wait()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    await send_queue.send({"type": "lifespan.shutdown"})
    try:
        await asyncio.wait_for(shutdown_receive.receive(), timeout=5)
    except asyncio.TimeoutError:
        pass
    lifespan_task.cancel()
    try:
        await lifespan_task
    except (asyncio.CancelledError, Exception):
        pass


async def test_e2e_full_batch_via_http(client, httpx_mock: HTTPXMock):
    # Mock three upstream LLM replies
    for text in ("r1", "r2", "r3"):
        httpx_mock.add_response(
            url="https://api.example.com/v1/chat/completions",
            json={"choices": [{"message": {"content": text}}]},
        )

    # 1. Login
    r = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"}
    )
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    # 2. Create profile
    profile_yaml = yaml.safe_dump(
        {
            "name": "openai_compat",
            "platform": "api",
            "api": {
                "base_url": "https://api.example.com/v1",
                "model": "m",
                "api_key": "OPENAI_TEST_KEY",
            },
        }
    )
    r = await client.post("/api/v1/profiles/openai_compat", json={"yaml": profile_yaml}, headers=h)
    assert r.status_code == 201

    # 3. Upload batch
    jsonl = "\n".join(
        json.dumps(
            {
                "id": f"t{i}",
                "prompts": [f"prompt{i}"],
                "mode": "api",
                "target_profile": "openai_compat",
            }
        )
        for i in range(3)
    )
    files = {"file": ("b.jsonl", jsonl, "application/x-ndjson")}
    data = {"name": "e2e", "mode": "api", "concurrency": "2"}
    r = await client.post("/api/v1/batches/upload", files=files, data=data, headers=h)
    assert r.status_code == 201
    batch_id = r.json()["batch_id"]

    # 4. Poll until done
    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await client.get(f"/api/v1/batches/{batch_id}", headers=h)
        if r.json()["status"] in ("done", "failed"):
            break

    detail = r.json()
    assert detail["status"] == "done"
    assert detail["total"] == 3
    assert detail["done"] == 3
    assert detail["failed"] == 0
    assert len(detail["samples"]) == 3

    # 5. Download results JSONL
    r = await client.get(f"/api/v1/batches/{batch_id}/results", headers=h)
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        d = json.loads(line)
        assert d["status"] == "done"
        assert len(d["responses"]) == 1
