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


def _seed(tmp_logs: Path, batch_id: str, sample_id: str) -> Path:
    directory = tmp_logs / batch_id / sample_id
    directory.mkdir(parents=True)
    (directory / "executor.log").write_text("2026-07-28 INFO started\n")
    (directory / "after_result_1.xml").write_text("<hierarchy/>")
    (directory / "before_result_1.xml").write_text("<hierarchy/>")
    (directory / "01_ready.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (directory / "actions.jsonl").write_text('{"type": "tap"}\n')
    return directory


def _patch_logs_root(monkeypatch: pytest.MonkeyPatch, logs: Path) -> None:
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )


async def test_list_text_artifacts_only_includes_executor_log_and_xml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    _patch_logs_root(monkeypatch, logs)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/artifacts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        # executor.log always leads; screenshots/actions.jsonl are excluded
        # (screenshots go through media.py, the rest is only in logs.zip).
        assert response.json() == [
            "executor.log",
            "after_result_1.xml",
            "before_result_1.xml",
        ]


async def test_list_text_artifacts_empty_for_missing_sample_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    _patch_logs_root(monkeypatch, logs)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/artifacts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json() == []


async def test_get_text_artifact_returns_file_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    _patch_logs_root(monkeypatch, logs)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/artifact/executor.log",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.text == "2026-07-28 INFO started\n"

        response = await c.get(
            "/api/v1/batches/b1/samples/s1/artifact/after_result_1.xml",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.text == "<hierarchy/>"


async def test_get_text_artifact_404s_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    _patch_logs_root(monkeypatch, logs)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/artifact/nope.xml",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


async def test_get_text_artifact_rejects_names_outside_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    _patch_logs_root(monkeypatch, logs)

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Not executor.log or *.xml — screenshots/action logs stay reachable
        # only via the full logs.zip download, not this endpoint.
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/artifact/actions.jsonl",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

        response = await c.get(
            "/api/v1/batches/b1/samples/s1/artifact/01_ready.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400
