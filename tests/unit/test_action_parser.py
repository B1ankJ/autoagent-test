"""Unit tests for unified and legacy-compatible agent action parsers."""

from __future__ import annotations

from autoagent.executors.agent_core.action_parser import parse_action as parse_legacy_action
from autoagent.executors.agent_core.parser import parse_action


def test_parse_do_tap() -> None:
    result = parse_action('do(action="Tap", element=[320, 640])')
    assert result == {"_metadata": "do", "action": "Tap", "element": [320, 640]}


def test_parse_do_back() -> None:
    result = parse_action('do(action="Back")')
    assert result == {"_metadata": "do", "action": "Back"}


def test_parse_do_home() -> None:
    result = parse_action('do(action="Home")')
    assert result == {"_metadata": "do", "action": "Home"}


def test_parse_do_wait() -> None:
    result = parse_action('do(action="Wait", duration="3 seconds")')
    assert result == {"_metadata": "do", "action": "Wait", "duration": "3 seconds"}


def test_parse_do_press() -> None:
    result = parse_action('do(action="Press", key="enter")')
    assert result == {"_metadata": "do", "action": "Press", "key": "enter"}


def test_parse_do_type() -> None:
    result = parse_action('do(action="Type", text="hello world")')
    assert result == {"_metadata": "do", "action": "Type", "text": "hello world"}


def test_parse_do_scroll() -> None:
    result = parse_action('do(action="Scroll", direction="down", clicks=5)')
    assert result == {
        "_metadata": "do",
        "action": "Scroll",
        "direction": "down",
        "clicks": 5,
    }


def test_parse_finish() -> None:
    result = parse_action('finish(message="Task done")')
    assert result == {"_metadata": "finish", "message": "Task done"}


def test_parse_finish_with_unquoted_message() -> None:
    result = parse_action("finish(message=done)")
    assert result == {"_metadata": "finish", "message": "done"}


def test_parse_finish_with_parenthesized_unquoted_message() -> None:
    result = parse_action("finish(message=done(now))")
    assert result == {"_metadata": "finish", "message": "done(now)"}


def test_parse_legacy_click_positional() -> None:
    result = parse_action("Action: click(100, 200)")
    assert result == {"_metadata": "do", "action": "Tap", "element": [100, 200]}


def test_parse_legacy_click_named_args() -> None:
    result = parse_action("Action: click(x=387, y=480)")
    assert result == {"_metadata": "do", "action": "Tap", "element": [387, 480]}


def test_parse_legacy_type() -> None:
    result = parse_action('Action: type("hello world")')
    assert result == {"_metadata": "do", "action": "Type", "text": "hello world"}


def test_parse_legacy_press_enter() -> None:
    result = parse_action("Action: press(enter)")
    assert result == {"_metadata": "do", "action": "Press", "key": "enter"}


def test_parse_legacy_press_back() -> None:
    result = parse_action("Action: press(back)")
    assert result == {"_metadata": "do", "action": "Back"}


def test_parse_legacy_press_home() -> None:
    result = parse_action("Action: press(home)")
    assert result == {"_metadata": "do", "action": "Home"}


def test_parse_legacy_scroll() -> None:
    result = parse_action("Action: scroll(down, 3)")
    assert result == {"_metadata": "do", "action": "Scroll", "direction": "down", "clicks": 3}


def test_parse_extracts_answer_payload() -> None:
    result = parse_action('<answer>do(action="Tap", element=[200, 300])</answer>')
    assert result == {"_metadata": "do", "action": "Tap", "element": [200, 300]}


def test_compatibility_shim_maps_unified_tap_to_legacy_click() -> None:
    result = parse_legacy_action('do(action="Tap", element=[200, 300])')
    assert result == {"_type": "click", "x": 200, "y": 300}


def test_compatibility_shim_maps_unified_finish_to_legacy_finish() -> None:
    result = parse_legacy_action('finish(message="Task done")')
    assert result == {"_type": "finish", "message": "Task done"}


def test_compatibility_shim_maps_unquoted_finish_to_legacy_finish() -> None:
    result = parse_legacy_action("finish(message=done)")
    assert result == {"_type": "finish", "message": "done"}


def test_compatibility_shim_maps_parenthesized_unquoted_finish_to_legacy_finish() -> None:
    result = parse_legacy_action("finish(message=done(now))")
    assert result == {"_type": "finish", "message": "done(now)"}


def test_compatibility_shim_maps_structured_do_finish_to_legacy_finish() -> None:
    result = parse_legacy_action('do(action="Finish", message="done")')
    assert result == {"_type": "finish", "message": "done"}


def test_compatibility_shim_preserves_legacy_click_format() -> None:
    result = parse_legacy_action("Action: click(100, 200)")
    assert result == {"_type": "click", "x": 100, "y": 200}


def test_compatibility_shim_handles_unified_wait() -> None:
    result = parse_legacy_action('do(action="Wait", duration="3 seconds")')
    assert result == {"_type": "wait", "seconds": 3.0}


def test_compatibility_shim_degrades_invalid_wait_to_noop() -> None:
    result = parse_legacy_action('do(action="Wait", duration="soon")')
    assert result == {"_type": "noop"}


def test_compatibility_shim_degrades_invalid_tap_coordinates_to_noop() -> None:
    result = parse_legacy_action('do(action="Tap", element=["a", "b"])')
    assert result == {"_type": "noop"}


def test_compatibility_shim_maps_swipe_to_legacy_scroll() -> None:
    result = parse_legacy_action('do(action="Swipe", start=[500, 800], end=[500, 200])')
    assert result == {"_type": "scroll", "direction": "up", "amount": 3}


def test_compatibility_shim_maps_double_tap() -> None:
    result = parse_legacy_action('do(action="Double Tap", element=[320, 640])')
    assert result == {"_type": "double_click", "x": 320, "y": 640}


def test_compatibility_shim_maps_long_press() -> None:
    result = parse_legacy_action('do(action="Long Press", element=[320, 640], duration_ms=800)')
    assert result == {"_type": "long_press", "x": 320, "y": 640, "duration_ms": 800}


def test_compatibility_shim_maps_hotkey() -> None:
    result = parse_legacy_action('do(action="Hotkey", keys=["ctrl", "c"])')
    assert result == {"_type": "hotkey", "keys": ["ctrl", "c"]}


def test_parse_malformed_returns_noop_with_original_text() -> None:
    raw = "I cannot determine the action to take."
    result = parse_action(raw)
    assert result == {"_metadata": "noop", "raw": raw}


def test_parse_empty_returns_noop_with_original_text() -> None:
    result = parse_action("")
    assert result == {"_metadata": "noop", "raw": ""}


def test_compatibility_shim_returns_legacy_noop() -> None:
    result = parse_legacy_action("I cannot determine the action to take.")
    assert result == {"_type": "noop"}
