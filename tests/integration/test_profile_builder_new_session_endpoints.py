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
