import asyncio
import json
import threading
from pathlib import Path

from autoagent.executors import profile_builder_new_session
from autoagent.executors.profile_builder_capture import CapturedState
from tests.integration.test_profile_builder_endpoints import (
    _create_builder_session_with_captures,
    _mock_profile_builder_adb_keyboard,
    _reset_profile_builder_sessions,
    client,
)


async def test_generate_draft_includes_empty_new_session_builder_state(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/draft",
        json={"draft_mode": "rule", "inject_llm": False},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_session_strategy"] == "disabled"
    assert body["new_session_steps"] == []
    assert "new_session_action: []" in body["draft_profile_yaml"]


async def test_new_session_config_initializes_requested_steps(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 2},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_session_strategy"] == "guided_tap_sequence"
    assert [step["step_index"] for step in body["new_session_steps"]] == [0, 1]
    assert all(step["recommended_tap"]["status"] == "idle" for step in body["new_session_steps"])


async def test_new_session_config_returns_preview_without_persisting_incomplete_draft(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    draft_path = artifact_dir / "draft_profile.yaml"

    assert not draft_path.exists()

    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 2},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_session_strategy"] == "guided_tap_sequence"
    assert "new_session_action: []" in body["draft_profile_yaml"]
    assert not draft_path.exists()


async def test_new_session_config_truncates_higher_steps(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    initial = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 3},
        headers=headers,
    )
    assert initial.status_code == 200, initial.text

    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_session_strategy"] == "guided_tap_sequence"
    assert [step["step_index"] for step in body["new_session_steps"]] == [0]


async def test_generate_draft_recovers_malformed_new_session_state(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    state_path = artifact_dir / "new_session_state.json"
    state_path.write_text(
        json.dumps(
            {
                "strategy": "guided_tap_sequence",
                "steps": [{"step_index": "bad", "recommended_tap": "invalid"}],
            }
        ),
        encoding="utf-8",
    )

    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/draft",
        json={"draft_mode": "rule", "inject_llm": False},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_session_strategy"] == "disabled"
    assert body["new_session_steps"] == []
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "strategy": "disabled",
        "steps": [],
    }


async def test_generate_draft_recovers_empty_guided_new_session_state(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    state_path = artifact_dir / "new_session_state.json"
    state_path.write_text(
        json.dumps(
            {
                "strategy": "guided_tap_sequence",
                "steps": [],
            }
        ),
        encoding="utf-8",
    )

    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/draft",
        json={"draft_mode": "rule", "inject_llm": False},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_session_strategy"] == "disabled"
    assert body["new_session_steps"] == []
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "strategy": "disabled",
        "steps": [],
    }


async def test_new_session_state_file_is_hidden_from_session_artifacts(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 2},
        headers=headers,
    )

    assert response.status_code == 200, response.text

    get_response = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )

    assert get_response.status_code == 200, get_response.text
    assert "new_session_state.json" not in get_response.json()["artifacts"]


async def test_capture_new_session_step_records_artifacts_and_recommendation(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    async def _capture(device, session_dir, step, **_kwargs):
        assert step == "new_session_step_0"
        xml_path = session_dir / "new_session_step_0.xml"
        screenshot_path = session_dir / "new_session_step_0.png"
        xml_path.write_text("<hierarchy/>", encoding="utf-8")
        screenshot_path.write_bytes(b"png")
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".IdleActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_kwargs: {"x": 111, "y": 222, "reason": "plus button"},
    )

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    step = body["new_session_steps"][0]
    assert step["xml_artifact"] == "new_session_step_0.xml"
    assert step["screenshot_artifact"] == "new_session_step_0.png"
    assert step["recommended_tap"]["point"] == {"x": 111, "y": 222}
    assert step["recommended_tap"]["reason"] == "plus button"
    assert step["recommended_tap"]["status"] == "ready"
    assert step["confirmed_tap"] is None
    assert "new_session_step_0.xml" in body["session"]["artifacts"]
    assert "new_session_step_0.png" in body["session"]["artifacts"]


async def test_capture_new_session_step_handles_recommendation_failure(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    state_path = artifact_dir / "new_session_state.json"

    async def _capture(device, session_dir, step, **_kwargs):
        xml_path = session_dir / "new_session_step_0.xml"
        screenshot_path = session_dir / "new_session_step_0.png"
        xml_path.write_text("<hierarchy/>", encoding="utf-8")
        screenshot_path.write_bytes(b"png")
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".IdleActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_kwargs: (_ for _ in ()).throw(
            profile_builder_new_session.RecommendationProviderError("vlm unavailable")
        ),
    )

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["steps"][0]["confirmed_tap"] = {"x": 9, "y": 8}
    state["steps"][0]["source"] = "manual"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    step = response.json()["new_session_steps"][0]
    assert step["recommended_tap"] == {
        "point": None,
        "reason": None,
        "status": "failed",
    }
    assert step["confirmed_tap"] is None
    assert step["source"] is None


async def test_capture_new_session_step_recapture_archives_previous_artifacts(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    capture_round = {"value": 0}

    async def _capture(device, session_dir, step, **_kwargs):
        capture_round["value"] += 1
        xml_path = session_dir / "new_session_step_0.xml"
        screenshot_path = session_dir / "new_session_step_0.png"
        xml_path.write_text(f"<hierarchy round='{capture_round['value']}'/>", encoding="utf-8")
        screenshot_path.write_bytes(f"png-{capture_round['value']}".encode("utf-8"))
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".IdleActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_kwargs: {"x": 111, "y": 222, "reason": "plus button"},
    )

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    first = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )
    assert second.status_code == 200, second.text

    body = second.json()
    step = body["new_session_steps"][0]
    assert step["xml_artifact"] == "new_session_step_0.xml"
    assert step["screenshot_artifact"] == "new_session_step_0.png"
    assert (artifact_dir / "new_session_step_0.xml").read_text(encoding="utf-8") == (
        "<hierarchy round='2'/>"
    )
    assert (artifact_dir / "new_session_step_0.png").read_bytes() == b"png-2"

    archived_xml = sorted(artifact_dir.glob("capture_new_session_step_0_*.xml"))
    archived_png = sorted(artifact_dir.glob("capture_new_session_step_0_*.png"))
    assert len(archived_xml) == 1
    assert len(archived_png) == 1
    assert archived_xml[0].read_text(encoding="utf-8") == "<hierarchy round='1'/>"
    assert archived_png[0].read_bytes() == b"png-1"
    assert archived_xml[0].name in body["session"]["artifacts"]
    assert archived_png[0].name in body["session"]["artifacts"]


async def test_capture_new_session_step_recapture_archives_same_second_without_collision(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    capture_round = {"value": 0}

    class _FixedDateTime:
        @staticmethod
        def now(_tz=None):
            class _FixedMoment:
                @staticmethod
                def strftime(_fmt):
                    return "20260426123456"

            return _FixedMoment()

    async def _capture(device, session_dir, step, **_kwargs):
        capture_round["value"] += 1
        xml_path = session_dir / "new_session_step_0.xml"
        screenshot_path = session_dir / "new_session_step_0.png"
        xml_path.write_text(f"<hierarchy round='{capture_round['value']}'/>", encoding="utf-8")
        screenshot_path.write_bytes(f"png-{capture_round['value']}".encode("utf-8"))
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".IdleActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.datetime", _FixedDateTime)
    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_kwargs: {"x": 111, "y": 222, "reason": "plus button"},
    )

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    for _ in range(3):
        response = await client.post(
            f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
            headers=headers,
        )
        assert response.status_code == 200, response.text

    archived_xml = sorted(artifact_dir.glob("capture_new_session_step_0_*.xml"))
    archived_png = sorted(artifact_dir.glob("capture_new_session_step_0_*.png"))
    assert len(archived_xml) == 2
    assert len(archived_png) == 2
    assert sorted(path.read_text(encoding="utf-8") for path in archived_xml) == [
        "<hierarchy round='1'/>",
        "<hierarchy round='2'/>",
    ]
    assert sorted(path.read_bytes() for path in archived_png) == [b"png-1", b"png-2"]


async def test_capture_new_session_step_recapture_failure_preserves_previous_artifacts(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    state_path = artifact_dir / "new_session_state.json"
    capture_round = {"value": 0}

    async def _capture(device, session_dir, step, **_kwargs):
        capture_round["value"] += 1
        if capture_round["value"] == 2:
            raise RuntimeError("capture broke")
        xml_path = session_dir / "new_session_step_0.xml"
        screenshot_path = session_dir / "new_session_step_0.png"
        xml_path.write_text("<hierarchy round='1'/>", encoding="utf-8")
        screenshot_path.write_bytes(b"png-1")
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".IdleActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_kwargs: {"x": 111, "y": 222, "reason": "plus button"},
    )

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    first = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_step = first.json()["new_session_steps"][0]

    second = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )
    assert second.status_code == 502, second.text

    state = json.loads(state_path.read_text(encoding="utf-8"))
    step = state["steps"][0]
    assert step["xml_artifact"] == first_step["xml_artifact"]
    assert step["screenshot_artifact"] == first_step["screenshot_artifact"]
    assert (artifact_dir / step["xml_artifact"]).read_text(encoding="utf-8") == "<hierarchy round='1'/>"
    assert (artifact_dir / step["screenshot_artifact"]).read_bytes() == b"png-1"

    xml_download = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}/artifacts/{step['xml_artifact']}",
        headers=headers,
    )
    png_download = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}/artifacts/{step['screenshot_artifact']}",
        headers=headers,
    )
    assert xml_download.status_code == 200, xml_download.text
    assert png_download.status_code == 200
    assert xml_download.text == "<hierarchy round='1'/>"
    assert png_download.content == b"png-1"


async def test_capture_new_session_step_stays_consistent_during_overlapping_config_change(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    recommend_started = threading.Event()
    allow_recommend = threading.Event()

    async def _capture(device, session_dir, step, **_kwargs):
        xml_path = session_dir / "new_session_step_0.xml"
        screenshot_path = session_dir / "new_session_step_0.png"
        xml_path.write_text("<hierarchy/>", encoding="utf-8")
        screenshot_path.write_bytes(b"png")
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".IdleActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    def _recommend(**_kwargs):
        recommend_started.set()
        allow_recommend.wait()
        return {"x": 111, "y": 222, "reason": "plus button"}

    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        _recommend,
    )

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    capture_task = asyncio.create_task(
        client.post(
            f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
            headers=headers,
        )
    )
    await asyncio.to_thread(recommend_started.wait)

    reconfig_task = asyncio.create_task(
        client.put(
            f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
            json={"strategy": "disabled", "step_count": 0},
            headers=headers,
        )
    )

    await asyncio.sleep(0)
    allow_recommend.set()

    capture_response = await capture_task
    reconfig_response = await reconfig_task

    assert capture_response.status_code == 200, capture_response.text
    assert reconfig_response.status_code == 200, reconfig_response.text
    capture_body = capture_response.json()
    assert capture_body["new_session_strategy"] == "guided_tap_sequence"
    assert capture_body["new_session_steps"][0]["recommended_tap"]["status"] == "ready"
    assert capture_body["new_session_steps"][0]["xml_artifact"] == "new_session_step_0.xml"
    assert (artifact_dir / "new_session_step_0.xml").exists()
    assert (artifact_dir / "new_session_step_0.png").exists()

    final_response = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )
    assert final_response.status_code == 200, final_response.text
    assert "new_session_step_0.xml" in final_response.json()["artifacts"]

async def test_capture_new_session_step_malformed_recommendation_degrades_to_failed(
    client, monkeypatch
):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    async def _capture(device, session_dir, step, **_kwargs):
        xml_path = session_dir / "new_session_step_0.xml"
        screenshot_path = session_dir / "new_session_step_0.png"
        xml_path.write_text("<hierarchy/>", encoding="utf-8")
        screenshot_path.write_bytes(b"png")
        return CapturedState(
            step=step,
            package="com.aliyun.tongyi",
            activity=".IdleActivity",
            xml_path=xml_path,
            screenshot_path=screenshot_path,
        )

    class _MalformedResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": [{"type": "text", "text": "not json"}]}}]}

    async def _get_config(_key):
        return {"base_url": "http://vlm.test", "model": "demo", "api_key": "secret"}

    monkeypatch.setattr("autoagent.api.profile_builder.capture_android_state", _capture)
    monkeypatch.setattr("autoagent.api.profile_builder.get_config", _get_config)
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.httpx.post",
        lambda *args, **kwargs: _MalformedResponse(),
    )

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    step = response.json()["new_session_steps"][0]
    assert step["recommended_tap"] == {
        "point": None,
        "reason": None,
        "status": "failed",
    }


async def test_confirm_new_session_step_writes_tap_xy_into_draft_yaml(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 2},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/confirm",
        json={"x": 111, "y": 222, "source": "manual"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["new_session_strategy"] == "guided_tap_sequence"
    assert body["new_session_steps"][0]["confirmed_tap"] == {"x": 111, "y": 222}
    assert body["new_session_steps"][0]["source"] == "manual"
    assert "new_session_action:" in body["draft_profile_yaml"]
    assert body["draft_profile_yaml"].index("x: 111") < body["draft_profile_yaml"].index("y: 222")

    second = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/1/confirm",
        json={"x": 321, "y": 654, "source": "manual"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["new_session_steps"][1]["confirmed_tap"] == {"x": 321, "y": 654}
    assert second_body["new_session_steps"][1]["source"] == "manual"
    yaml_text = second_body["draft_profile_yaml"]
    assert yaml_text.index("x: 111") < yaml_text.index("x: 321")
    assert yaml_text.index("x: 321") < yaml_text.index("y: 654")


async def test_disable_new_session_strategy_clears_yaml_sequence(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    artifact_dir = Path(session["artifact_dir"])
    draft_path = artifact_dir / "draft_profile.yaml"

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    confirmed = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/confirm",
        json={"x": 11, "y": 22, "source": "manual"},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert "x: 11" in confirmed.json()["draft_profile_yaml"]

    generated = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/draft",
        json={"draft_mode": "rule", "inject_llm": False},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    assert draft_path.exists()

    disabled = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "disabled", "step_count": 0},
        headers=headers,
    )

    assert disabled.status_code == 200, disabled.text
    body = disabled.json()
    assert body["new_session_strategy"] == "disabled"
    assert body["new_session_steps"] == []
    assert "new_session_action: []" in body["draft_profile_yaml"]
    assert "x: 11" not in body["draft_profile_yaml"]
    assert "new_session_action: []" in draft_path.read_text(encoding="utf-8")


async def test_confirm_new_session_step_rejects_non_prefix_confirmation(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 2},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/1/confirm",
        json={"x": 321, "y": 654, "source": "manual"},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "new-session steps must be confirmed in order"


async def test_confirm_new_session_step_rejects_fake_recommended_choice(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/confirm",
        json={"x": 11, "y": 22, "source": "recommended"},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "recommended tap is not available for this step"


async def test_confirmed_steps_are_returned_in_order_in_draft_yaml(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)

    config = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 2},
        headers=headers,
    )
    assert config.status_code == 200, config.text

    step0 = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/confirm",
        json={"x": 100, "y": 200, "source": "manual"},
        headers=headers,
    )
    assert step0.status_code == 200, step0.text

    step1 = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/1/confirm",
        json={"x": 200, "y": 300, "source": "manual"},
        headers=headers,
    )
    assert step1.status_code == 200, step1.text
    body = step1.json()

    yaml_text = body["draft_profile_yaml"]
    assert yaml_text.count("action: tap_xy") == 2
    assert yaml_text.index("x: 100") < yaml_text.index("x: 200")
