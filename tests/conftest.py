from pathlib import Path

import pytest

@pytest.fixture(autouse=True)
def _env_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin_pw_1234")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("LOGS_ROOT", str(tmp_path / "logs"))
    from autoagent.config.settings import get_settings
    get_settings.cache_clear()
    # Reset DB singletons so fresh tmp path is used
    import autoagent.storage.database as db_mod
    db_mod._engine = None
    db_mod._sessionmaker = None
    yield
    get_settings.cache_clear()
