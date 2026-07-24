from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from autoagent.models.api import SampleResult
from autoagent.models.db import Base
from autoagent.storage.batches import create_batch, list_batches
from autoagent.storage.database import get_engine, init_db
from autoagent.storage.samples import upsert_sample


async def _batch_with_prompt(batch_id: str, prompt: str) -> None:
    await create_batch(
        batch_id=batch_id,
        name=batch_id,
        mode="api",
        concurrency=1,
        total=1,
        target_profile_default=None,
    )
    await upsert_sample(
        batch_id,
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=[prompt],
            mode="api",
            target_profile="p",
        ),
    )


@pytest.mark.asyncio
async def test_chinese_prompt_is_searchable():
    await init_db()
    await _batch_with_prompt("cjk_new", "在中国如何种植茶叶")
    # Stored as literal UTF-8, not \uXXXX escapes.
    hits = await list_batches(limit=100, q="种植茶叶")
    assert any(b.id == "cjk_new" for b in hits)


@pytest.mark.asyncio
async def test_backfill_makes_legacy_escaped_prompts_searchable():
    # Simulate a pre-Alembic DB: tables exist (as any deployment running
    # before this migration framework landed would have), but there's no
    # alembic_version table yet. init_db() should detect that and run the
    # one-time backfill migration for it (see storage/database.py's
    # "stamp to baseline, then upgrade" branch), not just stamp-and-skip.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _batch_with_prompt("cjk_legacy", "placeholder")
    # Simulate a legacy row written with ensure_ascii=True.
    escaped = json.dumps(["查询天气预报"])  # default → \uXXXX
    assert "\\u" in escaped
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE samples SET prompts_sent_json = :v WHERE batch_id = :b"),
            {"v": escaped, "b": "cjk_legacy"},
        )
    # Before backfill: Chinese query can't match the escaped column.
    assert not any(b.id == "cjk_legacy" for b in await list_batches(limit=100, q="天气预报"))

    await init_db()

    assert any(b.id == "cjk_legacy" for b in await list_batches(limit=100, q="天气预报"))
