import asyncio
from unittest.mock import MagicMock

import pytest
import yaml
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
    assert (
        capture.json()["detail"]
        == "profile builder capture connect failed: cannot connect to serial-1"
    )


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

    profile_builder_mod._SESSIONS[original_session["id"]] = (
        ProfileBuilderSessionView.model_validate(original_session)
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


async def test_profile_builder_concurrent_capture_preserves_both_records(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    from pathlib import Path

    from autoagent.executors.profile_builder_capture import CapturedState

    started_steps: set[str] = set()
    both_started = asyncio.Event()

    async def _capture(device, session_dir: Path, step: str) -> CapturedState:
        session_dir.mkdir(parents=True, exist_ok=True)
        xml_path = session_dir / f"capture_{step}.xml"
        screenshot_path = session_dir / f"capture_{step}.png"
        xml_path.write_text(f"<hierarchy step='{step}'/>", encoding="utf-8")
        screenshot_path.write_bytes(f"{step}-png".encode())
        started_steps.add(step)
        if len(started_steps) == 2:
            both_started.set()
        await both_started.wait()
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=f".{step.capitalize()}Activity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: object())
    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)

    idle_response, editing_response = await asyncio.gather(
        client.post(
            f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
            headers=headers,
        ),
        client.post(
            f"/api/v1/profile-builder/sessions/{session['id']}/capture/editing",
            headers=headers,
        ),
    )

    assert idle_response.status_code == 200
    assert editing_response.status_code == 200

    fetched = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["captures"] == [
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


async def test_profile_builder_generate_draft_persists_rule_artifacts(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    device = MagicMock()
    device.dump_hierarchy.side_effect = [
        (
            '<hierarchy><node text="发消息或按住说话..." class="android.widget.TextView" '
            'bounds="[177,2066][777,2123]" /></hierarchy>'
        ),
        (
            '<hierarchy><node text="你好" class="android.widget.EditText" '
            'bounds="[36,1882][1032,2002]" /><node class="android.widget.FrameLayout" '
            'bounds="[909,2009][1020,2120]" clickable="true" /></hierarchy>'
        ),
        (
            '<hierarchy><node text="你好" class="android.widget.EditText" />'
            '<node text="当然可以" class="android.widget.TextView" /></hierarchy>'
        ),
    ]
    device.app_current.side_effect = [
        {"package": "com.aliyun.tongyi", "activity": ".IdleActivity"},
        {"package": "com.aliyun.tongyi", "activity": ".EditingActivity"},
        {"package": "com.aliyun.tongyi", "activity": ".ResponseActivity"},
    ]
    device.screenshot.side_effect = [b"idle", b"editing", b"response"]
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    for step in ("idle", "editing", "response"):
        capture = await client.post(
            f"/api/v1/profile-builder/sessions/{session['id']}/capture/{step}",
            headers=headers,
        )
        assert capture.status_code == 200

    draft = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/draft",
        headers=headers,
    )

    assert draft.status_code == 200
    body = draft.json()
    assert body["session"]["status"] == "ready"
    assert (
        body["candidates"]["input_candidates"][0]["locator"]["value"]
        == '//*[@class="android.widget.EditText"]'
    )
    assert "draft_profile.yaml" in body["session"]["artifacts"]
    assert body["draft_profile_yaml"].startswith("name: qwen")
    profile_data = yaml.safe_load(body["draft_profile_yaml"])
    assert profile_data["response_extraction"]["latest_bubble_match"] == {
        "type": "class",
        "value": "android.widget.TextView",
    }


async def test_profile_builder_review_and_validate_flow(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    artifact_dir = get_settings().data_root / "profile_builder" / session["id"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "draft_profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "qwen",
                "platform": "android",
                "package": "com.aliyun.tongyi",
                "activity": ".BrowserActivity",
                "serial": "serial-1",
                "input_method": "auto",
                "ready_check": {"type": "ui_tree_contains", "text": "发消息", "timeout_sec": 5},
                "recovery_path": [],
                "input_locator": {
                    "type": "xpath",
                    "value": '//*[@class="android.widget.EditText"]',
                },
                "send_button_locator": {
                    "type": "xpath",
                    "value": '//*[@bounds="[909,1291][1020,1402]"]',
                },
                "response_extraction": {
                    "method": "ui_tree_only",
                    "response_container_locator": {
                        "type": "xpath",
                        "value": '//*[@bounds="[48,1340][1032,1640]"]',
                    },
                    "scroll_container_locator": {
                        "type": "xpath",
                        "value": '//*[@bounds="[0,320][1080,2060]"]',
                    },
                    "latest_bubble_match": {"type": "class", "value": "android.widget.TextView"},
                },
                "new_session_action": [],
                "complete_detection": {
                    "type": "ui_tree_stable",
                    "stable_sec": 2,
                    "max_wait_sec": 180,
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    from autoagent.models.api import SampleResult

    async def _run_sync(sample):
        assert sample.target_profile == f"pb_{session['id']}"
        return SampleResult(
            id=sample.id,
            status="done",
            prompts_sent=["hello"],
            responses=["pong"],
            mode=sample.mode,
            target_profile=sample.target_profile,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.execute_sync_test", _run_sync)

    review = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/review",
        json={
            "send_button_locator": {
                "type": "xpath",
                "value": '//*[@bounds="[909,2009][1020,2120]"]',
            }
        },
        headers=headers,
    )
    assert review.status_code == 200
    assert '//*[@bounds="[909,2009][1020,2120]"]' in review.json()["draft_profile_yaml"]

    validate = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/validate",
        headers=headers,
    )
    assert validate.status_code == 200
    assert validate.json()["session"]["status"] == "validated"
    assert validate.json()["connectivity_result"]["responses"] == ["pong"]
    assert (artifact_dir / "connectivity_result.json").exists()


async def test_profile_builder_runtime_endpoint_reflects_capture_progress(client, monkeypatch):
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

    runtime = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}/runtime",
        headers=headers,
    )
    assert runtime.status_code == 200
    body = runtime.json()
    assert body["current_step"] == "capture_idle"
    assert body["captures"][0]["status"] == "done"
    assert body["captures"][0]["screenshot"] == "capture_idle.png"
