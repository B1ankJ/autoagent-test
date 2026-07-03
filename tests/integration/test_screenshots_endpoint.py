from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from autoagent.auth.jwt import create_access_token
from autoagent.config.settings import get_settings
from autoagent.main import app
from autoagent.models.api import SampleResult


@pytest.fixture
def token() -> str:
    return create_access_token("admin")


def _seed(tmp_logs: Path, batch_id: str, sample_id: str) -> None:
    directory = tmp_logs / batch_id / sample_id
    directory.mkdir(parents=True)
    (directory / "01_ready.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (directory / "02_filled.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")


def _seed_android_style(tmp_logs: Path, batch_id: str, sample_id: str) -> None:
    directory = tmp_logs / batch_id / sample_id
    directory.mkdir(parents=True)
    (directory / "before_input_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (directory / "after_send_1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")


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


async def test_list_screenshots_accepts_android_style_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed_android_style(logs, "b1", "s1")
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
        assert names == ["before_input_1.png", "after_send_1.png"]


async def test_list_screenshots_uses_sample_logs_dir_when_it_is_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    actual_logs = tmp_path / "data" / "logs"
    _seed_android_style(actual_logs, "b1", "s1")
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": tmp_path / "logs"}),
    )
    async def _fake_list_samples(_batch_id: str) -> list[SampleResult]:
        return [
            SampleResult(
                id="s1",
                status="done",
                mode="gui_android",
                target_profile="android_demo",
                logs_dir=str((actual_logs / "b1" / "s1").resolve()),
            )
        ]

    monkeypatch.setattr("autoagent.api.batches.list_samples_for_batch", _fake_list_samples)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/screenshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names == ["before_input_1.png", "after_send_1.png"]


async def test_list_screenshots_prefers_metadata_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    actual_logs = tmp_path / "data" / "logs"
    sample_dir = actual_logs / "b1" / "s1"
    sample_dir.mkdir(parents=True)
    for name in [
        "before_input_1.png",
        "after_input_1.png",
        "after_send_1.png",
        "after_result_1.png",
    ]:
        (sample_dir / name).write_bytes(b"\x89PNG\r\n\x1a\nfake")

    async def _fake_list_samples(_batch_id: str) -> list[SampleResult]:
        return [
            SampleResult(
                id="s1",
                status="done",
                mode="gui_android",
                target_profile="android_demo",
                logs_dir=str(sample_dir.resolve()),
                metadata={
                    "screenshots": [
                        {"name": "before_input_1.png", "label": "before_input_1"},
                        {"name": "after_input_1.png", "label": "after_input_1"},
                        {"name": "after_send_1.png", "label": "after_send_1"},
                        {"name": "after_result_1.png", "label": "after_result_1"},
                    ]
                },
            )
        ]

    monkeypatch.setattr("autoagent.api.batches.list_samples_for_batch", _fake_list_samples)
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": tmp_path / "logs"}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/screenshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names == [
            "before_input_1.png",
            "after_input_1.png",
            "after_send_1.png",
            "after_result_1.png",
        ]


async def test_list_screenshots_uses_stage_order_when_metadata_order_is_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    actual_logs = tmp_path / "data" / "logs"
    sample_dir = actual_logs / "b1" / "s1"
    sample_dir.mkdir(parents=True)
    for name in [
        "after_input_1.png",
        "after_result_1.png",
        "after_send_1.png",
        "before_input_1.png",
    ]:
        (sample_dir / name).write_bytes(b"\x89PNG\r\n\x1a\nfake")

    async def _fake_list_samples(_batch_id: str) -> list[SampleResult]:
        return [
            SampleResult(
                id="s1",
                status="done",
                mode="gui_android",
                target_profile="android_demo",
                logs_dir=str(sample_dir.resolve()),
                metadata={
                    "screenshots": [
                        {"name": "01_done_1.png", "label": "done_1"},
                    ]
                },
            )
        ]

    monkeypatch.setattr("autoagent.api.batches.list_samples_for_batch", _fake_list_samples)
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": tmp_path / "logs"}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/batches/b1/samples/s1/screenshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()]
        assert names == [
            "before_input_1.png",
            "after_input_1.png",
            "after_send_1.png",
            "after_result_1.png",
        ]


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


def _seed_real_png(tmp_logs: Path, batch_id: str, sample_id: str, name: str) -> None:
    from PIL import Image as _Image

    directory = tmp_logs / batch_id / sample_id
    directory.mkdir(parents=True, exist_ok=True)
    _Image.new("RGB", (1080, 2400), (30, 60, 90)).save(directory / name, format="PNG")


async def test_media_full_png_requires_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed_real_png(logs, "b1", "s1", "after_result_1.png")
    monkeypatch.setattr(
        "autoagent.api.media.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        base = "/api/v1/media/batches/b1/samples/s1/screenshot/after_result_1.png"
        # No token → 401.
        resp = await c.get(base)
        assert resp.status_code == 401
        # Full PNG.
        resp = await c.get(f"{base}?token={token}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert resp.content.startswith(b"\x89PNG")


async def test_media_thumbnail_is_smaller_jpeg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed_real_png(logs, "b1", "s1", "after_result_1.png")
    monkeypatch.setattr(
        "autoagent.api.media.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        base = "/api/v1/media/batches/b1/samples/s1/screenshot/after_result_1.png"
        full = await c.get(f"{base}?token={token}")
        thumb = await c.get(f"{base}?token={token}&w=336")
        assert thumb.status_code == 200
        assert thumb.headers["content-type"] == "image/jpeg"
        # Thumbnail is meaningfully smaller than the full PNG.
        assert len(thumb.content) < len(full.content)


async def test_media_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    _seed_real_png(logs, "b1", "s1", "after_result_1.png")
    monkeypatch.setattr(
        "autoagent.api.media.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/media/batches/b1/samples/s1/screenshot/01_ready.jpg",
            params={"token": token},
        )
        assert resp.status_code == 400
