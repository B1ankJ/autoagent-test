from __future__ import annotations

import pytest

from autoagent.notifications.vlm_judge import describe_judgement_error


@pytest.mark.parametrize(
    "error,expected_substring",
    [
        ("no_screenshots", "与 VLM 服务本身无关"),
        ("no_readable_screenshots", "与 VLM 服务本身无关"),
        ("timeout", "调用 VLM 超时"),
        ("auth", "鉴权失败"),
        ("status:500", "500"),
        ("http:ConnectError", "ConnectError"),
        ("response_shape:JSONDecodeError", "格式异常"),
    ],
)
def test_describe_judgement_error_known_codes(error, expected_substring):
    assert expected_substring in describe_judgement_error(error)


def test_describe_judgement_error_unknown_code_passthrough():
    assert describe_judgement_error("something_new") == "something_new"
