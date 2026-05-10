from __future__ import annotations

import pytest

from autoagent.auth import bearer as mod


def test_resolve_bearer_subject_accepts_static_api_key(monkeypatch):
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: type("S", (), {"static_api_key": "permanent-key", "admin_username": "admin"})(),
    )

    subject = mod.resolve_bearer_subject("permanent-key")

    assert subject == "admin"


def test_resolve_bearer_subject_falls_back_to_jwt(monkeypatch):
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: type("S", (), {"static_api_key": "permanent-key", "admin_username": "admin"})(),
    )
    monkeypatch.setattr(
        mod,
        "decode_token",
        lambda token: {"sub": "alice"} if token == "jwt-token" else {},
    )

    subject = mod.resolve_bearer_subject("jwt-token")

    assert subject == "alice"


def test_resolve_bearer_subject_rejects_missing_subject(monkeypatch):
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: type("S", (), {"static_api_key": None, "admin_username": "admin"})(),
    )
    monkeypatch.setattr(mod, "decode_token", lambda token: {})

    with pytest.raises(mod.BearerAuthError) as exc:
        mod.resolve_bearer_subject("jwt-token")

    assert exc.value.reason == "malformed"


def test_resolve_bearer_subject_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: type("S", (), {"static_api_key": "permanent-key", "admin_username": "admin"})(),
    )

    def _raise(_token: str):
        raise RuntimeError("bad jwt")

    monkeypatch.setattr(mod, "decode_token", _raise)

    with pytest.raises(mod.BearerAuthError) as exc:
        mod.resolve_bearer_subject("wrong-token")

    assert exc.value.reason == "invalid"
