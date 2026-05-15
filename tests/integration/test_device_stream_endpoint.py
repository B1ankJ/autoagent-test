"""Integration tests for /api/v1/devices/{serial}/input endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _auth(client: AsyncClient) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_input_tap_dispatches_adb(client):
    h = await _auth(client)
    with patch("autoagent.api.device_stream.run_input_command") as mock_run:
        r = await client.post(
            "/api/v1/devices/emulator-5554/input",
            json={"type": "tap", "x": 360, "y": 640},
            headers=h,
        )
    assert r.status_code == 204
    mock_run.assert_called_once_with("emulator-5554", {"type": "tap", "x": 360, "y": 640})


async def test_input_swipe_dispatches_adb(client):
    h = await _auth(client)
    with patch("autoagent.api.device_stream.run_input_command") as mock_run:
        r = await client.post(
            "/api/v1/devices/emulator-5554/input",
            json={"type": "swipe", "x1": 100, "y1": 500, "x2": 100, "y2": 200},
            headers=h,
        )
    assert r.status_code == 204
    mock_run.assert_called_once_with(
        "emulator-5554",
        {"type": "swipe", "x1": 100, "y1": 500, "x2": 100, "y2": 200, "duration_ms": 300},
    )


async def test_input_text_dispatches_adb(client):
    h = await _auth(client)
    with patch("autoagent.api.device_stream.run_input_command") as mock_run:
        r = await client.post(
            "/api/v1/devices/emulator-5554/input",
            json={"type": "text", "value": "hello"},
            headers=h,
        )
    assert r.status_code == 204
    mock_run.assert_called_once_with("emulator-5554", {"type": "text", "value": "hello"})


async def test_input_key_dispatches_adb(client):
    h = await _auth(client)
    with patch("autoagent.api.device_stream.run_input_command") as mock_run:
        r = await client.post(
            "/api/v1/devices/emulator-5554/input",
            json={"type": "key", "keycode": "KEYCODE_BACK"},
            headers=h,
        )
    assert r.status_code == 204
    mock_run.assert_called_once_with(
        "emulator-5554", {"type": "key", "keycode": "KEYCODE_BACK"}
    )


async def test_input_requires_auth(client):
    r = await client.post(
        "/api/v1/devices/emulator-5554/input",
        json={"type": "tap", "x": 0, "y": 0},
    )
    assert r.status_code == 401


async def test_input_rejects_invalid_serial(client):
    h = await _auth(client)
    r = await client.post(
        "/api/v1/devices/../evil/input",
        json={"type": "tap", "x": 0, "y": 0},
        headers=h,
    )
    assert r.status_code in (400, 404)


async def test_input_adb_error_returns_502(client):
    from autoagent.devices.adb import AdbCommandError

    h = await _auth(client)
    with patch(
        "autoagent.api.device_stream.run_input_command",
        side_effect=AdbCommandError("device offline"),
    ):
        r = await client.post(
            "/api/v1/devices/emulator-5554/input",
            json={"type": "tap", "x": 0, "y": 0},
            headers=h,
        )
    assert r.status_code == 502
    assert "device offline" in r.json()["detail"]
