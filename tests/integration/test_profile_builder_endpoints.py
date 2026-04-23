from httpx import ASGITransport, AsyncClient

from autoagent.main import app


async def test_profile_builder_session_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/v1/profile-builder/sessions",
            json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        )

        assert create.status_code == 201
        session = create.json()
        assert session["platform"] == "android"
        assert session["status"] == "draft"
        assert session["steps"] == ["idle", "editing", "response"]

        fetched = await client.get(f"/api/v1/profile-builder/sessions/{session['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == session["id"]
