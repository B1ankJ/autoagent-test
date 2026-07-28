from __future__ import annotations

from autoagent.notifications import blacklist, whitelist
from autoagent.storage.database import init_db


async def test_whitelist_add_contains_remove():
    await init_db()
    assert await whitelist.contains("p1", "hi") is False

    await whitelist.add("p1", "hi")
    assert await whitelist.contains("p1", "hi") is True
    assert await whitelist.contains("p1", "hi  ") is True  # normalized (strip)
    assert await whitelist.contains("p2", "hi") is False  # scoped per profile

    entries = await whitelist.load_all()
    assert len(entries) == 1
    assert entries[0]["target_profile"] == "p1"

    assert await whitelist.remove("p1", "hi") is True
    assert await whitelist.contains("p1", "hi") is False
    assert await whitelist.remove("p1", "hi") is False  # already gone


async def test_blacklist_add_contains_remove():
    await init_db()
    assert await blacklist.contains("p1", "bad") is False

    await blacklist.add("p1", "bad")
    assert await blacklist.contains("p1", "bad") is True

    entries = await blacklist.load_all()
    assert len(entries) == 1
    assert entries[0]["response"] == "bad"

    assert await blacklist.remove("p1", "bad") is True
    assert await blacklist.contains("p1", "bad") is False


async def test_whitelist_and_blacklist_are_independent_stores():
    """Adding the same (profile, response) to one list must not affect the
    other — they're stored under different kv keys."""
    await init_db()
    await whitelist.add("p1", "same-text")

    assert await whitelist.contains("p1", "same-text") is True
    assert await blacklist.contains("p1", "same-text") is False

    await blacklist.add("p1", "same-text")
    assert await blacklist.contains("p1", "same-text") is True
    assert await whitelist.contains("p1", "same-text") is True  # unaffected
