from datetime import datetime, timezone

import pytest

from autoagent.anomalies import store as anomaly_store
from autoagent.health.profile_health import list_profile_health
from autoagent.models.api import SampleResult
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db
from autoagent.storage.devices import upsert_discovered_device
from autoagent.storage.samples import upsert_sample


def _sample(sid, profile, status, ms):
    return SampleResult(
        id=sid, status=status, mode="gui_android", target_profile=profile,
        duration_ms=ms, ended_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_assembly_and_worst_first_order():
    await init_db()
    save_profile_yaml(
        "good",
        "name: good\nplatform: api\napi:\n  base_url: http://x\n  model: m\n  api_key: K\n",
    )
    save_profile_yaml(
        "bad",
        "name: bad\nplatform: android\nserials: ['dev1']\n"
        "package: com.x\n"
        "response_extraction:\n"
        "  method: ui_tree_only\n"
        "  response_container_locator: {type: xpath, value: '//x'}\n"
        "  scroll_container_locator: {type: xpath, value: '//x'}\n"
        "  latest_bubble_match: {type: xpath, value: '//x'}\n",
    )
    for i in range(5):
        await upsert_sample("b", _sample(f"g{i}", "good", "done", 100))
    await upsert_sample("b", _sample("bad1", "bad", "failed", None))
    for i in range(5):
        await anomaly_store.record_anomaly(
            type="duration", batch_id="b", sample_id=f"a{i}", target_profile="bad",
            device_serial="dev1", summary="x", detail={},
        )
    await upsert_discovered_device(
        serial="dev1", model="m", android_version="14",
        adb_keyboard_installed=False, adb_keyboard_enabled=False, online=False,
        seen_at=datetime.now(timezone.utc),
    )

    health = await list_profile_health()
    by_name = {h.name: h for h in health}
    assert by_name["good"].status == "green"
    assert by_name["good"].success_rate == 1.0
    assert by_name["bad"].status == "red"
    assert by_name["bad"].unacked_anomalies == 5
    assert by_name["bad"].devices_online == 0 and by_name["bad"].devices_total == 1
    assert by_name["bad"].serials == ["dev1"]
    assert by_name["good"].serials == []  # non-android → no serials exposed
    assert [h.name for h in health].index("bad") < [h.name for h in health].index("good")
