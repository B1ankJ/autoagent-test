"""Unit tests for agent action parser."""

from __future__ import annotations

from autoagent.executors.agent_core.action_parser import parse_action


def test_parse_click():
    result = parse_action("Action: click(850, 420)")
    assert result == {"_type": "click", "x": 850, "y": 420}


def test_parse_type():
    result = parse_action('Action: type("hello world")')
    assert result == {"_type": "type", "text": "hello world"}


def test_parse_finish():
    result = parse_action('Action: finish("Task done")')
    assert result == {"_type": "finish", "message": "Task done"}


def test_parse_scroll_down():
    result = parse_action("Action: scroll(down, 3)")
    assert result == {"_type": "scroll", "direction": "down", "amount": 3}


def test_parse_press():
    result = parse_action("Action: press(enter)")
    assert result == {"_type": "press", "key": "enter"}


def test_parse_malformed_returns_noop():
    result = parse_action("I cannot determine the action to take.")
    assert result == {"_type": "noop"}


def test_parse_empty_returns_noop():
    result = parse_action("")
    assert result == {"_type": "noop"}


def test_parse_extracts_from_multiline():
    text = "<think>I should click the button</think>\nAction: click(100, 200)"
    result = parse_action(text)
    assert result == {"_type": "click", "x": 100, "y": 200}


def test_parse_type_with_single_quotes():
    result = parse_action("Action: type('hello')")
    assert result == {"_type": "type", "text": "hello"}


def test_parse_finish_with_chinese():
    result = parse_action('Action: finish("任务完成")')
    assert result == {"_type": "finish", "message": "任务完成"}


def test_parse_click_with_named_args():
    result = parse_action("Action: click(x=387, y=480)")
    assert result == {"_type": "click", "x": 387, "y": 480}


def test_parse_do_tap_from_answer_tag():
    result = parse_action('<answer>do(action="Tap", element=[200, 300])</answer>')
    assert result == {"_type": "click", "x": 200, "y": 300}


def test_parse_do_type():
    result = parse_action('do(action="Type", text="hello world")')
    assert result == {"_type": "type", "text": "hello world"}


def test_parse_finish_message_form():
    result = parse_action('finish(message="Task done")')
    assert result == {"_type": "finish", "message": "Task done"}


def test_parse_do_back():
    result = parse_action('do(action="Back")')
    assert result == {"_type": "press", "key": "back"}


def test_parse_do_home():
    result = parse_action('do(action="Home")')
    assert result == {"_type": "press", "key": "home"}


def test_parse_do_press():
    result = parse_action('do(action="Press", key="enter")')
    assert result == {"_type": "press", "key": "enter"}


def test_parse_do_swipe_up():
    result = parse_action('do(action="Swipe", start=[500, 800], end=[500, 200])')
    assert result == {"_type": "scroll", "direction": "up", "amount": 3}


def test_parse_do_scroll_clicks():
    result = parse_action('do(action="Scroll", clicks=5)')
    assert result == {"_type": "scroll", "direction": "down", "amount": 5}
