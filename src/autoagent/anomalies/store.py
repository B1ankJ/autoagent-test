from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select

from autoagent.models.api import AnomalyRecord
from autoagent.models.db import Anomaly as AnomalyRow
from autoagent.storage.database import get_sessionmaker


def _row_to_record(r: AnomalyRow) -> AnomalyRecord:
    return AnomalyRecord(
        id=r.id,
        type=r.type,
        batch_id=r.batch_id,
        sample_id=r.sample_id,
        target_profile=r.target_profile,
        device_serial=r.device_serial,
        summary=r.summary,
        detail=json.loads(r.detail_json or "{}"),
        acknowledged=bool(r.acknowledged),
        acknowledged_at=(
            r.acknowledged_at.replace(tzinfo=timezone.utc) if r.acknowledged_at else None
        ),
        created_at=r.created_at.replace(tzinfo=timezone.utc) if r.created_at else None,
    )


async def record_anomaly(
    *,
    type: str,
    batch_id: str,
    sample_id: str,
    target_profile: str,
    device_serial: str | None,
    summary: str,
    detail: dict[str, Any],
) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        s.add(
            AnomalyRow(
                type=type,
                batch_id=batch_id,
                sample_id=sample_id,
                target_profile=target_profile,
                device_serial=device_serial,
                summary=summary,
                detail_json=json.dumps(detail, ensure_ascii=False),
            )
        )
        await s.commit()


async def list_anomalies(
    *,
    type: str | None = None,
    target_profile: str | None = None,
    acknowledged: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int,
    offset: int,
) -> tuple[list[AnomalyRecord], int]:
    sm = get_sessionmaker()
    async with sm() as s:
        conds = []
        if type is not None:
            conds.append(AnomalyRow.type == type)
        if target_profile is not None:
            conds.append(AnomalyRow.target_profile == target_profile)
        if acknowledged is not None:
            conds.append(AnomalyRow.acknowledged == acknowledged)
        if created_after is not None:
            conds.append(AnomalyRow.created_at >= created_after)
        if created_before is not None:
            conds.append(AnomalyRow.created_at <= created_before)

        total = (
            await s.execute(select(func.count()).select_from(AnomalyRow).where(*conds))
        ).scalar_one()
        rows = (
            (
                await s.execute(
                    select(AnomalyRow)
                    .where(*conds)
                    .order_by(AnomalyRow.created_at.desc(), AnomalyRow.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return [_row_to_record(r) for r in rows], int(total)


async def acknowledge(anomaly_id: int) -> bool:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(AnomalyRow, anomaly_id)
        if row is None:
            return False
        row.acknowledged = True
        row.acknowledged_at = datetime.now(timezone.utc)
        await s.commit()
        return True


async def count_unacknowledged() -> int:
    sm = get_sessionmaker()
    async with sm() as s:
        total = (
            await s.execute(
                select(func.count())
                .select_from(AnomalyRow)
                .where(AnomalyRow.acknowledged == False)  # noqa: E712
            )
        ).scalar_one()
        return int(total)


async def unacked_counts_by_profile(since: datetime) -> dict[str, int]:
    """Per profile: number of unacknowledged anomalies created since `since`.
    Feeds the health dashboard's anomaly signal."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(AnomalyRow.target_profile, func.count())
            .where(AnomalyRow.acknowledged == False)  # noqa: E712
            .where(AnomalyRow.created_at >= since)
            .group_by(AnomalyRow.target_profile)
        )
        return {profile: int(count) for profile, count in r.all()}


async def delete_for_batch(batch_id: str) -> int:
    sm = get_sessionmaker()
    async with sm() as s:
        res = await s.execute(delete(AnomalyRow).where(AnomalyRow.batch_id == batch_id))
        await s.commit()
        return res.rowcount or 0
