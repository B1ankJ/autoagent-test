"""Unit test for web executor LLM integration (mocks Playwright page)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoagent.executors.web_response_llm_extractor import LLMExtractionResult


@pytest.mark.asyncio
async def test_capture_html_uses_selector_when_found():
    from autoagent.executors.web_executor import _capture_html

    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="<div>hello</div>")
    result = await _capture_html(page, ".reply")
    assert result == "<div>hello</div>"
    page.evaluate.assert_called_once()
    # selector was passed as argument
    call_args = page.evaluate.call_args
    assert ".reply" in str(call_args)


@pytest.mark.asyncio
async def test_capture_html_falls_back_to_body_when_selector_missing():
    from autoagent.executors.web_executor import _capture_html

    page = AsyncMock()
    # First call (selector lookup) returns None, second call (body) returns full html
    page.evaluate = AsyncMock(side_effect=[None, "<body>full</body>"])
    result = await _capture_html(page, ".missing")
    assert result == "<body>full</body>"
    assert page.evaluate.call_count == 2


@pytest.mark.asyncio
async def test_capture_html_returns_empty_string_when_both_none():
    from autoagent.executors.web_executor import _capture_html

    page = AsyncMock()
    page.evaluate = AsyncMock(side_effect=[None, None])
    result = await _capture_html(page, ".missing")
    assert result == ""
