import pytest

from autoagent.anomalies import store
from autoagent.models.api import SampleResult
from autoagent.notifications import rules
from autoagent.storage.database import init_db


def _result(sid="s1", profile="p1"):
    return SampleResult(id=sid, status="done", mode="gui_android", target_profile=profile)


class _FakeSend:
    ok = True
    status_code = 200
    errcode = 0
    errmsg = None


async def _fake_send(*a, **k):
    return _FakeSend()


async def _fake_reinit(*a, **k):
    return True


@pytest.mark.asyncio
async def test_empty_streak_alert_writes_record(monkeypatch):
    await init_db()
    monkeypatch.setattr(rules, "send_markdown", _fake_send)
    monkeypatch.setattr(rules, "_maybe_auto_reinit", _fake_reinit)
    config = {"webhook_url": "http://x", "empty_response_threshold": 3}
    await rules._fire_empty_streak_alert(
        config=config, serial="emulator-5554", count=3, batch_id="b1", result=_result()
    )
    items, total = await store.list_anomalies(type="empty_streak", limit=10, offset=0)
    assert total == 1
    assert items[0].detail["streak_count"] == 3
    assert items[0].device_serial == "emulator-5554"


@pytest.mark.asyncio
async def test_same_response_alert_writes_record(monkeypatch):
    await init_db()
    monkeypatch.setattr(rules, "send_markdown", _fake_send)
    monkeypatch.setattr(rules, "_maybe_auto_reinit", _fake_reinit)
    config = {"webhook_url": "http://x"}
    await rules._fire_same_response_alert(
        config=config,
        serial="emulator-5554",
        profile="p1",
        response="重复了",
        refs=[("b1", "s1"), ("b2", "s2")],
        normal=False,
        reason="not a chat page",
    )
    items, total = await store.list_anomalies(type="same_response", limit=10, offset=0)
    assert total == 1
    assert items[0].batch_id == "b2" and items[0].sample_id == "s2"
    assert items[0].detail["response"] == "重复了"


@pytest.mark.asyncio
async def test_anr_alert_writes_record(monkeypatch):
    await init_db()
    monkeypatch.setattr(rules, "send_markdown", _fake_send)
    monkeypatch.setattr(rules, "_start_reinit_job", _fake_reinit)
    config = {"webhook_url": "http://x"}
    await rules._fire_anr_alert(
        config=config,
        serial="emulator-5554",
        profile_name="p1",
        package="com.x",
        batch_id="b1",
        result=_result(),
    )
    items, total = await store.list_anomalies(type="anr", limit=10, offset=0)
    assert total == 1
    assert items[0].detail["package"] == "com.x"
