from datetime import datetime, timedelta, timezone

import pytest

from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.samples import search_samples_by_response, upsert_sample


def _s(sid, profile, responses, llm=None, ended=None):
    return SampleResult(
        id=sid, status="done", mode="api", target_profile=profile,
        responses=responses, llm_responses=llm or [], ended_at=ended,
    )


@pytest.mark.asyncio
async def test_search_matches_raw_and_llm_with_snippet_and_source():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b1", _s("s1", "p", ["前面 抱歉我无法 后面的内容"], ended=now))
    await upsert_sample(
        "b1",
        _s("s2", "p", [""], llm=["LLM里也有 抱歉我无法 的"], ended=now - timedelta(minutes=1)),
    )
    await upsert_sample("b1", _s("s3", "p", ["完全无关的响应"], ended=now - timedelta(minutes=2)))

    hits, total = await search_samples_by_response("抱歉我无法", limit=20, offset=0)
    assert total == 2
    by_id = {h.sample_id: h for h in hits}
    assert by_id["s1"].source == "response" and "抱歉我无法" in by_id["s1"].snippet
    assert by_id["s2"].source == "llm_response" and "抱歉我无法" in by_id["s2"].snippet
    assert "s3" not in by_id


@pytest.mark.asyncio
async def test_search_profile_filter_and_pagination():
    await init_db()
    now = datetime.now(timezone.utc)
    for i in range(5):
        await upsert_sample("b", _s(f"a{i}", "pa", ["hit here"], ended=now - timedelta(minutes=i)))
    await upsert_sample("b", _s("bb", "pb", ["hit here"], ended=now))

    _, total_pa = await search_samples_by_response("hit", target_profile="pa", limit=20, offset=0)
    assert total_pa == 5
    page1, total_all = await search_samples_by_response("hit", limit=2, offset=0)
    assert total_all == 6 and len(page1) == 2


@pytest.mark.asyncio
async def test_search_handles_null_ended_at_and_sorts_it_last():
    # Regression: the ordering must not use "NULLS LAST" SQL (SQLite 3.30+
    # only; older production sqlite raises "near NULLS: syntax error").
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", _s("timed", "p", ["hit here"], ended=now))
    await upsert_sample("b", _s("nulltime", "p", ["hit here"], ended=None))
    hits, total = await search_samples_by_response("hit", limit=20, offset=0)
    assert total == 2
    # both returned; the NULL-ended_at row sorts after the timed one under DESC
    assert [h.sample_id for h in hits] == ["timed", "nulltime"]


@pytest.mark.asyncio
async def test_search_escapes_like_metachars():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", _s("s1", "p", ["no percent here"], ended=now))
    _, total = await search_samples_by_response("%", limit=20, offset=0)
    assert total == 0
