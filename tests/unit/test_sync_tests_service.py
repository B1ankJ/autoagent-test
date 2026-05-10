from __future__ import annotations

import pytest
from fastapi import HTTPException

from autoagent.models.api import Sample, SampleResult
from autoagent.services import sync_tests as mod


@pytest.mark.asyncio
async def test_execute_sync_sample_uses_gui_android_wait_timeout(monkeypatch):
    captured: dict[str, object] = {}

    class Scheduler:
        async def submit(self, **kwargs):
            captured.update(kwargs)
            return "b1"

        async def wait_done(self, batch_id, timeout_sec):
            captured["batch_id"] = batch_id
            captured["timeout_sec"] = timeout_sec

    async def fake_list(_batch_id: str):
        return [
            SampleResult(
                id="s1",
                status="done",
                prompts_sent=["hi"],
                responses=["echo: hi"],
                mode="gui_android",
                target_profile="android_profile",
            )
        ]

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    sample = Sample(
        id="s1",
        prompts=["hi"],
        mode="gui_android",
        target_profile="android_profile",
    )

    result = await mod.execute_sync_sample(sample)

    assert result.status == "done"
    assert captured["timeout_sec"] == 210


@pytest.mark.asyncio
async def test_execute_sync_sample_raises_when_no_result_recorded(monkeypatch):
    class Scheduler:
        async def submit(self, **kwargs):
            return "b2"

        async def wait_done(self, batch_id, timeout_sec):
            return None

    async def fake_list(_batch_id: str):
        return []

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    sample = Sample(id="s2", prompts=["yo"], mode="api", target_profile="p_api")

    with pytest.raises(HTTPException) as exc:
        await mod.execute_sync_sample(sample)

    assert exc.value.status_code == 500
    assert exc.value.detail == "no result recorded"
