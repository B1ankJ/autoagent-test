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


def _device_serial_match(serial: str):
    # Exact match on the JSON field, not a substring LIKE — the old
    # `%"device_serial"%"x"%` could false-match when a serial appears as a
    # substring elsewhere in metadata. json_extract pulls the actual value.
    return func.json_extract(Sample.metadata_json, "$.device_serial") == serial


def _is_empty_response_clause():
    """SQL clause matching sample rows whose response is effectively empty.

    Covers the shapes observed in this DB:
      NULL              → missing column
      "[]"              → wrote responses=[] (executor never appended)
      '[""]'            → wrote responses=[""] (e.g. copy_button_vlm gave up)
      '["", ...'        → multi-prompt sample with empty first response
    First-empty in multi-prompt covers OpenAI-compat single-prompt batches
    where most empty-response anomalies show up.
    """
    return or_(
        Sample.responses_json.is_(None),
        Sample.responses_json == "[]",
        Sample.responses_json == '[""]',
        Sample.responses_json.like('["", %'),
        Sample.responses_json.like('["",%'),
    )


async def list_batches(
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    target_profile: str | None = None,
    device_serial: str | None = None,
    empty_response_only: bool = False,
) -> list[Batch]:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(Batch)
        joined_samples = False

        def ensure_samples_join(stmt_):
            nonlocal joined_samples
            if not joined_samples:
                stmt_ = stmt_.outerjoin(Sample, Sample.batch_id == Batch.id)
                joined_samples = True
            return stmt_

        if q:
            # Match batch name OR any of its samples' prompt JSON. Slow on
            # huge tables but adequate for the scale here.
            term = _like_term(q)
            stmt = ensure_samples_join(stmt).where(
                or_(
                    Batch.name.like(term, escape="\\"),
                    Batch.id.like(term, escape="\\"),
                    Sample.prompts_sent_json.like(term, escape="\\"),
                )
            )
        if device_serial:
            # device_serial only exists per-sample inside metadata_json, so
            # join samples and match on the extracted JSON value.
            stmt = ensure_samples_join(stmt).where(
                _device_serial_match(device_serial)
            )
        if target_profile:
            # Match either Batch.target_profile_default (set only when the
            # explicit JSON/upload endpoints supply one) OR any sample's
            # target_profile (the column that's actually populated for
            # OpenAI-compat / sync-test entry points).
            stmt = ensure_samples_join(stmt).where(
                or_(
                    Batch.target_profile_default == target_profile,
                    Sample.target_profile == target_profile,
                )
            )
        if empty_response_only:
            # Constrain to single-sample done batches with an empty
            # response. Multi-sample batches are intentionally excluded —
            # one empty sample among many isn't the "anomaly" surface
            # this filter is for.
            stmt = stmt.where(Batch.total == 1, Batch.status == "done")
            stmt = ensure_samples_join(stmt).where(_is_empty_response_clause())
        if created_after is not None:
            stmt = stmt.where(Batch.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(Batch.created_at <= created_before)
        if joined_samples:
            stmt = stmt.distinct()
        result = await s.execute(
            stmt.order_by(desc(Batch.created_at)).limit(limit).offset(offset)
        )
        return list(result.scalars().all())


async def count_batches_by_status(
    q: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    target_profile: str | None = None,
    device_serial: str | None = None,
    empty_response_only: bool = False,
) -> dict[str, int]:
    """Return {status: count}, plus a 'total' aggregate.

    All filter args mirror list_batches so the dashboard cards stay
    consistent with the visible list.
    """
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(Batch.status, func.count(func.distinct(Batch.id)))
        joined_samples = False

        def ensure_samples_join(stmt_):
            nonlocal joined_samples
            if not joined_samples:
                stmt_ = stmt_.outerjoin(Sample, Sample.batch_id == Batch.id)
                joined_samples = True
            return stmt_

        if q:
            term = _like_term(q)
            stmt = ensure_samples_join(stmt).where(
                or_(
                    Batch.name.like(term, escape="\\"),
                    Batch.id.like(term, escape="\\"),
                    Sample.prompts_sent_json.like(term, escape="\\"),
                )
            )
        if device_serial:
            stmt = ensure_samples_join(stmt).where(
                _device_serial_match(device_serial)
            )
        if target_profile:
            stmt = ensure_samples_join(stmt).where(
                or_(
                    Batch.target_profile_default == target_profile,
                    Sample.target_profile == target_profile,
                )
            )
        if empty_response_only:
            stmt = stmt.where(Batch.total == 1, Batch.status == "done")
            stmt = ensure_samples_join(stmt).where(_is_empty_response_clause())
        if created_after is not None:
            stmt = stmt.where(Batch.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(Batch.created_at <= created_before)
        stmt = stmt.group_by(Batch.status)
        result = await s.execute(stmt)
        out: dict[str, int] = {}
        for status, count in result.all():
            out[str(status)] = int(count)
        out["total"] = sum(out.values())
        return out


async def recover_orphaned_batches() -> int:
    """Flip all queued/running batches to cancelled and stamp ended_at.

    Called from lifespan startup — any batch still marked "active" in the
    DB at boot time is by definition orphaned (there's no scheduler task
    in this process holding it), so it can never make progress and would
    otherwise wedge the UI forever.
    """
    from sqlalchemy import update as sa_update

    sm = get_sessionmaker()
    async with sm() as s:
        now = datetime.now(timezone.utc)
        result = await s.execute(
            sa_update(Batch)
            .where(Batch.status.in_(("queued", "running")))
            .values(status="cancelled", ended_at=now)
        )
        await s.commit()
        return int(result.rowcount or 0)


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


async def batch_profiles_and_devices(
    batch_ids: list[str],
) -> dict[str, tuple[list[str], list[str]]]:
    """Distinct target_profile + device_serial per batch, in one pass.

    Returns {batch_id: (profiles, devices)}. device_serial is pulled from
    Sample.metadata_json via json_extract so we don't load full rows.
    Batches with no samples are absent from the map.
    """
    if not batch_ids:
        return {}
    sm = get_sessionmaker()
    out: dict[str, tuple[set[str], set[str]]] = {b: (set(), set()) for b in batch_ids}
    async with sm() as s:
        rows = await s.execute(
            select(
                Sample.batch_id,
                Sample.target_profile,
                func.json_extract(Sample.metadata_json, "$.device_serial"),
            ).where(Sample.batch_id.in_(batch_ids))
        )
        for batch_id, profile, serial in rows.all():
            if batch_id not in out:
                continue
            if profile:
                out[batch_id][0].add(str(profile))
            if serial:
                out[batch_id][1].add(str(serial))
    return {b: (sorted(p), sorted(d)) for b, (p, d) in out.items()}


_TERMINAL_STATUSES = ("done", "failed", "cancelled")


async def list_finished_batch_ids_before(cutoff: datetime) -> list[str]:
    """IDs of terminal (done/failed/cancelled) batches created before cutoff."""
    sm = get_sessionmaker()
    async with sm() as s:
        result = await s.execute(
            select(Batch.id).where(
                Batch.status.in_(_TERMINAL_STATUSES),
                Batch.created_at < cutoff,
            )
        )
        return [row[0] for row in result.all()]


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
