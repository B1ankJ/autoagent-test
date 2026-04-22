import importlib
from pathlib import Path

from fastapi.testclient import TestClient

import autoagent.main


def test_root_serves_index_html_when_present(tmp_path: Path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html><body>Plan 2 UI</body></html>")
    monkeypatch.setenv("AUTOAGENT_STATIC_DIR", str(static_dir))

    importlib.reload(autoagent.main)

    client = TestClient(autoagent.main.app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Plan 2 UI" in response.text


def test_root_returns_placeholder_when_no_static(tmp_path: Path, monkeypatch):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setenv("AUTOAGENT_STATIC_DIR", str(empty_dir))

    importlib.reload(autoagent.main)

    client = TestClient(autoagent.main.app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ui": "not_built"}
