from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport
from sse_starlette.sse import AppStatus

from autoagent.auth.jwt import create_access_token
from autoagent.events.bus import get_event_bus, reset_bus_for_tests
from autoagent.main import app


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()
    # sse_starlette lazily creates a module-level anyio.Event on first use
    # and never resets it — reusing it from a prior test binds it to that
    # test's (by-then-closed) event loop, raising "bound to a different
    # event loop" the next time an SSE endpoint is hit in this session.
    AppStatus.should_exit_event = None


@pytest.fixture
def token() -> str:
    return create_access_token("admin")


async def _collect_events(client: httpx.AsyncClient, url: str, token: str, n: int) -> list[dict]:
    out: list[dict] = []
    async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk.replace("\r\n", "\n")
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                for line in raw.splitlines():
                    if line.startswith("data: "):
                        out.append(json.loads(line[6:]))
                        if len(out) >= n:
                            return out
    return out


async def test_sse_receives_published_events(token: str) -> None:
    bus = get_event_bus()
    transport = ASGITransport(app=app)

    async def publisher() -> None:
        await asyncio.sleep(0.1)
        await bus.publish("b1", "batch_progress", {"done": 1, "total": 3})
        await bus.publish("b1", "batch_done", {"status": "done"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        pub_task = asyncio.create_task(publisher())
        events = await asyncio.wait_for(
            _collect_events(client, "/api/v1/batches/b1/events", token, 2),
            timeout=5,
        )
        await pub_task

    assert events[0]["kind"] == "batch_progress"
    assert events[1]["kind"] == "batch_done"
    assert events[0]["seq"] < events[1]["seq"]


async def test_sse_replays_buffered_events_since_after_seq(token: str) -> None:
    bus = get_event_bus()
    transport = ASGITransport(app=app)

    # Publish before any subscriber connects — simulates events that were
    # missed during a reconnect gap. replay_since must hand these back
    # instead of them being lost forever (the pre-fix behavior: subscribe()
    # only ever sees events published *after* it connects).
    await bus.publish("b1", "batch_progress", {"done": 1, "total": 3})
    await bus.publish("b1", "batch_progress", {"done": 2, "total": 3})
    await bus.publish("b1", "batch_done", {"status": "done"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        events = await asyncio.wait_for(
            _collect_events(client, "/api/v1/batches/b1/events?after_seq=1", token, 2),
            timeout=5,
        )

    # Only seq 2 and 3 are replayed — seq 1 (already seen before the
    # reconnect) is filtered out by after_seq.
    assert [e["seq"] for e in events] == [2, 3]
    assert events[1]["kind"] == "batch_done"


async def test_sse_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/batches/b1/events")
        assert response.status_code == 401
