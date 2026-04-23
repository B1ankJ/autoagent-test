from autoagent.executors.response_extractor import _is_suspect


def test_is_suspect_detects_short_or_truncated_text() -> None:
    assert _is_suspect("")
    assert _is_suspect("..")
    assert _is_suspect("abc…")
    assert not _is_suspect("完整回答")
