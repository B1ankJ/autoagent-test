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
