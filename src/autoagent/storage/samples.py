from __future__ import annotations

import json
from datetime import timezone

from sqlalchemy import select

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
        await s.commit()


async def list_samples_for_batch(batch_id: str) -> list[SampleResult]:
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(select(SampleRow).where(SampleRow.batch_id == batch_id))
        return [_row_to_result(row) for row in r.scalars().all()]
