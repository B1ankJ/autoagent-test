"""empty_response_only (list_batches / count_batches_by_status) must agree
with select_effective_response about what "empty" means: a sample whose raw
extraction came back blank but whose LLM review recovered real text is not
an anomaly — that recovered text is what /v1/chat/completions would actually
have returned. Same root cause as the batch-list preview bug: this filter's
SQL clause used to only look at responses_json.
"""
from __future__ import annotations

from autoagent.models.api import SampleResult
from autoagent.storage.batches import (
    count_batches_by_status,
    create_batch,
    list_batches,
    update_batch_status,
)
from autoagent.storage.database import init_db
from autoagent.storage.samples import upsert_sample


async def _single_sample_batch(batch_id: str, result: SampleResult) -> None:
    await create_batch(
        batch_id=batch_id,
        name=batch_id,
        mode=result.mode,
        concurrency=1,
        total=1,
        target_profile_default=None,
    )
    # empty_response_only only looks at status="done" batches — create_batch
    # always starts a batch as "queued".
    await update_batch_status(batch_id, "done")
    await upsert_sample(batch_id, result)


async def test_truly_empty_response_still_matches_filter():
    await init_db()
    await _single_sample_batch(
        "b_truly_empty",
        SampleResult(
            id="s1", status="done", prompts_sent=["hi"], responses=[""],
            mode="api", target_profile="p",
        ),
    )
    hits = await list_batches(limit=100, empty_response_only=True)
    assert any(b.id == "b_truly_empty" for b in hits)
    counts = await count_batches_by_status(empty_response_only=True)
    assert counts["total"] >= 1


async def test_llm_recovered_response_excluded_from_empty_filter():
    await init_db()
    await _single_sample_batch(
        "b_llm_recovered",
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=[""],
            llm_responses=["llm-reviewed answer"],
            llm_errors=[None],
            mode="gui_android",
            target_profile="p",
        ),
    )
    hits = await list_batches(limit=100, empty_response_only=True)
    assert not any(b.id == "b_llm_recovered" for b in hits)


async def test_llm_failed_falls_back_to_raw_and_still_counts_as_empty():
    await init_db()
    await _single_sample_batch(
        "b_llm_failed_empty",
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=[""],
            llm_responses=[""],
            llm_errors=["auth"],
            mode="gui_android",
            target_profile="p",
        ),
    )
    hits = await list_batches(limit=100, empty_response_only=True)
    assert any(b.id == "b_llm_failed_empty" for b in hits)


async def test_llm_empty_text_falls_back_to_raw_and_still_counts_as_empty():
    await init_db()
    await _single_sample_batch(
        "b_llm_empty_text",
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=[""],
            llm_responses=[""],
            llm_errors=[None],
            mode="gui_android",
            target_profile="p",
        ),
    )
    hits = await list_batches(limit=100, empty_response_only=True)
    assert any(b.id == "b_llm_empty_text" for b in hits)


async def test_non_empty_raw_response_never_matches_filter():
    await init_db()
    await _single_sample_batch(
        "b_normal",
        SampleResult(
            id="s1", status="done", prompts_sent=["hi"], responses=["fine"],
            mode="api", target_profile="p",
        ),
    )
    hits = await list_batches(limit=100, empty_response_only=True)
    assert not any(b.id == "b_normal" for b in hits)
