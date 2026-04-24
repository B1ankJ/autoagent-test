import asyncio
from unittest.mock import MagicMock

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.config.settings import get_settings
from autoagent.models.api import SampleResult
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


@pytest.fixture(autouse=True)
def _mock_profile_builder_adb_keyboard(monkeypatch):
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_capture.set_ime",
        lambda _serial, _ime: None,
    )
    monkeypatch.setattr(
        "autoagent.api.profile_builder.ensure_adb_keyboard_ready",
        lambda _device: "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.api.profile_builder.set_ime",
        lambda _serial, _ime: None,
    )
    dummy_device = MagicMock()
    dummy_device.serial = "serial-1"
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda _serial: dummy_device)


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
    assert session["steps"] == ["idle", "editing"]
    assert session["artifact_dir"] == expected_artifact_dir

    fetched = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json() == session


async def test_profile_builder_session_enables_adb_keyboard_until_draft_finishes(
    client, monkeypatch
):
    headers = await _h(client)
    ime_events: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        "autoagent.api.profile_builder.ensure_adb_keyboard_ready",
        lambda device: ime_events.append(("enable", device.serial)) or "com.example/.Ime",
    )
    monkeypatch.setattr(
        "autoagent.api.profile_builder.set_ime",
        lambda serial, ime: ime_events.append(("restore", serial, ime)),
    )

    device = MagicMock()
    device.serial = "serial-1"
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    assert create.status_code == 201
    session = create.json()
    assert ime_events == [("enable", "serial-1")]

    device.dump_hierarchy.side_effect = [
        (
            '<hierarchy><node text="发消息或按住说话..." class="android.widget.TextView" '
            'bounds="[177,2066][777,2123]" /></hierarchy>'
        ),
        (
            '<hierarchy><node text="你好" class="android.widget.EditText" '
            'package="com.aliyun.tongyi" bounds="[36,1882][1032,2002]" />'
            '<node class="android.widget.FrameLayout" package="com.aliyun.tongyi" '
            'bounds="[909,2009][1020,2120]" clickable="true" /></hierarchy>'
        ),
    ]
    device.app_current.side_effect = [
        {"package": "com.aliyun.tongyi", "activity": ".IdleActivity"},
        {"package": "com.aliyun.tongyi", "activity": ".EditingActivity"},
    ]
    device.screenshot.side_effect = [b"idle", b"editing"]
    for step in ("idle", "editing"):
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
    assert ime_events == [
        ("enable", "serial-1"),
        ("restore", "serial-1", "com.example/.Ime"),
    ]


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
    assert len(body["captures"]) == 1
    assert body["captures"][0]["step"] == "idle"
    assert body["captures"][0]["active"] is True
    assert body["captures"][0]["xml_artifact"] == "capture_idle.xml"
    assert body["captures"][0]["screenshot_artifact"] == "capture_idle.png"
    assert body["captures"][0]["captured_at"] is not None


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
    assert len(body["captures"]) == 1
    assert body["captures"][0]["step"] == "idle"
    assert body["captures"][0]["active"] is True
    assert body["captures"][0]["captured_at"] is not None


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
    captures = second.json()["captures"]
    assert [capture["step"] for capture in captures] == ["idle", "editing"]
    assert all(capture["active"] is True for capture in captures)


async def test_profile_builder_capture_editing_does_not_auto_focus_from_idle(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    from pathlib import Path

    from autoagent.executors.profile_builder_capture import CapturedState

    calls: list[dict] = []

    async def _capture(
        device,
        session_dir: Path,
        step: str,
        *,
        enable_adb_keyboard: bool = False,
        focus_target: tuple[int, int] | None = None,
        focus_settle_sec: float = 0.4,
        restore_focus: bool = True,
    ) -> CapturedState:
        calls.append(
            {
                "step": step,
                "enable_adb_keyboard": enable_adb_keyboard,
                "focus_target": focus_target,
                "restore_focus": restore_focus,
            }
        )
        session_dir.mkdir(parents=True, exist_ok=True)
        xml_path = session_dir / f"capture_{step}.xml"
        screenshot_path = session_dir / f"capture_{step}.png"
        xml_path.write_text("<hierarchy/>", encoding="utf-8")
        screenshot_path.write_bytes(b"png")
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".BrowserActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)

    idle_capture = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
        headers=headers,
    )
    assert idle_capture.status_code == 200

    editing_capture = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/editing",
        headers=headers,
    )
    assert editing_capture.status_code == 200
    assert calls == [
        {
            "step": "idle",
            "enable_adb_keyboard": False,
            "focus_target": None,
            "restore_focus": True,
        },
        {
            "step": "editing",
            "enable_adb_keyboard": False,
            "focus_target": None,
            "restore_focus": True,
        },
    ]


async def test_profile_builder_repeated_capture_marks_prior_step_superseded(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    device = MagicMock()
    device.dump_hierarchy.side_effect = [
        "<hierarchy><node text='发消息'/></hierarchy>",
        "<hierarchy><node text='重新发消息'/></hierarchy>",
    ]
    device.app_current.side_effect = [
        {"package": "com.aliyun.tongyi", "activity": ".IdleActivity"},
        {"package": "com.aliyun.tongyi", "activity": ".IdleActivity"},
    ]
    device.screenshot.side_effect = [b"idle-v1", b"idle-v2"]
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    first = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
        headers=headers,
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
        headers=headers,
    )
    assert second.status_code == 200
    captures = second.json()["captures"]
    assert len(captures) == 2
    active = [capture for capture in captures if capture["active"]]
    superseded = [capture for capture in captures if not capture["active"]]
    assert len(active) == 1
    assert len(superseded) == 1
    assert active[0]["xml_artifact"] == "capture_idle.xml"
    assert active[0]["screenshot_artifact"] == "capture_idle.png"
    assert superseded[0]["xml_artifact"].startswith("capture_idle_")
    assert superseded[0]["screenshot_artifact"].startswith("capture_idle_")
    assert "capture_idle.xml" in second.json()["artifacts"]
    assert any(name.startswith("capture_idle_") for name in second.json()["artifacts"])


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


@pytest.mark.skip(
    reason="concurrent idle+editing mock deadlocks on the session-wide capture lock; "
    "tracked separately from the response-capture merge",
)
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

    async def _capture(
        device,
        session_dir: Path,
        step: str,
        *,
        enable_adb_keyboard: bool = False,
        focus_target: tuple[int, int] | None = None,
        focus_settle_sec: float = 0.4,
    ) -> CapturedState:
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
    fetched_captures = fetched.json()["captures"]
    assert [capture["step"] for capture in fetched_captures] == ["idle", "editing"]
    assert all(capture["active"] is True for capture in fetched_captures)


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
            'package="com.aliyun.tongyi" bounds="[36,1882][1032,2002]" />'
            '<node class="android.widget.FrameLayout" package="com.aliyun.tongyi" '
            'bounds="[909,2009][1020,2120]" clickable="true" />'
            '<node class="android.widget.FrameLayout" package="com.android.systemui" '
            'bounds="[962,2244][1080,2376]" clickable="true" /></hierarchy>'
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
    for step in ("idle", "editing"):
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
        == '//*[@bounds="[36,1882][1032,2002]"]'
    )
    assert "draft_profile.yaml" in body["session"]["artifacts"]
    assert body["draft_profile_yaml"].startswith("name: qwen")
    profile_data = yaml.safe_load(body["draft_profile_yaml"])
    assert profile_data["new_session_action"] == []
    assert profile_data["input_focus_action"] == [
        {
            "action": "tap_xy",
            "x": 477,
            "y": 2094,
        }
    ]
    assert body["review_items"][0]["field"] == "input_focus_action"
    assert body["review_items"][0]["recommended_option"] == [
        {"action": "tap_xy", "x": 477, "y": 2094}
    ]
    assert len(body["review_items"][0]["alternative_candidates"]) >= 2
    assert [
        {
            "action": "click_locator",
            "locator": {"type": "xpath", "value": '//*[contains(@text, "发消息")]'},
        }
    ] in body["review_items"][0]["alternative_candidates"]
    assert [
        {
            "action": "tap_xy",
            "x": 534,
            "y": 1942,
        }
    ] in body["review_items"][0]["alternative_candidates"]
    assert profile_data["input_locator"] == {
        "type": "xpath",
        "value": '//*[@bounds="[36,1882][1032,2002]"]',
    }
    assert profile_data["send_button_locator"] == {
        "type": "xpath",
        "value": '//*[@bounds="[909,2009][1020,2120]"]',
    }
    assert profile_data["send_action"] == [{"action": "tap_xy", "x": 964, "y": 2064}]
    assert any(item["field"] == "send_action" for item in body["review_items"])
    send_evidence = body["candidates"]["send_candidates"][0]["evidence_refs"][0]
    assert send_evidence["artifact"] == "capture_editing.png"
    assert send_evidence["bounds"] == [909, 2009, 1020, 2120]
    assert profile_data["response_extraction"]["latest_bubble_match"] == {
        "type": "class",
        "value": "android.widget.TextView",
    }
    input_review_item = next(
        item for item in body["review_items"] if item["field"] == "input_locator"
    )
    assert input_review_item["recommended_option"] == {
        "type": "xpath",
        "value": '//*[@bounds="[36,1882][1032,2002]"]',
    }
    assert {"type": "xpath", "value": '//*[@bounds="[177,2066][777,2123]"]'} in input_review_item[
        "alternative_candidates"
    ]
    assert input_review_item["evidence_refs"][0]["artifact"] == "capture_editing.png"
    assert any(
        refs[0]["artifact"] == "capture_idle.png"
        for refs in input_review_item["alternative_evidence_refs"]
        if refs
    )


async def test_profile_builder_generate_draft_falls_back_to_input_locator_focus_when_idle_has_no_prompt(
    client, monkeypatch
):
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
            '<hierarchy>'
            '<node text="19:58" class="android.widget.TextView" package="com.android.systemui" />'
            '<node text="百灵·专属服务顾问" class="android.widget.TextView" package="com.eg.android.AlipayGphone" />'
            '</hierarchy>'
        ),
        (
            '<hierarchy><node class="android.widget.EditText" package="com.eg.android.AlipayGphone" '
            'bounds="[92,2029][899,2090]" clickable="true" focusable="true" focused="true" />'
            '<node text="发送" class="android.widget.Image" package="com.eg.android.AlipayGphone" '
            'bounds="[915,2013][1009,2106]" clickable="false" /></hierarchy>'
        ),
    ]
    device.app_current.side_effect = [
        {
            "package": "com.eg.android.AlipayGphone",
            "activity": "com.alipay.mobile.nebulax.xriver.activity.XRiverActivity",
        },
        {
            "package": "com.eg.android.AlipayGphone",
            "activity": "com.alipay.mobile.nebulax.xriver.activity.XRiverActivity",
        },
    ]
    device.screenshot.side_effect = [b"idle", b"editing"]
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    for step in ("idle", "editing"):
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
    profile_data = yaml.safe_load(body["draft_profile_yaml"])
    assert profile_data["ready_check"]["text"] == "百灵·专属服务顾问"
    assert profile_data["input_focus_action"] == [{"action": "tap_xy", "x": 495, "y": 2059}]
    assert body["review_items"][0]["field"] == "input_focus_action"


async def test_profile_builder_generate_draft_keeps_manual_editing_send_locator(
    client, monkeypatch
):
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
            'package="com.aliyun.tongyi" bounds="[36,1164][1032,1284]" />'
            '<node class="android.widget.FrameLayout" package="com.aliyun.tongyi" '
            'bounds="[909,1291][1020,1402]" clickable="true" /></hierarchy>'
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

    for step in ("idle", "editing"):
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
    profile_data = yaml.safe_load(draft.json()["draft_profile_yaml"])
    assert profile_data["send_button_locator"] == {
        "type": "xpath",
        "value": '//*[@bounds="[909,1291][1020,1402]"]',
    }
    assert profile_data["send_action"] == [{"action": "tap_xy", "x": 964, "y": 1346}]


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
                "input_focus_action": [],
                "send_action": [],
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
        json={"send_action": [{"action": "tap_xy", "x": 964, "y": 2064}]},
        headers=headers,
    )
    assert review.status_code == 200
    assert "send_action:" in review.json()["draft_profile_yaml"]
    assert "tap_xy" in review.json()["draft_profile_yaml"]

    validate = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/validate",
        headers=headers,
    )
    assert validate.status_code == 200
    assert validate.json()["session"]["status"] == "validated"
    assert validate.json()["connectivity_result"]["responses"] == ["pong"]
    assert (artifact_dir / "connectivity_result.json").exists()


async def test_profile_builder_review_updates_input_focus_action_field(client):
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
                "input_focus_action": [],
                "send_action": [],
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

    review = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/review",
        json={"input_focus_action": [{"action": "tap_xy", "x": 477, "y": 2094}]},
        headers=headers,
    )

    assert review.status_code == 200
    updated = yaml.safe_load(review.json()["draft_profile_yaml"])
    assert updated["input_focus_action"] == [{"action": "tap_xy", "x": 477, "y": 2094}]


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


async def test_profile_builder_validate_updates_runtime_and_screens(client, monkeypatch):
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
                "package": "demo",
                "activity": ".BrowserActivity",
                "serial": "serial-1",
                "input_method": "auto",
                "ready_check": {"type": "ui_tree_contains", "text": "发消息", "timeout_sec": 5},
                "recovery_path": [],
                "input_locator": {"type": "xpath", "value": "//*[contains(@text, '发消息')]"},
                "send_button_locator": {"type": "xpath", "value": "//*[@bounds='[1,1][2,2]']"},
                "response_extraction": {
                    "method": "ui_tree_only",
                    "response_container_locator": {
                        "type": "class",
                        "value": "androidx.recyclerview.widget.RecyclerView",
                    },
                    "scroll_container_locator": {
                        "type": "class",
                        "value": "androidx.recyclerview.widget.RecyclerView",
                    },
                    "latest_bubble_match": {
                        "type": "class",
                        "value": "android.widget.TextView",
                    },
                },
                "new_session_action": [],
                "send_action": [],
                "complete_detection": {
                    "type": "ui_tree_stable",
                    "stable_sec": 2,
                    "max_wait_sec": 30,
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    async def _run_sync(sample):
        logs_dir = artifact_dir / "validate_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "before_input_1.png",
            "after_input_1.png",
            "after_send_1.png",
            "after_result_1.png",
        ):
            (logs_dir / name).write_bytes(b"png")
        return SampleResult(
            id=sample.id,
            status="done",
            prompts_sent=["hello"],
            responses=["pong"],
            mode=sample.mode,
            target_profile=sample.target_profile,
            logs_dir=str(logs_dir),
        )

    monkeypatch.setattr("autoagent.api.profile_builder.execute_sync_test", _run_sync)

    validate = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/validate",
        headers=headers,
    )
    assert validate.status_code == 200

    runtime = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}/runtime",
        headers=headers,
    )
    assert runtime.status_code == 200
    body = runtime.json()
    assert body["session_status"] == "validated"
    assert body["connectivity"]["status"] == "done"
    assert body["connectivity"]["result_summary"] == "pong"
    assert len(body["connectivity"]["screens"]) >= 1
    assert {screen["path"] for screen in body["connectivity"]["screens"]} >= {
        "validate_before_input.png",
        "validate_after_input.png",
        "validate_after_send.png",
        "validate_after_result.png",
    }
