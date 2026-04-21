import os
from autoagent.config.settings import get_settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "root")
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("JWT_SECRET", "s" * 32)
    monkeypatch.setenv("DEFAULT_API_TIMEOUT_SEC", "90")
    get_settings.cache_clear()
    s = get_settings()
    assert s.admin_username == "root"
    assert s.admin_password == "pw"
    assert s.default_api_timeout_sec == 90


def test_missing_jwt_secret_fails(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "a")
    monkeypatch.setenv("ADMIN_PASSWORD", "b")
    get_settings.cache_clear()
    import pytest
    with pytest.raises(Exception):
        get_settings()
