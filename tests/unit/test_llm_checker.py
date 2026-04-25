# tests/unit/test_llm_checker.py
import httpx
import pytest

from autoagent.executors.llm_checker import CheckResult, check_llm_api


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_check_llm_api_ok_200_with_valid_shape(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer sk-xyz"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hi"}}]},
        )

    async def _client_factory(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _client_factory)
    res = await check_llm_api("https://api/v1", "qwen-plus", "sk-xyz")
    assert res.ok is True
    assert res.stage == "ok"
    assert res.latency_ms >= 0


@pytest.mark.asyncio
async def test_check_llm_api_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "qwen-plus", "bad")
    assert res.ok is False
    assert res.stage == "auth"
    assert "invalid key" in res.message.lower() or "401" in res.message


@pytest.mark.asyncio
async def test_check_llm_api_model_not_found(monkeypatch):
    def handler(request):
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "zzz", "sk-xyz")
    assert res.ok is False
    assert res.stage == "model_not_found"


@pytest.mark.asyncio
async def test_check_llm_api_connect_failure(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "qwen-plus", "sk-xyz")
    assert res.ok is False
    assert res.stage == "connect"


@pytest.mark.asyncio
async def test_check_llm_api_response_shape(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "qwen-plus", "sk-xyz")
    assert res.ok is False
    assert res.stage == "response_shape"


def test_check_result_dataclass_fields_exist():
    r = CheckResult(ok=True, stage="ok", message="ok", latency_ms=12)
    assert (r.ok, r.stage, r.message, r.latency_ms) == (True, "ok", "ok", 12)
