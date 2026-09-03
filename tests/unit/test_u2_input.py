from unittest.mock import MagicMock

import pytest

from autoagent.devices import u2_input


@pytest.fixture(autouse=True)
def _clear_connection_cache():
    u2_input.reset_connections()
    yield
    u2_input.reset_connections()


def _noop_spawn(serial, connect, probe):
    """Spawn stub that does nothing (warmup never runs) — the default for tests
    that only care about the tap-time behavior, not the background warmup."""


def test_text_always_uses_shell_and_never_warms_u2():
    shell = MagicMock()
    spawn = MagicMock()
    cmd = {"type": "text", "value": "hi"}
    u2_input.send_input("s1", cmd, connect=MagicMock(), shell=shell, spawn=spawn)
    shell.assert_called_once_with("s1", cmd)
    spawn.assert_not_called()


def test_tap_with_no_ready_connection_falls_back_to_shell_and_starts_warmup():
    shell = MagicMock()
    spawn = MagicMock()
    cmd = {"type": "tap", "x": 1, "y": 2}
    u2_input.send_input("s1", cmd, connect=MagicMock(), shell=shell, spawn=spawn, probe=MagicMock())
    # never blocks on u2 — the tap goes straight to shell
    shell.assert_called_once_with("s1", cmd)
    # and a background warmup is kicked off for next time
    spawn.assert_called_once()


def test_tap_uses_u2_when_a_ready_connection_exists():
    conn = MagicMock()
    shell = MagicMock()
    u2_input._ready["s1"] = conn
    u2_input.send_input("s1", {"type": "tap", "x": 10, "y": 20}, shell=shell, spawn=MagicMock())
    conn.click.assert_called_once_with(10, 20)
    shell.assert_not_called()


def test_ready_swipe_converts_duration_ms_to_seconds():
    conn = MagicMock()
    u2_input._ready["s1"] = conn
    u2_input.send_input(
        "s1",
        {"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 500},
        shell=MagicMock(),
        spawn=MagicMock(),
    )
    conn.swipe.assert_called_once_with(1, 2, 3, 4, duration=0.5)


def test_ready_key_maps_keycode_to_u2_symbolic_name():
    conn = MagicMock()
    u2_input._ready["s1"] = conn
    u2_input.send_input(
        "s1", {"type": "key", "keycode": "KEYCODE_BACK"}, shell=MagicMock(), spawn=MagicMock()
    )
    conn.press.assert_called_once_with("back")


def test_ready_unknown_keycode_falls_back_to_shell():
    conn = MagicMock()
    shell = MagicMock()
    u2_input._ready["s1"] = conn
    cmd = {"type": "key", "keycode": "KEYCODE_MUTE"}
    u2_input.send_input("s1", cmd, shell=shell, spawn=MagicMock())
    conn.press.assert_not_called()
    shell.assert_called_once_with("s1", cmd)


def test_ready_dispatch_failure_drops_connection_and_falls_back_to_shell():
    conn = MagicMock()
    conn.click.side_effect = RuntimeError("device offline")
    shell = MagicMock()
    u2_input._ready["s1"] = conn
    cmd = {"type": "tap", "x": 1, "y": 2}
    u2_input.send_input("s1", cmd, shell=shell, spawn=MagicMock())
    shell.assert_called_once_with("s1", cmd)
    # the dead connection is dropped so a later tap re-warms instead of reusing it
    assert "s1" not in u2_input._ready


def test_warmup_success_marks_connection_ready():
    conn = MagicMock()
    connect = MagicMock(return_value=conn)
    probe = MagicMock()
    u2_input._warmup("s1", connect, probe)
    assert u2_input._ready["s1"] is conn
    probe.assert_called_once_with(conn)
    assert "s1" not in u2_input._warming


def test_warmup_failure_leaves_no_ready_and_clears_warming_flag():
    connect = MagicMock(side_effect=RuntimeError("cannot install apk"))
    u2_input._warming.add("s1")
    u2_input._warmup("s1", connect, MagicMock())
    assert "s1" not in u2_input._ready
    # cleared so a future tap can retry the warmup
    assert "s1" not in u2_input._warming


def test_warmup_is_not_started_twice_concurrently():
    spawn = MagicMock()
    cmd = {"type": "tap", "x": 1, "y": 2}
    # First tap kicks off a warmup; second tap (while still warming) must not.
    u2_input.send_input(
        "s1", cmd, connect=MagicMock(), shell=MagicMock(), spawn=spawn, probe=MagicMock()
    )
    u2_input.send_input(
        "s1", cmd, connect=MagicMock(), shell=MagicMock(), spawn=spawn, probe=MagicMock()
    )
    spawn.assert_called_once()
