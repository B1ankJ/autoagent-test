from unittest.mock import MagicMock

import pytest

from autoagent.devices import u2_input


@pytest.fixture(autouse=True)
def _clear_connection_cache():
    u2_input.reset_connections()
    yield
    u2_input.reset_connections()


def test_tap_goes_through_u2_not_shell():
    conn = MagicMock()
    shell = MagicMock()
    u2_input.send_input(
        "s1", {"type": "tap", "x": 10, "y": 20}, connect=lambda _s: conn, shell=shell
    )
    conn.click.assert_called_once_with(10, 20)
    shell.assert_not_called()


def test_swipe_converts_duration_ms_to_seconds():
    conn = MagicMock()
    u2_input.send_input(
        "s1",
        {"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 500},
        connect=lambda _s: conn,
        shell=MagicMock(),
    )
    conn.swipe.assert_called_once_with(1, 2, 3, 4, duration=0.5)


def test_key_maps_keycode_to_u2_symbolic_name():
    conn = MagicMock()
    u2_input.send_input(
        "s1", {"type": "key", "keycode": "KEYCODE_BACK"}, connect=lambda _s: conn, shell=MagicMock()
    )
    conn.press.assert_called_once_with("back")


def test_unknown_keycode_falls_back_to_shell():
    conn = MagicMock()
    shell = MagicMock()
    cmd = {"type": "key", "keycode": "KEYCODE_MUTE"}
    u2_input.send_input("s1", cmd, connect=lambda _s: conn, shell=shell)
    conn.press.assert_not_called()
    shell.assert_called_once_with("s1", cmd)


def test_text_always_uses_shell_never_u2():
    conn = MagicMock()
    shell = MagicMock()
    cmd = {"type": "text", "value": "hi"}
    u2_input.send_input("s1", cmd, connect=lambda _s: conn, shell=shell)
    shell.assert_called_once_with("s1", cmd)
    conn.send_keys.assert_not_called()


def test_u2_failure_invalidates_connection_and_falls_back_to_shell():
    conn = MagicMock()
    conn.click.side_effect = RuntimeError("device offline")
    shell = MagicMock()
    connect = MagicMock(side_effect=lambda _s: conn)
    cmd = {"type": "tap", "x": 1, "y": 2}
    u2_input.send_input("s1", cmd, connect=connect, shell=shell)
    shell.assert_called_once_with("s1", cmd)
    # A failed injection drops the (possibly dead) connection so the next call
    # reconnects instead of reusing it.
    assert "s1" not in u2_input._connections


def test_connection_is_cached_across_calls():
    conn = MagicMock()
    connect = MagicMock(side_effect=lambda _s: conn)
    u2_input.send_input("s1", {"type": "tap", "x": 1, "y": 2}, connect=connect, shell=MagicMock())
    u2_input.send_input("s1", {"type": "tap", "x": 3, "y": 4}, connect=connect, shell=MagicMock())
    assert connect.call_count == 1
    assert conn.click.call_count == 2
