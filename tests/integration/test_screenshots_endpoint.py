from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from autoagent.auth.jwt import create_access_token
from autoagent.config.settings import get_settings
from autoagent.main import app


@pytest.fixture
def token() -> str:
    return create_access_token("admin")


def _seed(tmp_logs: Path, batch_id: str, sample_id: str) -> None:
    directory = tmp_logs / batch_id / sample_id
    directory.mkdir(parents=True)
    (directory / "01_ready.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (directory / "02_filled.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")


async def test_list_screenshots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/screenshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names == ["01_ready.png", "02_filled.png"]


async def test_download_screenshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/screenshots/01_ready.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert response.content.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "bad_name",
    [
        "../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "01_ready.jpg",
        "01_READY.png",
        "a.png",
    ],
)
async def test_download_rejects_invalid_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str, bad_name: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            f"/api/v1/batches/b1/samples/s1/screenshots/{bad_name}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in (400, 404)


async def test_list_missing_dir_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b_none/samples/s_none/screenshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json() == []
