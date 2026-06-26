from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, desc, func, or_, select

from autoagent.models.db import Batch, Sample
from autoagent.storage.database import get_sessionmaker


def _like_term(q: str) -> str:
    # Escape LIKE metacharacters so a user typing "%foo" doesn't match everything.
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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


async def list_batches(
    limit: int = 50, offset: int = 0, q: str | None = None
) -> list[Batch]:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(Batch)
        if q:
            # Match batch name OR any of its samples' prompt JSON. The JSON is
            # stored as a Text column so LIKE substring search works fine for
            # ad-hoc lookups. Distinct keeps multi-match samples from inflating
            # the result. Slow on huge tables but adequate for the scale here.
            term = _like_term(q)
            stmt = (
                stmt.outerjoin(Sample, Sample.batch_id == Batch.id)
                .where(
                    or_(
                        Batch.name.like(term, escape="\\"),
                        Batch.id.like(term, escape="\\"),
                        Sample.prompts_sent_json.like(term, escape="\\"),
                    )
                )
                .distinct()
            )
        result = await s.execute(
            stmt.order_by(desc(Batch.created_at)).limit(limit).offset(offset)
        )
        return list(result.scalars().all())


async def count_batches_by_status(q: str | None = None) -> dict[str, int]:
    """Return {status: count}, plus a 'total' aggregate.

    When `q` is given, counts only batches whose name/id or any sample's
    prompt JSON contains the substring. Status breakdown reflects the
    filtered set so the dashboard cards stay consistent with the list.
    """
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(Batch.status, func.count(func.distinct(Batch.id)))
        if q:
            term = _like_term(q)
            stmt = stmt.outerjoin(Sample, Sample.batch_id == Batch.id).where(
                or_(
                    Batch.name.like(term, escape="\\"),
                    Batch.id.like(term, escape="\\"),
                    Sample.prompts_sent_json.like(term, escape="\\"),
                )
            )
        stmt = stmt.group_by(Batch.status)
        result = await s.execute(stmt)
        out: dict[str, int] = {}
        for status, count in result.all():
            out[str(status)] = int(count)
        out["total"] = sum(out.values())
        return out


async def delete_batch_rows(batch_id: str) -> bool:
    """Delete the Batch row and all its Sample rows. Returns True if removed."""
    sm = get_sessionmaker()
    async with sm() as s:
        b = await s.get(Batch, batch_id)
        if b is None:
            return False
        await s.execute(delete(Sample).where(Sample.batch_id == batch_id))
        await s.delete(b)
        await s.commit()
        return True


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
