"""_single_sample_preview (the batch-list "简略显示" preview) must agree with
select_message_content (what /v1/chat/completions actually returns) about
which text is "the response" for a sample — previously it only ever read
responses[0], so a sample whose LLM-reviewed answer (llm_responses[0])
differed from the raw extraction showed the wrong text in the list.
"""
from __future__ import annotations

from autoagent.api.batches import _single_sample_preview
from autoagent.models.api import SampleResult
from autoagent.storage.batches import create_batch
from autoagent.storage.database import init_db
from autoagent.storage.samples import upsert_sample


async def _make_batch_with_sample(batch_id: str, result: SampleResult) -> None:
    await create_batch(
        batch_id=batch_id,
        name=batch_id,
        mode=result.mode,
        concurrency=1,
        total=1,
        target_profile_default=None,
    )
    await upsert_sample(batch_id, result)


async def test_preview_prefers_llm_response_when_it_succeeded():
    await init_db()
    await _make_batch_with_sample(
        "b_llm_ok",
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=["raw extraction"],
            llm_responses=["llm-reviewed answer"],
            llm_errors=[None],
            mode="gui_android",
            target_profile="p",
        ),
    )
    prompt, response = await _single_sample_preview("b_llm_ok")
    assert prompt == "hi"
    assert response == "llm-reviewed answer"


async def test_preview_falls_back_to_raw_when_llm_failed():
    await init_db()
    await _make_batch_with_sample(
        "b_llm_failed",
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=["raw extraction"],
            llm_responses=[""],
            llm_errors=["auth"],
            mode="gui_android",
            target_profile="p",
        ),
    )
    prompt, response = await _single_sample_preview("b_llm_failed")
    assert prompt == "hi"
    assert response == "raw extraction"


async def test_preview_falls_back_to_raw_when_llm_extraction_never_ran():
    await init_db()
    await _make_batch_with_sample(
        "b_no_llm",
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=["raw extraction"],
            mode="api",
            target_profile="p",
        ),
    )
    prompt, response = await _single_sample_preview("b_no_llm")
    assert prompt == "hi"
    assert response == "raw extraction"


async def test_preview_empty_string_still_flags_true_anomaly():
    # Both raw and LLM extraction produced nothing — this really is the
    # "responded with empty" anomaly the frontend flags, not a preview bug.
    await init_db()
    await _make_batch_with_sample(
        "b_truly_empty",
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=[""],
            mode="api",
            target_profile="p",
        ),
    )
    prompt, response = await _single_sample_preview("b_truly_empty")
    assert prompt == "hi"
    assert response == ""
