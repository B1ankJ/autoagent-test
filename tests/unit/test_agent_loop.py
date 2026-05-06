from __future__ import annotations

import base64
from unittest.mock import MagicMock

from autoagent.executors.agent_core.agent_loop import AgentLoop
from autoagent.executors.agent_core.device import Screenshot


def _screenshot() -> Screenshot:
    return Screenshot(
        base64_data=base64.b64encode(b"fake-png-bytes").decode(),
        width=1920,
        height=1080,
    )


def test_loop_finishes_on_finish_action() -> None:
    device = MagicMock()
    device.capture.return_value = _screenshot()
    client = MagicMock()
    client.call.side_effect = [
        "Action: click(100, 200)",
        'Action: type("hello")',
        'Action: finish("done")',
    ]

    loop = AgentLoop(device, client, "sys", max_steps=10)
    result = loop.run("type hello and finish")

    assert result.finished is True
    assert result.step_count == 3
    assert result.finish_message == "done"
    assert device.execute_action.call_count == 2
    assert len(result.steps) == 3
    assert result.steps[0].action["_type"] == "click"
    assert result.steps[2].action["_type"] == "finish"
    assert result.steps[0].raw == "Action: click(100, 200)"


def test_loop_stops_at_max_steps() -> None:
    device = MagicMock()
    device.capture.return_value = _screenshot()
    client = MagicMock()
    client.call.return_value = "Action: click(100, 200)"

    loop = AgentLoop(device, client, "sys", max_steps=3)
    result = loop.run("do something")

    assert result.finished is False
    assert result.step_count == 3
    assert result.finish_message == "max_steps reached"
    assert device.execute_action.call_count == 3
    assert len(result.steps) == 3


def test_loop_skips_noop_but_counts_step() -> None:
    device = MagicMock()
    device.capture.return_value = _screenshot()
    client = MagicMock()
    client.call.side_effect = [
        "gibberish output",
        'Action: finish("ok")',
    ]

    loop = AgentLoop(device, client, "sys", max_steps=10)
    result = loop.run("task")

    assert result.finished is True
    assert result.step_count == 2
    assert device.execute_action.call_count == 0
    assert result.steps[0].action["_type"] == "noop"
