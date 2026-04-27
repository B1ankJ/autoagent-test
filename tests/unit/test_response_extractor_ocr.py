from pathlib import Path

import pytest

from autoagent.executors.response_extractor import OcrExtractor, _is_suspect


def test_is_suspect_detects_short_or_truncated_text() -> None:
    assert _is_suspect("")
    assert _is_suspect("..")
    assert _is_suspect("abc…")
    assert not _is_suspect("完整回答")


pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_ocr_fixture_matches_expected() -> None:
    fixture_dir = Path("tests/fixtures/android_screenshots")
    image = fixture_dir / "long_reply_01.png"
    expected = (fixture_dir / "long_reply_01.expected.txt").read_text(encoding="utf-8").strip()
    result = await OcrExtractor().extract_from_paths([image])
    assert result.text.strip() == expected
