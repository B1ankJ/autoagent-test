from datetime import datetime, timezone

import pytest

from autoagent.anomalies import store
from autoagent.maintenance import scheduler
from autoagent.storage.configs import get_config, put_config
from autoagent.storage.database import init_db


class _OkResult:
    ok = True


async def _fake_send(**kw):
    return _OkResult()


@pytest.mark.asyncio
async def test_digest_tick_sends_and_advances(monkeypatch):
    await init_db()
    sent = []

    async def _send(**kw):
        sent.append(kw)
        return _OkResult()

    monkeypatch.setattr(scheduler, "send_markdown", _send)
    await put_config(
        "notifications",
        {"enabled": True, "webhook_url": "http://x", "digest_interval_hours": 24},
    )
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    await scheduler._digest_tick_once()
    assert len(sent) == 1
    state = await get_config("anomaly_digest_state")
    assert state and state.get("last_sent")


@pytest.mark.asyncio
async def test_digest_tick_skips_send_when_no_new(monkeypatch):
    await init_db()
    sent = []

    async def _send(**kw):
        sent.append(kw)
        return _OkResult()

    monkeypatch.setattr(scheduler, "send_markdown", _send)
    await put_config(
        "notifications",
        {"enabled": True, "webhook_url": "http://x", "digest_interval_hours": 24},
    )
    await put_config(
        "anomaly_digest_state",
        {"last_sent": datetime.now(timezone.utc).isoformat()},
    )
    await scheduler._digest_tick_once()
    assert sent == []


@pytest.mark.asyncio
async def test_digest_tick_disabled(monkeypatch):
    await init_db()
    sent = []

    async def _send(**kw):
        sent.append(kw)
        return _OkResult()

    monkeypatch.setattr(scheduler, "send_markdown", _send)
    await put_config("notifications", {"enabled": False, "digest_interval_hours": 24})
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    await scheduler._digest_tick_once()
    assert sent == []
