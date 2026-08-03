from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, asc, case, delete, desc, false, func, or_, select

from autoagent.models.db import Anomaly, Batch, Sample
from autoagent.storage.database import get_sessionmaker
from autoagent.storage.samples import avg_duration_by_profile


def _like_term(q: str) -> str:
    # Escape LIKE metacharacters so a user typing "%foo" doesn't match everything.
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# Whitelisted columns the Batches List UI can sort by (server-side, so it
# stays correct under pagination — a client-side Table sorter would only
# reorder whatever page happened to be fetched).
SORTABLE_COLUMNS = {"avg_duration_ms": Batch.avg_duration_ms, "started_at": Batch.started_at}


async def create_batch(
    *,
    batch_id: str,
    name: str,
    mode: str,
    concurrency: int,
    total: int,
    target_profile_default: str | None,
    samples_request_json: str | None = None,
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
                samples_request_json=samples_request_json,
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


def _has_effective_llm_response_clause():
    """True when llm_responses[0] would win under select_effective_response
    (LLM extraction ran, produced non-empty text, and reported no error).

    json_extract on a NULL/'[]'/'[""]' column safely yields SQL NULL / ''
    for a missing index 0, so this clause is False (not error) for samples
    that never had LLM extraction configured at all.
    """
    llm_response_0 = func.json_extract(Sample.llm_responses_json, "$[0]")
    llm_error_0 = func.json_extract(Sample.llm_errors_json, "$[0]")
    return and_(
        llm_error_0.is_(None),
        llm_response_0.is_not(None),
        llm_response_0 != "",
    )


def _is_end_session_noop_clause():
    """True for a Sample.end_session=true no-op turn.

    That path never calls a profile/executor at all — it just releases a
    device-session pin and returns status=done with no prompts/responses —
    so it always looks raw-empty. `session_released` is the one key that
    branch's SampleResult.metadata always has (see batch_scheduler.py's
    end_session branch), making it a reliable "this was never meant to
    produce a response" signal distinct from a real empty-response anomaly.
    """
    return func.json_extract(Sample.metadata_json, "$.session_released").is_not(None)


# A batch's duration is "anomalous" if it's more than 2x or less than 0.5x
# its profile's own historical average (across every sample ever run under
# that profile) — an arbitrary but reasonable threshold, tune if it proves
# too noisy/quiet in practice.
ANOMALY_HIGH_RATIO = 2.0
ANOMALY_LOW_RATIO = 0.5


def is_duration_anomaly(batch_avg_ms: float | None, profile_avg_ms: float | None) -> bool:
    """Plain-Python twin of _duration_anomaly_clause's condition, for the
    API layer to compute the same "anomalous?" flag it displays per row
    without going back to SQL — same ANOMALY_HIGH_RATIO/ANOMALY_LOW_RATIO
    thresholds, so the two never drift apart.
    """
    if batch_avg_ms is None or not profile_avg_ms or profile_avg_ms <= 0:
        return False
    return (
        batch_avg_ms > ANOMALY_HIGH_RATIO * profile_avg_ms
        or batch_avg_ms < ANOMALY_LOW_RATIO * profile_avg_ms
    )


def _duration_anomaly_clause(profile_averages: dict[str, float]):
    """SQL clause matching Batch rows whose own avg_duration_ms is far from
    their profile's historical average.

    Scoped to total==1 batches by the caller (same precedent as
    empty_response_only) — Batch.avg_duration_ms is an aggregate across
    every sample in the batch, and a multi-sample/multi-profile batch has
    no single well-defined "this batch's profile" to compare against.
    """
    if not profile_averages:
        # No baseline to compare against at all — nothing can be flagged.
        return false()
    threshold_avg = case(
        *[(Sample.target_profile == name, avg) for name, avg in profile_averages.items()],
        else_=None,
    )
    return and_(
        threshold_avg.is_not(None),
        threshold_avg > 0,
        or_(
            Batch.avg_duration_ms > ANOMALY_HIGH_RATIO * threshold_avg,
            Batch.avg_duration_ms < ANOMALY_LOW_RATIO * threshold_avg,
        ),
    )


def _is_empty_response_clause():
    """SQL clause matching sample rows whose *effective* response is empty.

    Mirrors select_effective_response (openai_compat/chat_completions.py):
    a sample isn't "empty" just because the raw extraction came back blank
    if LLM review recovered real text — that's what /v1/chat/completions
    would actually have returned, so it shouldn't trip the empty-response
    anomaly filter either.

    Raw-empty shapes covered:
      NULL              → missing column
      "[]"              → wrote responses=[] (executor never appended)
      '[""]'            → wrote responses=[""] (e.g. copy_button_vlm gave up)
      '["", ...'        → multi-prompt sample with empty first response
    First-empty in multi-prompt covers OpenAI-compat single-prompt batches
    where most empty-response anomalies show up.

    Also excludes Sample.end_session=true no-ops (see
    _is_end_session_noop_clause) — those are a deliberate "release the
    device, don't send anything" signal, not a failed response.
    """
    raw_empty = or_(
        Sample.responses_json.is_(None),
        Sample.responses_json == "[]",
        Sample.responses_json == '[""]',
        Sample.responses_json.like('["", %'),
        Sample.responses_json.like('["",%'),
    )
    return and_(
        raw_empty, ~_has_effective_llm_response_clause(), ~_is_end_session_noop_clause()
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
    exclude_end_session: bool = False,
    duration_anomaly_only: bool = False,
    status: list[str] | None = None,
    mode: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str = "desc",
) -> list[Batch]:
    profile_averages = await avg_duration_by_profile() if duration_anomaly_only else None
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

        if status:
            stmt = stmt.where(Batch.status.in_(status))
        if mode:
            stmt = stmt.where(Batch.mode.in_(mode))
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
            stmt = ensure_samples_join(stmt).where(_device_serial_match(device_serial))
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
        if exclude_end_session:
            stmt = ensure_samples_join(stmt).where(~_is_end_session_noop_clause())
        if duration_anomaly_only:
            # Same total==1 scoping as empty_response_only — Batch.avg_duration_ms
            # is an aggregate across every sample in the batch, so only a
            # single-sample batch has one well-defined profile to compare against.
            stmt = stmt.where(Batch.total == 1, Batch.avg_duration_ms.is_not(None))
            stmt = ensure_samples_join(stmt).where(
                _duration_anomaly_clause(profile_averages or {})
            )
        if created_after is not None:
            stmt = stmt.where(Batch.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(Batch.created_at <= created_before)
        if joined_samples:
            stmt = stmt.distinct()
        order_col = SORTABLE_COLUMNS.get(sort_by) if sort_by else None
        if order_col is not None:
            primary = asc(order_col) if sort_dir == "asc" else desc(order_col)
            # created_at as a tiebreaker keeps ordering stable for rows that
            # share the sorted value (e.g. many batches with avg_duration_ms=None).
            stmt = stmt.order_by(primary, desc(Batch.created_at))
        else:
            stmt = stmt.order_by(desc(Batch.created_at))
        result = await s.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all())


async def count_batches_by_status(
    q: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    target_profile: str | None = None,
    device_serial: str | None = None,
    empty_response_only: bool = False,
    exclude_end_session: bool = False,
    duration_anomaly_only: bool = False,
    mode: list[str] | None = None,
) -> dict[str, int]:
    """Return {status: count}, plus a 'total' aggregate.

    All filter args mirror list_batches so the dashboard cards stay
    consistent with the visible list. No `status` filter here by design —
    grouping by status is the whole point, so the caller reads the count for
    whichever status it cares about out of the returned breakdown instead.
    """
    profile_averages = await avg_duration_by_profile() if duration_anomaly_only else None
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

        if mode:
            stmt = stmt.where(Batch.mode.in_(mode))
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
            stmt = ensure_samples_join(stmt).where(_device_serial_match(device_serial))
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
        if exclude_end_session:
            stmt = ensure_samples_join(stmt).where(~_is_end_session_noop_clause())
        if duration_anomaly_only:
            stmt = stmt.where(Batch.total == 1, Batch.avg_duration_ms.is_not(None))
            stmt = ensure_samples_join(stmt).where(
                _duration_anomaly_clause(profile_averages or {})
            )
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


async def count_active_batches() -> int:
    """Number of batches currently queued or running.

    Used by the self-update gate: restarting the process kills any in-flight
    batch, so the API surfaces this count and requires force=true to proceed.
    """
    sm = get_sessionmaker()
    async with sm() as s:
        result = await s.execute(
            select(func.count()).select_from(Batch).where(Batch.status.in_(("queued", "running")))
        )
        return int(result.scalar_one() or 0)


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
        await s.execute(delete(Anomaly).where(Anomaly.batch_id == batch_id))
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
