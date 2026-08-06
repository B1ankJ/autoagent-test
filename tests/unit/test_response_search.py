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


@pytest.mark.asyncio
async def test_search_fields_scope():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample(
        "b",
        SampleResult(id="pq", status="done", mode="api", target_profile="p",
                     prompts_sent=["问一下 唯一词A"], responses=["无关"], ended_at=now),
    )
    await upsert_sample(
        "b",
        SampleResult(id="rq", status="done", mode="api", target_profile="p",
                     prompts_sent=["无关"], responses=["答案 唯一词A"], ended_at=now),
    )

    _, all_total = await search_samples_by_response("唯一词A", fields="all", limit=20, offset=0)
    assert all_total == 2
    p_hits, p_total = await search_samples_by_response(
        "唯一词A", fields="prompt", limit=20, offset=0
    )
    assert p_total == 1 and p_hits[0].sample_id == "pq" and p_hits[0].source == "prompt"
    assert "唯一词A" in p_hits[0].snippet
    r_hits, r_total = await search_samples_by_response(
        "唯一词A", fields="response", limit=20, offset=0
    )
    assert r_total == 1 and r_hits[0].sample_id == "rq" and r_hits[0].source == "response"


@pytest.mark.asyncio
async def test_search_status_filter():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="d", status="done", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=now))
    await upsert_sample("b", SampleResult(id="f", status="failed", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=now))
    _, total = await search_samples_by_response("找我", status=["failed"], limit=20, offset=0)
    assert total == 1


@pytest.mark.asyncio
async def test_search_time_range_filter():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="recent", status="done", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=now))
    await upsert_sample("b", SampleResult(id="old", status="done", mode="api",
                                          target_profile="p", responses=["找我"],
                                          ended_at=now - timedelta(days=30)))
    await upsert_sample("b", SampleResult(id="none", status="done", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=None))
    _, total = await search_samples_by_response(
        "找我", created_after=now - timedelta(days=7), limit=20, offset=0
    )
    assert total == 1
