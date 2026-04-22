from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select

from autoagent.models.api import DeviceInfo
from autoagent.models.db import Device
from autoagent.storage.database import get_sessionmaker


def _to_info(row: Device) -> DeviceInfo:
    return DeviceInfo(
        serial=row.serial,
        label=row.label,
        model=row.model,
        android_version=row.android_version,
        online=row.online,
        enabled=row.enabled,
        last_seen_at=row.last_seen_at,
    )


async def upsert_discovered_device(
    *,
    serial: str,
    model: str | None,
    android_version: str | None,
    online: bool,
    seen_at: datetime,
) -> DeviceInfo:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(Device, serial)
        if row is None:
            row = Device(serial=serial)
            s.add(row)
        row.model = model
        row.android_version = android_version
        row.online = online
        row.last_seen_at = seen_at
        await s.commit()
        await s.refresh(row)
        return _to_info(row)


async def list_devices() -> list[DeviceInfo]:
    sm = get_sessionmaker()
    async with sm() as s:
        rows = await s.execute(select(Device).order_by(desc(Device.online), desc(Device.last_seen_at)))
        return [_to_info(row) for row in rows.scalars().all()]


async def update_device_enabled(serial: str, *, enabled: bool) -> DeviceInfo | None:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(Device, serial)
        if row is None:
            return None
        row.enabled = enabled
        await s.commit()
        await s.refresh(row)
        return _to_info(row)


async def update_device_label(serial: str, label: str | None) -> DeviceInfo | None:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(Device, serial)
        if row is None:
            return None
        row.label = label
        await s.commit()
        await s.refresh(row)
        return _to_info(row)
