"""Unit tests for the unified agent action parser."""

from __future__ import annotations

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


def test_parse_finish() -> None:
    result = parse_action('finish(message="Task done")')
    assert result == {"_metadata": "finish", "message": "Task done"}


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


def test_parse_malformed_returns_noop_with_original_text() -> None:
    raw = "I cannot determine the action to take."
    result = parse_action(raw)
    assert result == {"_metadata": "noop", "raw": raw}


def test_parse_empty_returns_noop_with_original_text() -> None:
    result = parse_action("")
    assert result == {"_metadata": "noop", "raw": ""}
