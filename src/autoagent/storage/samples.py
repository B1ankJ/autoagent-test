from __future__ import annotations

import json
from datetime import timezone

from sqlalchemy import func, select

from autoagent.models.api import SampleResult
from autoagent.models.db import Sample as SampleRow
from autoagent.storage.database import get_sessionmaker


def _row_to_result(r: SampleRow) -> SampleResult:
    return SampleResult(
        id=r.id,
        status=r.status,  # type: ignore[arg-type]
        prompts_sent=json.loads(r.prompts_sent_json or "[]"),
        responses=json.loads(r.responses_json or "[]"),
        llm_responses=json.loads(r.llm_responses_json or "[]"),
        llm_errors=json.loads(r.llm_errors_json or "[]"),
        duration_ms=r.duration_ms,
        attempt_count=r.attempt_count,
        mode=r.mode,  # type: ignore[arg-type]
        target_profile=r.target_profile,
        metadata=json.loads(r.metadata_json or "{}"),
        error=r.error,
        logs_dir=r.logs_dir,
        started_at=r.started_at.replace(tzinfo=timezone.utc) if r.started_at else None,
        ended_at=r.ended_at.replace(tzinfo=timezone.utc) if r.ended_at else None,
        session_id=r.session_id,
        new_session=r.new_session,
    )


async def upsert_sample(batch_id: str, result: SampleResult) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.get(SampleRow, (batch_id, result.id))
        if existing is None:
            existing = SampleRow(
                batch_id=batch_id,
                id=result.id,
                mode=result.mode,
                target_profile=result.target_profile,
            )
            s.add(existing)
        existing.status = result.status
        # ensure_ascii=False so non-ASCII prompts store as literal text, not
        # \uXXXX escapes — otherwise the batch search LIKE on this column
        # can never match a Chinese query.
        existing.prompts_sent_json = json.dumps(result.prompts_sent, ensure_ascii=False)
        existing.responses_json = json.dumps(result.responses, ensure_ascii=False)
        existing.llm_responses_json = json.dumps(result.llm_responses, ensure_ascii=False)
        existing.llm_errors_json = json.dumps(result.llm_errors, ensure_ascii=False)
        existing.duration_ms = result.duration_ms
        existing.attempt_count = result.attempt_count
        existing.mode = result.mode
        existing.target_profile = result.target_profile
        existing.metadata_json = json.dumps(result.metadata, ensure_ascii=False)
        existing.error = result.error
        existing.logs_dir = result.logs_dir
        existing.started_at = result.started_at
        existing.ended_at = result.ended_at
        existing.session_id = result.session_id
        existing.new_session = result.new_session
        await s.commit()


async def list_samples_for_batch(batch_id: str) -> list[SampleResult]:
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(select(SampleRow).where(SampleRow.batch_id == batch_id))
        return [_row_to_result(row) for row in r.scalars().all()]


async def list_samples_by_session_id(session_id: str) -> list[tuple[str, SampleResult]]:
    """Every Sample carrying this session_id, oldest first, as (batch_id, result).

    A multi-turn conversation stitched together via session_id (as opposed
    to multiple `prompts` in one Sample) is typically a sequence of separate
    single-sample batches, not one batch — so this queries the whole table
    rather than being scoped to a batch_id like list_samples_for_batch.
    Ordered by started_at; a turn that never reached execution (e.g. a
    device-acquisition failure, or an end_session no-op) has no started_at
    and sorts first, which is an acceptable rough edge for what's meant to
    be a debugging aid, not an authoritative ordering.
    """
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(SampleRow)
            .where(SampleRow.session_id == session_id)
            .order_by(SampleRow.started_at.asc())
        )
        return [(row.batch_id, _row_to_result(row)) for row in r.scalars().all()]


async def list_samples_for_batches(batch_ids: list[str]) -> dict[str, list[SampleResult]]:
    """Samples for many batches in a single query, grouped by batch_id.

    Batches with no samples are absent from the map.
    """
    if not batch_ids:
        return {}
    sm = get_sessionmaker()
    out: dict[str, list[SampleResult]] = {}
    async with sm() as s:
        r = await s.execute(select(SampleRow).where(SampleRow.batch_id.in_(batch_ids)))
        for row in r.scalars().all():
            out.setdefault(row.batch_id, []).append(_row_to_result(row))
    return out


async def avg_duration_by_profile() -> dict[str, float]:
    """Average Sample.duration_ms across every recorded sample, grouped by
    target_profile — the one number the Profiles list column and the
    Batches list's duration-anomaly highlight/filter both compare against.

    Samples with no duration_ms (never finished, or the branches that skip
    execution entirely — cancelled, end_session, device-acquisition
    failures) are excluded so they don't drag the average toward zero.
    """
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(SampleRow.target_profile, func.avg(SampleRow.duration_ms))
            .where(SampleRow.duration_ms.is_not(None))
            .group_by(SampleRow.target_profile)
        )
        return {profile: float(avg) for profile, avg in r.all() if avg is not None}


async def recent_durations_for_profile(profile: str, limit: int = 500) -> list[int]:
    """The profile's most recent timed durations (ms), newest first, capped
    at `limit`. Baseline for IQR duration-anomaly detection — 'recent' so the
    baseline tracks a profile drifting over time, capped so the query stays
    cheap (SQLite has no percentile function, so the list is pulled and IQR
    computed in Python). Ordered by ended_at (a timed sample always has one)."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(SampleRow.duration_ms)
            .where(SampleRow.duration_ms.is_not(None))
            .where(SampleRow.target_profile == profile)
            .order_by(SampleRow.ended_at.desc())
            .limit(limit)
        )
        return [int(d) for (d,) in r.all()]
