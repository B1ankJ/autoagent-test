from __future__ import annotations

import pytest

from autoagent.models.api import SampleResult
from autoagent.notifications import rules


def _make_sample(*, serial: str | None, response: str, status: str = "done") -> SampleResult:
    return SampleResult(
        id="s1",
        status=status,  # type: ignore[arg-type]
        prompts_sent=["hi"],
        responses=[response],
        mode="gui_android",
        target_profile="p",
        metadata={"device_serial": serial} if serial else {},
    )


@pytest.fixture(autouse=True)
def _reset():
    rules._reset_streak_for_tests()


async def test_no_config_no_fire(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(rules, "_load_config", _stub_config(None))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    for _ in range(5):
        await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    assert sent == []


async def test_streak_fires_then_resets(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "https://example.com/wh",
        "empty_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    # 2 empty: no fire
    for _ in range(2):
        await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    assert sent == []

    # 3rd empty: fire
    await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    assert len(sent) == 1

    # Streak resets after fire — next 2 empties don't re-fire
    for _ in range(2):
        await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    assert len(sent) == 1


async def test_non_empty_resets_streak(monkeypatch):
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 3}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="dev1", response="ok"), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    # Only 2 in the current streak — no fire
    assert sent == []


async def test_per_device_independent(monkeypatch):
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 2}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(_make_sample(serial="A", response=""), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="B", response=""), batch_id="b")
    assert sent == []
    await rules.on_sample_result(_make_sample(serial="A", response=""), batch_id="b")
    assert len(sent) == 1
    await rules.on_sample_result(_make_sample(serial="B", response=""), batch_id="b")
    assert len(sent) == 2


async def test_failed_status_ignored(monkeypatch):
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 1}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(
        _make_sample(serial="A", response="", status="failed"), batch_id="b"
    )
    assert sent == []


def _stub_config(value):
    async def _load():
        return value

    return _load


def _capture_send(sink):
    async def _send(**kwargs):
        sink.append(kwargs)

        class _R:
            ok = True
            status_code = 200
            errcode = 0
            errmsg = "ok"

        return _R()

    return _send
