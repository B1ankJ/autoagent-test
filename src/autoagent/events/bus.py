from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str
    payload: dict[str, Any]
    ts: str


class _Subscription(AsyncIterator[Event]):
    def __init__(self, bus: BatchEventBus, batch_id: str, queue: asyncio.Queue[Event]) -> None:
        self._bus = bus
        self._batch_id = batch_id
        self._queue = queue
        self._closed = False

    def __aiter__(self) -> _Subscription:
        return self

    async def __anext__(self) -> Event:
        if self._closed:
            raise StopAsyncIteration
        return await self._queue.get()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._discard_sub(self._batch_id, self._queue)

    def __del__(self) -> None:
        self._bus._discard_sub(self._batch_id, self._queue)


class BatchEventBus:
    """In-process pub/sub keyed by batch_id."""

    def __init__(self, buffer_size: int = 100) -> None:
        self._subs: dict[str, set[asyncio.Queue[Event]]] = {}
        self._seq: dict[str, int] = {}
        self._buffer: dict[str, deque[Event]] = {}
        self._buffer_size = buffer_size

    def last_seq(self, batch_id: str) -> int:
        return self._seq.get(batch_id, 0)

    async def publish(self, batch_id: str, kind: str, payload: dict[str, Any]) -> Event:
        seq = self._seq.get(batch_id, 0) + 1
        self._seq[batch_id] = seq
        event = Event(
            seq=seq,
            kind=kind,
            payload=payload,
            ts=datetime.now(timezone.utc).isoformat(),
        )
        buf = self._buffer.setdefault(batch_id, deque(maxlen=self._buffer_size))
        buf.append(event)
        for queue in list(self._subs.get(batch_id, ())):
            queue.put_nowait(event)
        return event

    def replay_since(self, batch_id: str, after_seq: int) -> list[Event]:
        buf = self._buffer.get(batch_id)
        if buf is None:
            return []
        return [event for event in buf if event.seq > after_seq]

    def subscribe(self, batch_id: str) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subs.setdefault(batch_id, set()).add(queue)
        return _Subscription(self, batch_id, queue)

    def _discard_sub(self, batch_id: str, queue: asyncio.Queue[Event]) -> None:
        subs = self._subs.get(batch_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subs.pop(batch_id, None)


_instance: BatchEventBus | None = None


def get_event_bus() -> BatchEventBus:
    global _instance
    if _instance is None:
        _instance = BatchEventBus()
    return _instance


def reset_bus_for_tests() -> None:
    global _instance
    _instance = None
