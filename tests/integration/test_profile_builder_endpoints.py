from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.config.settings import get_settings
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_profile_builder_sessions():
    from autoagent.api.profile_builder import reset_sessions_for_tests

    reset_sessions_for_tests()
    yield
    reset_sessions_for_tests()


async def _h(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_profile_builder_requires_auth(client):
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
    )
    assert create.status_code == 401

    fetched = await client.get("/api/v1/profile-builder/sessions/missing")
    assert fetched.status_code == 401


async def test_profile_builder_session_lifecycle(client):
    headers = await _h(client)

    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )

    assert create.status_code == 201
    session = create.json()
    expected_artifact_dir = str(get_settings().data_root / "profile_builder" / session["id"])

    assert session["platform"] == "android"
    assert session["device_serial"] == "serial-1"
    assert session["name"] == "qwen"
    assert session["status"] == "draft"
    assert session["steps"] == ["idle", "editing", "response"]
    assert session["artifact_dir"] == expected_artifact_dir

    fetched = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json() == session


async def test_profile_builder_capture_idle(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    device = MagicMock()
    device.dump_hierarchy.return_value = "<hierarchy><node text='发消息'/></hierarchy>"
    device.app_current.return_value = {
        "package": "com.aliyun.tongyi",
        "activity": ".BrowserActivity",
    }
    device.screenshot.return_value = b"png-bytes"
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    capture = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
        headers=headers,
    )
    assert capture.status_code == 200
    body = capture.json()
    assert "capture_idle.xml" in body["artifacts"]
    assert body["captures"] == [
        {
            "step": "idle",
            "package": "com.aliyun.tongyi",
            "activity": ".BrowserActivity",
            "xml_artifact": "capture_idle.xml",
            "screenshot_artifact": "capture_idle.png",
        }
    ]


async def test_profile_builder_capture_rejects_unknown_step(client):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    capture = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/bad-step",
        headers=headers,
    )
    assert capture.status_code == 422
    assert capture.json()["detail"] == "unknown capture step: bad-step"


async def test_profile_builder_capture_wraps_device_failures(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    def _boom(serial: str):
        raise RuntimeError(f"cannot connect to {serial}")

    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", _boom)

    capture = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
        headers=headers,
    )
    assert capture.status_code == 502
    assert capture.json()["detail"] == "profile builder capture connect failed: cannot connect to serial-1"


async def test_profile_builder_session_reload_from_persisted_json(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    device = MagicMock()
    device.dump_hierarchy.return_value = "<hierarchy><node text='发消息'/></hierarchy>"
    device.app_current.return_value = {
        "package": "com.aliyun.tongyi",
        "activity": ".BrowserActivity",
    }
    device.screenshot.return_value = b"png-bytes"
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    capture = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
        headers=headers,
    )
    assert capture.status_code == 200

    from autoagent.api.profile_builder import reset_sessions_for_tests

    reset_sessions_for_tests()

    fetched = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["artifacts"] == ["capture_idle.png", "capture_idle.xml"]
    assert body["captures"] == [
        {
            "step": "idle",
            "package": "com.aliyun.tongyi",
            "activity": ".BrowserActivity",
            "xml_artifact": "capture_idle.xml",
            "screenshot_artifact": "capture_idle.png",
        }
    ]


async def test_profile_builder_capture_multi_step_accumulates_from_disk_truth(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    original_session = create.json()

    device = MagicMock()
    device.dump_hierarchy.side_effect = [
        "<hierarchy><node text='idle'/></hierarchy>",
        "<hierarchy><node text='editing'/></hierarchy>",
    ]
    device.app_current.side_effect = [
        {"package": "com.aliyun.tongyi", "activity": ".IdleActivity"},
        {"package": "com.aliyun.tongyi", "activity": ".EditingActivity"},
    ]
    device.screenshot.side_effect = [b"idle-png", b"editing-png"]
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    first = await client.post(
        f"/api/v1/profile-builder/sessions/{original_session['id']}/capture/idle",
        headers=headers,
    )
    assert first.status_code == 200

    import autoagent.api.profile_builder as profile_builder_mod
    from autoagent.models.api import ProfileBuilderSessionView

    profile_builder_mod._SESSIONS[original_session["id"]] = ProfileBuilderSessionView.model_validate(
        original_session
    )

    second = await client.post(
        f"/api/v1/profile-builder/sessions/{original_session['id']}/capture/editing",
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["captures"] == [
        {
            "step": "idle",
            "package": "com.aliyun.tongyi",
            "activity": ".IdleActivity",
            "xml_artifact": "capture_idle.xml",
            "screenshot_artifact": "capture_idle.png",
        },
        {
            "step": "editing",
            "package": "com.aliyun.tongyi",
            "activity": ".EditingActivity",
            "xml_artifact": "capture_editing.xml",
            "screenshot_artifact": "capture_editing.png",
        },
    ]


async def test_profile_builder_corrupted_session_json_returns_clear_error(client):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    from autoagent.api.profile_builder import _session_json_path, reset_sessions_for_tests

    _session_json_path(session["id"]).write_text("{not-json", encoding="utf-8")
    reset_sessions_for_tests()

    fetched = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )
    assert fetched.status_code == 500
    assert fetched.json()["detail"] == "profile builder session load failed"
