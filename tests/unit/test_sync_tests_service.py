from __future__ import annotations

import pytest

from autoagent.models.api import Sample, SampleResult
from autoagent.services import sync_tests as mod


@pytest.mark.asyncio
async def test_execute_sync_sample_uses_gui_android_wait_timeout():
    captured: dict[str, object] = {}
    sample = Sample(
        id="s1",
        prompts=["hi"],
        mode="gui_android",
        target_profile="android_profile",
    )

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

    result = await mod.execute_sync_sample(
        sample,
        get_scheduler_fn=lambda: Scheduler(),
        list_samples_for_batch_fn=fake_list,
    )

    assert result.status == "done"
    assert captured["name"] == "sync-s1"
    assert captured["concurrency"] == 1
    assert captured["samples"] == [sample]
    assert captured["batch_id"] == "b1"
    assert captured["timeout_sec"] == 210


@pytest.mark.asyncio
async def test_execute_sync_sample_uses_non_android_default_timeout():
    captured: dict[str, object] = {}

    class Scheduler:
        async def submit(self, **kwargs):
            captured.update(kwargs)
            return "b4"

        async def wait_done(self, batch_id, timeout_sec):
            captured["batch_id"] = batch_id
            captured["timeout_sec"] = timeout_sec

    async def fake_list(_batch_id: str):
        return [
            SampleResult(
                id="s4",
                status="done",
                prompts_sent=["hey"],
                responses=["echo: hey"],
                mode="api",
                target_profile="p_api",
            )
        ]

    sample = Sample(
        id="s4",
        prompts=["hey"],
        mode="api",
        target_profile="p_api",
    )

    result = await mod.execute_sync_sample(
        sample,
        get_scheduler_fn=lambda: Scheduler(),
        list_samples_for_batch_fn=fake_list,
    )

    assert result.status == "done"
    assert captured["batch_id"] == "b4"
    assert captured["timeout_sec"] == 630


@pytest.mark.asyncio
async def test_execute_sync_sample_uses_explicit_timeout_override():
    captured: dict[str, object] = {}

    class Scheduler:
        async def submit(self, **kwargs):
            captured.update(kwargs)
            return "b3"

        async def wait_done(self, batch_id, timeout_sec):
            captured["batch_id"] = batch_id
            captured["timeout_sec"] = timeout_sec

    async def fake_list(_batch_id: str):
        return [
            SampleResult(
                id="s3",
                status="done",
                prompts_sent=["hello"],
                responses=["echo: hello"],
                mode="api",
                target_profile="p_api",
            )
        ]

    sample = Sample(
        id="s3",
        prompts=["hello"],
        mode="api",
        target_profile="p_api",
        timeout_sec=12,
    )

    result = await mod.execute_sync_sample(
        sample,
        get_scheduler_fn=lambda: Scheduler(),
        list_samples_for_batch_fn=fake_list,
    )

    assert result.status == "done"
    assert captured["name"] == "sync-s3"
    assert captured["concurrency"] == 1
    assert captured["samples"] == [sample]
    assert captured["batch_id"] == "b3"
    assert captured["timeout_sec"] == 42


@pytest.mark.asyncio
async def test_execute_sync_sample_raises_when_no_result_recorded():
    class Scheduler:
        async def submit(self, **kwargs):
            return "b2"

        async def wait_done(self, batch_id, timeout_sec):
            return None

    async def fake_list(_batch_id: str):
        return []

    sample = Sample(id="s2", prompts=["yo"], mode="api", target_profile="p_api")

    with pytest.raises(mod.SyncSampleResultMissingError) as exc:
        await mod.execute_sync_sample(
            sample,
            get_scheduler_fn=lambda: Scheduler(),
            list_samples_for_batch_fn=fake_list,
        )

    assert str(exc.value) == "no result recorded"
