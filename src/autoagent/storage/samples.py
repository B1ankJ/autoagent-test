from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, func, select

from autoagent.models.api import DailyPoint, SampleResult, SampleSearchHit
from autoagent.models.db import Sample as SampleRow
from autoagent.storage.database import get_sessionmaker

_TERMINAL_EXECUTED = ("done", "failed", "timeout", "extraction_failed")


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


async def success_stats_by_profile(since: datetime) -> dict[str, tuple[int, int]]:
    """Per profile: (done_count, terminal_count) among samples that finished
    executing (status in _TERMINAL_EXECUTED) with ended_at >= since. Non-
    terminal statuses (queued/running/cancelled) are excluded from the
    denominator — success rate is done / (things that actually ran)."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(SampleRow.target_profile, SampleRow.status, func.count())
            .where(SampleRow.status.in_(_TERMINAL_EXECUTED))
            .where(SampleRow.ended_at.is_not(None))
            .where(SampleRow.ended_at >= since)
            .group_by(SampleRow.target_profile, SampleRow.status)
        )
        out: dict[str, tuple[int, int]] = {}
        for profile, status, count in r.all():
            done, total = out.get(profile, (0, 0))
            total += count
            if status == "done":
                done += count
            out[profile] = (done, total)
        return out


async def avg_duration_by_profile(since: datetime | None = None) -> dict[str, float]:
    """Average Sample.duration_ms grouped by target_profile. When `since` is
    given, only samples with ended_at >= since count (the health dashboard's
    7-day window); default None = all-time (the Profiles list / batch
    duration-anomaly callers, unchanged)."""
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = (
            select(SampleRow.target_profile, func.avg(SampleRow.duration_ms))
            .where(SampleRow.duration_ms.is_not(None))
            .group_by(SampleRow.target_profile)
        )
        if since is not None:
            stmt = stmt.where(SampleRow.ended_at.is_not(None)).where(SampleRow.ended_at >= since)
        r = await s.execute(stmt)
        return {profile: float(avg) for profile, avg in r.all() if avg is not None}


@dataclass
class TimedSample:
    sample_id: str
    batch_id: str
    duration_ms: int
    device_serial: str | None


async def distinct_sample_profiles() -> list[str]:
    """Every target_profile that has at least one timed sample — the set
    backfill iterates (sample-derived, not on-disk, so it covers profiles
    whose YAML was deleted)."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(SampleRow.target_profile)
            .where(SampleRow.duration_ms.is_not(None))
            .distinct()
        )
        return [p for (p,) in r.all()]


async def timed_samples_for_profile(profile: str) -> list[TimedSample]:
    """A profile's timed samples (duration_ms not null), oldest first, with
    device_serial parsed best-effort from metadata_json. For backfill's
    point-in-time slide."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(
                SampleRow.id, SampleRow.batch_id, SampleRow.duration_ms, SampleRow.metadata_json
            )
            .where(SampleRow.duration_ms.is_not(None))
            .where(SampleRow.target_profile == profile)
            .order_by(SampleRow.ended_at.asc())
        )
        out: list[TimedSample] = []
        for sid, bid, dur, meta_json in r.all():
            serial = None
            if meta_json:
                try:
                    serial = json.loads(meta_json).get("device_serial")
                except (ValueError, AttributeError):
                    serial = None
            out.append(
                TimedSample(
                    sample_id=sid, batch_id=bid, duration_ms=int(dur), device_serial=serial
                )
            )
        return out


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


async def daily_stats_by_profile(since: datetime) -> dict[str, list[DailyPoint]]:
    """Per profile, a daily time series (ascending) of success rate / avg
    duration / sample count over terminal-executed samples with ended_at >=
    since. Buckets by date(ended_at); only days with samples appear."""
    day = func.strftime("%Y-%m-%d", SampleRow.ended_at)
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(
                SampleRow.target_profile,
                day.label("day"),
                func.count().label("total"),
                func.sum(case((SampleRow.status == "done", 1), else_=0)).label("done"),
                func.avg(SampleRow.duration_ms).label("avg_ms"),
            )
            .where(SampleRow.status.in_(_TERMINAL_EXECUTED))
            .where(SampleRow.ended_at.is_not(None))
            .where(SampleRow.ended_at >= since)
            .group_by(SampleRow.target_profile, "day")
            .order_by(SampleRow.target_profile, "day")
        )
        out: dict[str, list[DailyPoint]] = {}
        for profile, d, total, done, avg_ms in r.all():
            out.setdefault(profile, []).append(
                DailyPoint(
                    date=d,
                    success_rate=(done / total) if total else None,
                    avg_duration_ms=float(avg_ms) if avg_ms is not None else None,
                    sample_count=int(total),
                )
            )
        return out


def _like_term(q: str) -> str:
    # Local copy (batches.py has the same helper, but importing it here would
    # be circular since batches imports from this module). Escapes LIKE
    # metacharacters so a "%foo" query doesn't match everything.
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _snippet(text: str, q: str, radius: int = 40) -> str:
    lo = text.lower().find(q.lower())
    if lo < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, lo - radius)
    end = min(len(text), lo + len(q) + radius)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def _first_match(items: list, q: str) -> str | None:
    ql = q.lower()
    for it in items:
        if isinstance(it, str) and ql in it.lower():
            return it
    return None


async def search_samples_by_response(
    q: str, target_profile: str | None = None, *, limit: int, offset: int
) -> tuple[list[SampleSearchHit], int]:
    """Cross-batch search over responses_json + llm_responses_json (substring
    LIKE, escaped). Returns matching samples (newest first) with a snippet of
    the matched response and its source, plus a total count."""
    term = _like_term(q)
    match = SampleRow.responses_json.like(term, escape="\\") | SampleRow.llm_responses_json.like(
        term, escape="\\"
    )
    sm = get_sessionmaker()
    async with sm() as s:
        conds = [match]
        if target_profile is not None:
            conds.append(SampleRow.target_profile == target_profile)
        total = (
            await s.execute(select(func.count()).select_from(SampleRow).where(*conds))
        ).scalar_one()
        rows = (
            (
                await s.execute(
                    select(SampleRow)
                    .where(*conds)
                    # NOT .nullslast(): "NULLS LAST" is a SQLite 3.30+ syntax
                    # (production may run older sqlite → "near NULLS: syntax
                    # error"). SQLite already sorts NULL as the smallest value,
                    # so DESC puts NULL-ended_at rows last anyway.
                    .order_by(SampleRow.ended_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        hits: list[SampleSearchHit] = []
        for r in rows:
            raw = json.loads(r.responses_json or "[]")
            llm = json.loads(r.llm_responses_json or "[]")
            matched = _first_match(raw, q)
            source = "response"
            if matched is None:
                matched = _first_match(llm, q)
                source = "llm_response"
            hits.append(
                SampleSearchHit(
                    batch_id=r.batch_id,
                    sample_id=r.id,
                    target_profile=r.target_profile,
                    status=r.status,
                    ended_at=r.ended_at.replace(tzinfo=timezone.utc) if r.ended_at else None,
                    source=source,
                    snippet=_snippet(matched or "", q),
                )
            )
        return hits, int(total)
