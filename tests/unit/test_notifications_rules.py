from __future__ import annotations

import pytest

from autoagent.models.api import SampleResult
from autoagent.notifications import rules


def _make_sample(
    *, serial: str | None, response: str, status: str = "done", mode: str = "gui_android"
) -> SampleResult:
    return SampleResult(
        id="s1",
        status=status,  # type: ignore[arg-type]
        prompts_sent=["hi"],
        responses=[response],
        mode=mode,  # type: ignore[arg-type]
        target_profile="p",
        metadata={"device_serial": serial} if serial else {},
    )


def _make_llm_sample(
    *,
    serial: str | None,
    raw_response: str,
    llm_response: str,
    llm_error: str | None = None,
) -> SampleResult:
    return SampleResult(
        id="s1",
        status="done",
        prompts_sent=["hi"],
        responses=[raw_response],
        llm_responses=[llm_response],
        llm_errors=[llm_error],
        mode="gui_android",
        target_profile="p",
        metadata={"device_serial": serial} if serial else {},
    )


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    rules._reset_streak_for_tests()
    # blacklist.contains hits the real kv config table (get_config), which
    # doesn't exist in these unit tests (no init_db()) — default to "not
    # blacklisted" so existing same-response-streak tests aren't affected;
    # blacklist-specific tests override this explicitly.
    async def _no_blacklist(*args, **kwargs):
        return False

    async def _noop_blacklist_add(*args, **kwargs):
        return None

    monkeypatch.setattr(rules.blacklist, "contains", _no_blacklist)
    monkeypatch.setattr(rules.blacklist, "add", _noop_blacklist_add)


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


async def test_empty_streak_alert_links_to_sample_when_app_base_url_set(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 1,
        "app_base_url": "https://autoagent.example.com/",
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    assert len(sent) == 1
    assert "[`b` / `s1`](https://autoagent.example.com/batches/b/samples/s1)" in sent[0]["text"]


async def test_empty_streak_alert_plain_text_when_no_app_base_url(monkeypatch):
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 1}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(_make_sample(serial="dev1", response=""), batch_id="b")
    assert len(sent) == 1
    assert "](https://" not in sent[0]["text"]
    assert "`b` / `s1`" in sent[0]["text"]


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


async def test_empty_streak_ignores_raw_empty_when_llm_response_present(monkeypatch):
    """Regression: a profile with LLM response extraction routinely has an
    empty raw extraction (nothing directly copyable in the UI) that LLM
    review recovers real text from — that must never count toward the
    empty-response streak."""
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 1}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(5):
        await rules.on_sample_result(
            _make_llm_sample(serial="dev1", raw_response="", llm_response="real answer"),
            batch_id="b",
        )
    assert sent == []


async def test_empty_streak_fires_when_llm_extraction_also_failed(monkeypatch):
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 1}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(
        _make_llm_sample(serial="dev1", raw_response="", llm_response="", llm_error="auth"),
        batch_id="b",
    )
    assert len(sent) == 1


async def test_failed_status_ignored(monkeypatch):
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 1}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(
        _make_sample(serial="A", response="", status="failed"), batch_id="b"
    )
    assert sent == []


async def test_empty_streak_auto_reinit_when_enabled(monkeypatch):
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 1,
        "empty_response_auto_reinit": True,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
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

    await rules.on_sample_result(_make_sample(serial="A", response=""), batch_id="b")

    assert len(sent) == 1
    assert "自动复位" in sent[0]["text"]
    assert started == [(["A"], {"pool": started[0][1]["pool"], "hold_timeout_sec": 300.0})]


async def test_empty_streak_no_reinit_when_disabled(monkeypatch):
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 1,
        # empty_response_auto_reinit omitted → default False
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    import autoagent.devices.init_jobs as init_jobs

    monkeypatch.setattr(init_jobs, "start_job", lambda *a, **k: started.append((a, k)))

    await rules.on_sample_result(_make_sample(serial="A", response=""), batch_id="b")

    assert len(sent) == 1
    assert "自动复位" not in sent[0]["text"]
    assert started == []


async def test_empty_streak_reinit_independent_of_same_response_flag(monkeypatch):
    """Regression: the two rules' auto-reinit opt-ins must stay independent
    — enabling one must not silently enable the other."""
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 1,
        "empty_response_auto_reinit": False,
        "same_response_auto_reinit": True,  # the *other* rule's flag is on
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    import autoagent.devices.init_jobs as init_jobs

    monkeypatch.setattr(init_jobs, "start_job", lambda *a, **k: started.append((a, k)))

    await rules.on_sample_result(_make_sample(serial="A", response=""), batch_id="b")

    assert len(sent) == 1
    assert "自动复位" not in sent[0]["text"]
    assert started == []


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
    blacklisted: list[tuple[str, str]] = []
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

    async def _record_blacklist_add(profile, response):
        blacklisted.append((profile, response))

    monkeypatch.setattr(rules.blacklist, "add", _record_blacklist_add)
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=False))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(3):
        await rules.on_sample_result(
            _make_sample(serial="A", response="same answer"), batch_id="b"
        )
    assert len(sent) == 1
    assert added == []  # not whitelisted when abnormal
    # VLM-confirmed anomaly auto-blacklists so the next occurrence skips the
    # streak wait and VLM judge entirely (symmetric with auto-whitelisting).
    assert blacklisted == [("p", "same answer")]


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
    # The alert text should explain *why* judgement failed in human terms,
    # not just echo the raw error code.
    assert "调用 VLM 超时" in sent[0]["text"]
    assert "error=timeout" in sent[0]["text"]


async def test_same_response_alert_links_to_samples_when_app_base_url_set(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 2,
        "app_base_url": "https://autoagent.example.com",
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "get_config", _stub_vlm_config(
        {"base_url": "x", "model": "m", "api_key": "k"}
    ))
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record([]))
    monkeypatch.setattr(rules, "is_normal_chat_page", _stub_judge(normal=False))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    for _ in range(2):
        await rules.on_sample_result(_make_sample(serial="A", response="hi"), batch_id="b")
    assert len(sent) == 1
    assert "[`b` / `s1`](https://autoagent.example.com/batches/b/samples/s1)" in sent[0]["text"]


async def test_same_response_finds_jpg_screenshots(monkeypatch, tmp_path):
    """Regression: after_result screenshots write as .jpg since the JPEG
    migration, but the collection glob used to only look for .png and
    silently found nothing — misreporting a perfectly healthy VLM as
    "VLM 不可用: no_screenshots" when the real problem was a stale glob."""
    sample_dir = tmp_path / "b" / "s1"
    sample_dir.mkdir(parents=True)
    shot = sample_dir / "after_result_1.jpg"
    shot.write_bytes(b"fake-jpeg")

    class _Settings:
        logs_root = tmp_path

    monkeypatch.setattr(rules, "get_settings", lambda: _Settings())

    seen_paths: list = []

    async def _judge(*, screenshot_paths, base_url, model, api_key, timeout_sec=30.0):
        from autoagent.notifications.vlm_judge import JudgementResult

        seen_paths.extend(screenshot_paths)
        return JudgementResult(normal=True, reason="ok")

    monkeypatch.setattr(rules, "is_normal_chat_page", _judge)

    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 1,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(
        rules, "get_config", _stub_vlm_config({"base_url": "x", "model": "m", "api_key": "k"})
    )
    monkeypatch.setattr(rules.whitelist, "contains", _stub_wl_contains_false)
    monkeypatch.setattr(rules.whitelist, "add", await _stub_wl_add_record([]))

    await rules.on_sample_result(
        SampleResult(
            id="s1",
            status="done",
            prompts_sent=["hi"],
            responses=["hi"],
            mode="gui_android",
            target_profile="p",
            metadata={"device_serial": "A"},
        ),
        batch_id="b",
    )

    assert seen_paths == [shot]


async def test_same_response_streak_uses_effective_response_not_raw(monkeypatch):
    """Regression: comparing raw `responses` directly meant every sample
    from an LLM-extraction profile had an identical (empty) raw response,
    which would false-positive the same-response streak constantly. The
    streak must be keyed on the LLM-reviewed text — three *different*
    effective responses (even with identical empty raw ones) must not fire,
    and three *identical* effective responses must."""
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

    for text in ("one", "two", "three"):
        await rules.on_sample_result(
            _make_llm_sample(serial="A", raw_response="", llm_response=text), batch_id="b"
        )
    assert sent == []

    for _ in range(3):
        await rules.on_sample_result(
            _make_llm_sample(serial="A", raw_response="", llm_response="same"), batch_id="b"
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


async def test_same_response_blacklisted_fires_immediately_without_vlm(monkeypatch):
    """A blacklisted response should alert on the very first occurrence —
    no streak wait, and no VLM call at all (config.get('vlm') is never
    even consulted here, unlike the whitelist/streak-judge path)."""
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))

    async def _get_config_should_not_be_called(key):
        raise AssertionError(f"get_config({key!r}) should not be called on a blacklist hit")

    monkeypatch.setattr(rules, "get_config", _get_config_should_not_be_called)

    async def _bl_contains_true(*args, **kwargs):
        return True

    monkeypatch.setattr(rules.blacklist, "contains", _bl_contains_true)
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(_make_sample(serial="A", response="bad"), batch_id="b")

    assert len(sent) == 1
    assert "黑名单" in sent[0]["text"]


async def test_same_response_blacklist_checked_before_whitelist(monkeypatch):
    sent: list[dict] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "same_response_enabled": True,
        "same_response_threshold": 3,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))

    async def _bl_contains_true(*args, **kwargs):
        return True

    async def _wl_contains_true(*args, **kwargs):
        return True

    monkeypatch.setattr(rules.blacklist, "contains", _bl_contains_true)
    monkeypatch.setattr(rules.whitelist, "contains", _wl_contains_true)
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    await rules.on_sample_result(_make_sample(serial="A", response="bad"), batch_id="b")

    # Blacklist wins — still fires even though whitelist also (nonsensically)
    # contains this response.
    assert len(sent) == 1


# --- ANR check rule (rule 3) ---


def _patch_reinit_deps(monkeypatch, started: list[tuple]):
    import autoagent.api._deps as deps
    import autoagent.devices.init_jobs as init_jobs
    import autoagent.profiles.registry as registry

    monkeypatch.setattr(registry, "load_profile", lambda _n: _android_profile())
    monkeypatch.setattr(deps, "get_device_pool", lambda: object())

    def _fake_start(profile, serials, **kwargs):
        started.append((serials, kwargs))

    monkeypatch.setattr(init_jobs, "start_job", _fake_start)


async def test_anr_check_disabled_by_default_no_fire(monkeypatch):
    sent: list[dict] = []
    cfg = {"enabled": True, "webhook_url": "x", "empty_response_threshold": 99}
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    monkeypatch.setattr(rules.adb, "logcat_anr_check", lambda serial, package: True)

    await rules.on_sample_result(_make_sample(serial="A", response="hi"), batch_id="b")
    assert sent == []


async def test_anr_check_fires_and_reinits_on_hit(monkeypatch):
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "anr_check_enabled": True,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    monkeypatch.setattr(rules.adb, "logcat_anr_check", lambda serial, package: True)
    _patch_reinit_deps(monkeypatch, started)

    await rules.on_sample_result(_make_sample(serial="A", response="hi"), batch_id="b")

    assert len(sent) == 1
    assert "ANR" in sent[0]["text"]
    assert "自动复位" in sent[0]["text"]
    assert len(started) == 1
    serials, kwargs = started[0]
    assert serials == ["A"]
    assert kwargs["hold_timeout_sec"] == 300.0


async def test_anr_check_no_fire_when_no_hit(monkeypatch):
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "anr_check_enabled": True,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    monkeypatch.setattr(rules.adb, "logcat_anr_check", lambda serial, package: False)
    _patch_reinit_deps(monkeypatch, started)

    await rules.on_sample_result(_make_sample(serial="A", response="hi"), batch_id="b")

    assert sent == []
    assert started == []


async def test_anr_check_runs_even_when_sample_failed(monkeypatch):
    """Unlike rules 1/2, an ANR check must still run on a failed/timeout
    sample — an ANR is a plausible *cause* of the failure, not something
    that only matters once a sample cleanly succeeds."""
    sent: list[dict] = []
    started: list[tuple] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "anr_check_enabled": True,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))
    monkeypatch.setattr(rules.adb, "logcat_anr_check", lambda serial, package: True)
    _patch_reinit_deps(monkeypatch, started)

    await rules.on_sample_result(
        _make_sample(serial="A", response="", status="timeout"), batch_id="b"
    )

    assert len(sent) == 1
    assert started != []


async def test_anr_check_skips_cancelled_sample(monkeypatch):
    """A cancelled sample never reached the executor/device at all, so
    there's nothing on the device's logcat to check."""
    sent: list[dict] = []
    calls: list[str] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "anr_check_enabled": True,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    def _tracked(serial, package):
        calls.append(serial)
        return True

    monkeypatch.setattr(rules.adb, "logcat_anr_check", _tracked)

    await rules.on_sample_result(
        _make_sample(serial="A", response="", status="cancelled"), batch_id="b"
    )

    assert calls == []
    assert sent == []


async def test_anr_check_skips_non_android_mode(monkeypatch):
    sent: list[dict] = []
    calls: list[str] = []
    cfg = {
        "enabled": True,
        "webhook_url": "x",
        "empty_response_threshold": 99,
        "anr_check_enabled": True,
    }
    monkeypatch.setattr(rules, "_load_config", _stub_config(cfg))
    monkeypatch.setattr(rules, "send_markdown", _capture_send(sent))

    def _tracked(serial, package):
        calls.append(serial)
        return True

    monkeypatch.setattr(rules.adb, "logcat_anr_check", _tracked)

    await rules.on_sample_result(
        _make_sample(serial="A", response="hi", mode="agent_android"), batch_id="b"
    )

    assert calls == []
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
