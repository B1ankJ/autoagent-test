from autoagent.scheduler.batch_scheduler import _resolve_concurrency


def test_android_concurrency_uses_available_devices() -> None:
    profile = type("P", (), {"platform": "android"})()
    samples = [type("S", (), {"target_profile": "fake_android"})()]
    assert (
        _resolve_concurrency(
            4,
            "gui_android",
            samples,
            lambda _name: profile,
            available_devices=2,
        )
        == 2
    )


def test_agent_android_concurrency_uses_available_devices() -> None:
    profile = type("P", (), {"platform": "agent_android"})()
    samples = [type("S", (), {"target_profile": "fake_agent_android"})()]
    assert (
        _resolve_concurrency(
            4,
            "agent_android",
            samples,
            lambda _name: profile,
            available_devices=2,
        )
        == 2
    )
