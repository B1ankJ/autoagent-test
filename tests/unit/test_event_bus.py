import asyncio

import pytest

from autoagent.events.bus import BatchEventBus, Event


async def _collect(bus: BatchEventBus, batch_id: str, n: int) -> list[Event]:
    gen = bus.subscribe(batch_id)
    out: list[Event] = []
    try:
        async with asyncio.timeout(2):
            async for event in gen:
                out.append(event)
                if len(out) >= n:
                    break
    finally:
        await gen.aclose()
    return out


async def test_publish_and_subscribe_single() -> None:
    bus = BatchEventBus()
    collected: list[Event] = []

    async def reader() -> None:
        async for event in bus.subscribe("b1"):
            collected.append(event)
            if len(collected) >= 2:
                break

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    await bus.publish("b1", "sample_update", {"sample_id": "s1", "status": "running"})
    await bus.publish("b1", "sample_update", {"sample_id": "s1", "status": "done"})
    await task

    assert [e.kind for e in collected] == ["sample_update", "sample_update"]
    assert [e.seq for e in collected] == [1, 2]
    assert collected[0].payload["sample_id"] == "s1"


async def test_two_subscribers_both_receive() -> None:
    bus = BatchEventBus()
    got_a: list[Event] = []
    got_b: list[Event] = []

    async def reader(sink: list[Event]) -> None:
        async for event in bus.subscribe("b1"):
            sink.append(event)
            if len(sink) >= 1:
                break

    ta = asyncio.create_task(reader(got_a))
    tb = asyncio.create_task(reader(got_b))
    await asyncio.sleep(0)
    await bus.publish("b1", "batch_progress", {"done": 1})
    await asyncio.gather(ta, tb)
    assert got_a[0].payload == {"done": 1}
    assert got_b[0].payload == {"done": 1}


async def test_seq_is_per_batch_not_global() -> None:
    bus = BatchEventBus()
    await bus.publish("b1", "k", {})
    await bus.publish("b2", "k", {})
    await bus.publish("b1", "k", {})
    assert bus.last_seq("b1") == 2
    assert bus.last_seq("b2") == 1


async def test_replay_since_returns_buffered_events() -> None:
    bus = BatchEventBus(buffer_size=5)
    await bus.publish("b1", "k", {"v": 1})
    await bus.publish("b1", "k", {"v": 2})
    await bus.publish("b1", "k", {"v": 3})
    replay = list(bus.replay_since("b1", after_seq=1))
    assert [e.seq for e in replay] == [2, 3]


async def test_replay_after_ring_eviction_returns_recent_events() -> None:
    bus = BatchEventBus(buffer_size=2)
    for i in range(5):
        await bus.publish("b1", "k", {"v": i})
    replay = list(bus.replay_since("b1", after_seq=1))
    assert [e.seq for e in replay] == [4, 5]


async def test_unsubscribe_stops_delivery() -> None:
    bus = BatchEventBus()

    async def short_reader() -> None:
        async for _event in bus.subscribe("b1"):
            break

    task = asyncio.create_task(short_reader())
    await asyncio.sleep(0)
    await bus.publish("b1", "k", {})
    await task
    assert bus._subs.get("b1", set()) == set()


@pytest.mark.parametrize("payload", [{"a": 1}, {"nested": {"x": [1, 2]}}])
async def test_payloads_passthrough(payload: dict) -> None:
    bus = BatchEventBus()
    got: list[Event] = []

    async def reader() -> None:
        async for event in bus.subscribe("b1"):
            got.append(event)
            break

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    await bus.publish("b1", "k", payload)
    await task
    assert got[0].payload == payload
