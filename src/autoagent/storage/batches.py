from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func, select

from autoagent.models.db import Batch
from autoagent.storage.database import get_sessionmaker


async def create_batch(
    *,
    batch_id: str,
    name: str,
    mode: str,
    concurrency: int,
    total: int,
    target_profile_default: str | None,
) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        s.add(
            Batch(
                id=batch_id,
                name=name,
                mode=mode,
                concurrency=concurrency,
                total=total,
                target_profile_default=target_profile_default,
                status="queued",
                created_at=datetime.now(timezone.utc),
            )
        )
        await s.commit()


async def get_batch(batch_id: str) -> Batch | None:
    sm = get_sessionmaker()
    async with sm() as s:
        return await s.get(Batch, batch_id)


async def list_batches(limit: int = 50, offset: int = 0) -> list[Batch]:
    sm = get_sessionmaker()
    async with sm() as s:
        result = await s.execute(
            select(Batch).order_by(desc(Batch.created_at)).limit(limit).offset(offset)
        )
        return list(result.scalars().all())


async def count_batches_by_status() -> dict[str, int]:
    """Return {status: count} across all batches, plus a 'total' aggregate."""
    sm = get_sessionmaker()
    async with sm() as s:
        result = await s.execute(
            select(Batch.status, func.count(Batch.id)).group_by(Batch.status)
        )
        out: dict[str, int] = {}
        for status, count in result.all():
            out[str(status)] = int(count)
        out["total"] = sum(out.values())
        return out


async def update_batch_status(batch_id: str, status: str) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        b = await s.get(Batch, batch_id)
        if b is None:
            return
        b.status = status
        if status == "running" and b.started_at is None:
            b.started_at = datetime.now(timezone.utc)
        if status in ("done", "failed", "cancelled"):
            b.ended_at = datetime.now(timezone.utc)
        await s.commit()


async def update_batch_progress(
    batch_id: str,
    *,
    done: int,
    failed: int,
    avg_duration_ms: int | None = None,
    total_duration_ms: int | None = None,
) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        b = await s.get(Batch, batch_id)
        if b is None:
            return
        b.done = done
        b.failed = failed
        if avg_duration_ms is not None:
            b.avg_duration_ms = avg_duration_ms
        if total_duration_ms is not None:
            b.total_duration_ms = total_duration_ms
        await s.commit()
