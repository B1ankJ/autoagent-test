from pytest_httpx import HTTPXMock

from autoagent.models.api import SampleResult
from autoagent.webhooks.sender import send_webhook


def _res() -> SampleResult:
    return SampleResult(
        id="t1",
        status="done",
        prompts_sent=["p"],
        responses=["r"],
        duration_ms=10,
        attempt_count=1,
        mode="api",
        target_profile="pf",
    )


async def test_send_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="http://example.com/cb", status_code=200)
    ok = await send_webhook("http://example.com/cb", _res())
    assert ok is True


async def test_send_retries_on_500(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="http://example.com/cb", status_code=500)
    httpx_mock.add_response(url="http://example.com/cb", status_code=500)
    httpx_mock.add_response(url="http://example.com/cb", status_code=200)
    ok = await send_webhook("http://example.com/cb", _res(), max_retries=3, base_delay=0.01)
    assert ok is True
    assert len(httpx_mock.get_requests()) == 3


async def test_send_eventually_gives_up(httpx_mock: HTTPXMock):
    for _ in range(3):
        httpx_mock.add_response(url="http://example.com/cb", status_code=500)
    ok = await send_webhook("http://example.com/cb", _res(), max_retries=3, base_delay=0.01)
    assert ok is False
