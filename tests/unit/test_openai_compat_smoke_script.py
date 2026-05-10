from __future__ import annotations

from types import SimpleNamespace

from scripts import openai_compat_smoke as mod


class _FakeResponse:
    def __init__(self, token: str = "jwt-token") -> None:
        self._token = token

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"token": self._token}


def test_run_chat_completion_logs_in_and_calls_openai(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, str], timeout: float):
        captured["login_url"] = url
        captured["login_json"] = json
        captured["login_timeout"] = timeout
        return _FakeResponse()

    class _Completions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return SimpleNamespace(
                id="chatcmpl_test",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="hello from compat"),
                    )
                ],
                x_autoagent=SimpleNamespace(
                    status="done",
                    responses=["hello from compat"],
                    llm_responses=[],
                    llm_errors=[],
                ),
            )

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            captured["openai_base_url"] = base_url
            captured["openai_api_key"] = api_key
            self.chat = _Chat()

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    monkeypatch.setattr(mod, "OpenAI", _FakeOpenAI)

    result = mod.run_chat_completion(
        base_url="http://localhost:8000",
        username="admin",
        password="pw",
        api_key=None,
        model="nxb",
        prompt="你好，介绍一下自己",
        new_session=False,
        timeout_sec=None,
        retry=None,
        dry_run=False,
    )

    assert captured["login_url"] == "http://localhost:8000/api/v1/auth/login"
    assert captured["login_json"] == {"username": "admin", "password": "pw"}
    assert captured["openai_base_url"] == "http://localhost:8000/v1"
    assert captured["openai_api_key"] == "jwt-token"
    assert captured["create_kwargs"] == {
        "model": "nxb",
        "messages": [{"role": "user", "content": "你好，介绍一下自己"}],
        "extra_body": {
            "new_session": False,
            "dry_run": False,
        },
    }
    assert result.message == "hello from compat"
    assert result.autoagent_status == "done"


def test_run_chat_completion_uses_static_api_key_without_login(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(*args, **kwargs):
        raise AssertionError("login should not be called when api_key is provided")

    class _Completions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return SimpleNamespace(
                id="chatcmpl_static",
                choices=[SimpleNamespace(message=SimpleNamespace(content="hello from static key"))],
                x_autoagent=SimpleNamespace(status="done"),
            )

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            captured["openai_base_url"] = base_url
            captured["openai_api_key"] = api_key
            self.chat = _Chat()

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    monkeypatch.setattr(mod, "OpenAI", _FakeOpenAI)

    result = mod.run_chat_completion(
        base_url="http://localhost:8000",
        username="admin",
        password="pw",
        api_key="static-key",
        model="nxb",
        prompt="你好，介绍一下自己",
        new_session=False,
        timeout_sec=None,
        retry=None,
        dry_run=False,
    )

    assert captured["openai_base_url"] == "http://localhost:8000/v1"
    assert captured["openai_api_key"] == "static-key"
    assert captured["create_kwargs"] == {
        "model": "nxb",
        "messages": [{"role": "user", "content": "你好，介绍一下自己"}],
        "extra_body": {
            "new_session": False,
            "dry_run": False,
        },
    }
    assert result.message == "hello from static key"
    assert result.autoagent_status == "done"
