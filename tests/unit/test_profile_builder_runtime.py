from autoagent.api.profile_builder import (
    _load_runtime_from_disk,
    _runtime_json_path,
    _store_runtime,
)


def test_store_runtime_persists_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "autoagent.api.profile_builder._session_dir",
        lambda session_id: tmp_path / session_id,
    )

    runtime = {
        "session_id": "pb_123",
        "session_status": "draft",
        "current_step": "capture_idle",
        "step_state": "running",
        "last_error": None,
        "captures": [],
        "connectivity": {
            "status": "idle",
            "result_status": None,
            "result_summary": None,
            "screens": [],
        },
        "recent_screens": [],
    }

    stored = _store_runtime("pb_123", runtime)

    assert stored["current_step"] == "capture_idle"
    assert _runtime_json_path("pb_123").exists()
    assert _load_runtime_from_disk("pb_123")["step_state"] == "running"
