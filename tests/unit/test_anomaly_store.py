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


@pytest.mark.asyncio
async def test_delete_batch_rows_cascades_to_anomalies() -> None:
    from datetime import datetime, timezone

    from autoagent.models.db import Batch
    from autoagent.storage.batches import delete_batch_rows
    from autoagent.storage.database import get_sessionmaker

    await init_db()
    sm = get_sessionmaker()
    async with sm() as s:
        s.add(
            Batch(
                id="bx",
                name="n",
                mode="api",
                status="done",
                total=1,
                created_at=datetime.now(timezone.utc),
            )
        )
        await s.commit()
    await store.record_anomaly(
        type="duration",
        batch_id="bx",
        sample_id="s1",
        target_profile="p",
        device_serial=None,
        summary="x",
        detail={},
    )
    assert (await store.list_anomalies(limit=10, offset=0))[1] == 1
    assert await delete_batch_rows("bx") is True
    assert (await store.list_anomalies(limit=10, offset=0))[1] == 0


@pytest.mark.asyncio
async def test_unacked_counts_by_profile():
    from datetime import datetime, timedelta, timezone

    await init_db()
    now = datetime.now(timezone.utc)
    for i in range(3):
        await store.record_anomaly(
            type="duration", batch_id="b", sample_id=f"s{i}", target_profile="p1",
            device_serial=None, summary="x", detail={},
        )
    await store.record_anomaly(
        type="anr", batch_id="b", sample_id="sx", target_profile="p2",
        device_serial=None, summary="y", detail={},
    )
    items, _ = await store.list_anomalies(target_profile="p1", limit=10, offset=0)
    await store.acknowledge(items[0].id)

    counts = await store.unacked_counts_by_profile(now - timedelta(days=7))
    assert counts == {"p1": 2, "p2": 1}


@pytest.mark.asyncio
async def test_list_anomalies_time_filter():
    from datetime import datetime, timedelta, timezone

    await init_db()
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    now = datetime.now(timezone.utc)
    _, after_future = await store.list_anomalies(
        created_after=now + timedelta(hours=1), limit=10, offset=0
    )
    assert after_future == 0
    _, after_past = await store.list_anomalies(
        created_after=now - timedelta(hours=1), limit=10, offset=0
    )
    assert after_past == 1
    _, before_past = await store.list_anomalies(
        created_before=now - timedelta(hours=1), limit=10, offset=0
    )
    assert before_past == 0


@pytest.mark.asyncio
async def test_existing_duration_sample_ids():
    await init_db()
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    await store.record_anomaly(
        type="anr", batch_id="b", sample_id="s2", target_profile="p",
        device_serial=None, summary="y", detail={},
    )
    ids = await store.existing_duration_sample_ids()
    assert ids == {"s1"}
