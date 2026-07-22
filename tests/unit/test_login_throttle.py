from autoagent.auth import login_throttle as mod


def setup_function() -> None:
    mod.reset()


def test_not_locked_before_max_attempts():
    for _ in range(mod.MAX_ATTEMPTS - 1):
        mod.record_failure("alice")
    assert mod.seconds_until_unlocked("alice") is None


def test_locks_after_max_attempts():
    for _ in range(mod.MAX_ATTEMPTS):
        mod.record_failure("alice")
    assert mod.seconds_until_unlocked("alice") is not None


def test_success_clears_failure_count():
    for _ in range(mod.MAX_ATTEMPTS - 1):
        mod.record_failure("alice")
    mod.record_success("alice")
    mod.record_failure("alice")
    # Counter was reset by the success, so one more failure alone can't lock.
    assert mod.seconds_until_unlocked("alice") is None


def test_lockout_expires(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: t[0])
    for _ in range(mod.MAX_ATTEMPTS):
        mod.record_failure("alice")
    assert mod.seconds_until_unlocked("alice") is not None

    t[0] += mod.LOCKOUT_SEC + 1
    assert mod.seconds_until_unlocked("alice") is None


def test_tracking_is_per_username():
    for _ in range(mod.MAX_ATTEMPTS):
        mod.record_failure("alice")
    assert mod.seconds_until_unlocked("bob") is None


def test_bounded_tracking_evicts_oldest_username(monkeypatch):
    monkeypatch.setattr(mod, "_MAX_TRACKED", 3)
    mod.record_failure("u1")
    mod.record_failure("u2")
    mod.record_failure("u3")
    mod.record_failure("u4")  # evicts u1, the least-recently-touched entry

    assert "u1" not in mod._failures
    assert "u4" in mod._failures
