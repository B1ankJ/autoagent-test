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


# --- Same-response streak rule ---

def _stub_vlm_config(value):
    async def _get(key):
        if key == "vlm":
            return value
        if key == "notifications":
            return None
        return None

    return _get


def _stub_judge(*, normal: bool, error: str | None = None):
    async def _j(*, screenshot_paths, base_url, model, api_key, timeout_sec=30.0):
        from autoagent.notifications.vlm_judge import JudgementResult

        return JudgementResult(normal=normal, reason="stub", error=error)

    return _j


async def _stub_wl_contains_false(*args, **kwargs):
    return False


async def _stub_wl_add_record(sink):
    async def _add(profile, response):
        sink.append((profile, response))

    return _add


def _android_profile(name="p"):
    from autoagent.profiles.schemas import AndroidProfile

    return AndroidProfile(
        name=name,
        platform="android",
        package="com.example",
        input_locator={"type": "class", "value": "c"},
        response_extraction={
            "method": "ui_tree_only",
            "response_container_locator": {"type": "class", "value": "c"},
            "scroll_container_locator": {"type": "class", "value": "c"},
            "latest_bubble_match": {"type": "class", "value": "c"},
        },
    )


async def test_same_response_auto_reinit_when_enabled(monkeypatch):
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
        "same_response_auto_reinit": True,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record([]))
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=False))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    # Stub the lazily-imported reinit dependencies.
    import autoagent.api._deps as deps
    import autoagent.devices.init_jobs as init_jobs
    import autoagent.profiles.registry as registry

    monkeypatch.setattr(registry, "load_profile", lambda _n: _android_profile())
    monkeypatch.setattr(deps, "get_device_pool", lambda: object())

    def _fake_start(profile, serials, **kwargs):
        started.append((serials, kwargs))

    monkeypatch.setattr(init_jobs, "start_job", _fake_start)

    for _ in range(3):
        await rules.on_sample_result(
            _make_sample(serial="A", response="same answer"), batch_id="b"
        )
    assert len(sent) == 1
    assert "自动复位" in sent[0]["text"]
    assert started == [(["A"], {"pool": started[0][1]["pool"], "hold_timeout_sec": 300.0})]


async def test_same_response_no_reinit_when_disabled(monkeypatch):
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
        # auto_reinit omitted → default False
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record([]))
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=False))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    import autoagent.devices.init_jobs as init_jobs

    monkeypatch.setattr(init_jobs, "start_job", lambda *a, **k: started.append((a, k)))

    for _ in range(3):
        await rules.on_sample_result(
            _make_sample(serial="A", response="same answer"), batch_id="b"
        )
    assert len(sent) == 1
    assert "自动复位" not in sent[0]["text"]
    assert started == []


async def test_same_response_fires_when_vlm_abnormal(monkeypatch):
    sent: list[dict] = []
    added: list[tuple[str, str, str]] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,  # disable empty-rule for this test
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record(added))
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=False))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(3):
        await rules.on_sample_result(
            _make_sample(serial="A", response="same answer"), batch_id="b"
        )
    assert len(sent) == 1
    assert added == []  # not whitelisted when abnormal


async def test_same_response_whitelists_when_vlm_normal(monkeypatch):
    sent: list[dict] = []
    added: list[tuple[str, str, str]] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record(added))
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=True))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(3):
        await rules.on_sample_result(
            _make_sample(serial="A", response="same answer"), batch_id="b"
        )
    assert sent == []
    assert added == [("p", "same answer")]


async def test_same_response_skips_if_no_vlm(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(None))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(5):
        await rules.on_sample_result(
            _make_sample(serial="A", response="same answer"), batch_id="b"
        )
    assert sent == []


async def test_same_response_resets_on_different_text(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record([]))
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=False))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(_make_sample(serial="A", response="x"), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="A", response="x"), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="A", response="y"), batch_id="b")
    await rules.on_sample_result(_make_sample(serial="A", response="x"), batch_id="b")
    # Only 1 "x" in the current streak — no fire.
    assert sent == []


async def test_same_response_alerts_on_vlm_failure(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record([]))
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=False, error="timeout"))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(3):
        await rules.on_sample_result(
            _make_sample(serial="A", response="hi"), batch_id="b"
        )
    assert len(sent) == 1


async def test_same_response_whitelisted_skips(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))

    async def _wl_contains_true(*args, **kwargs):
        return True

    monkeypatch.setattr(rules.whitelist, "contains", _wl_contains_true)
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(5):
        await rules.on_sample_result(
            _make_sample(serial="A", response="same"), batch_id="b"
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
