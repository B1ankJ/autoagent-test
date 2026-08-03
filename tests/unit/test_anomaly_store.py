import pytest

from autoagent.anomalies import store
from autoagent.storage.database import init_db


@pytest.mark.asyncio
async def test_record_list_acknowledge_count_delete() -> None:
    await init_db()

    await store.record_anomaly(
        type="duration",
        batch_id="b1",
        sample_id="s1",
        target_profile="p1",
        device_serial="emulator-5554",
        summary="耗时异常",
        detail={"value": 9000, "direction": "high"},
    )
    await store.record_anomaly(
        type="anr",
        batch_id="b2",
        sample_id="s2",
        target_profile="p2",
        device_serial=None,
        summary="ANR",
        detail={"package": "com.x"},
    )

    items, total = await store.list_anomalies(limit=50, offset=0)
    assert total == 2
    assert items[0].created_at is not None
    # newest first — b2 recorded last
    assert items[0].batch_id == "b2"
    assert items[0].detail == {"package": "com.x"}

    # filter by type
    dur, dur_total = await store.list_anomalies(type="duration", limit=50, offset=0)
    assert dur_total == 1 and dur[0].sample_id == "s1"

    # filter by profile
    _, p2_total = await store.list_anomalies(target_profile="p2", limit=50, offset=0)
    assert p2_total == 1

    assert await store.count_unacknowledged() == 2

    # acknowledge the duration one
    target_id = dur[0].id
    assert await store.acknowledge(target_id) is True
    assert await store.acknowledge(999999) is False  # missing id
    assert await store.count_unacknowledged() == 1

    # filter by acknowledged
    _, ack_total = await store.list_anomalies(acknowledged=True, limit=50, offset=0)
    assert ack_total == 1
    _, unack_total = await store.list_anomalies(acknowledged=False, limit=50, offset=0)
    assert unack_total == 1

    # delete by batch
    assert await store.delete_for_batch("b2") == 1
    _, after = await store.list_anomalies(limit=50, offset=0)
    assert after == 1
