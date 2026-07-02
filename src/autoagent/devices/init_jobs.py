"""In-memory registry for device-initialization jobs.

Init (especially with reboot) can take 90s+, which would blow through a
reverse-proxy read timeout on a synchronous request. So we kick the work
off as a background task and let the frontend poll a job by id. Process-
local and non-persistent — a restart drops in-flight jobs, which is fine
for an operator-triggered action.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass
from typing import Literal

from autoagent.devices.initializer import initialize_device
from autoagent.profiles.schemas import AndroidProfile

DeviceStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class DeviceInitState:
    serial: str
    status: DeviceStatus = "pending"
    rebooted: bool = False
    steps_run: int = 0
    duration_ms: int = 0
    error: str | None = None


@dataclass
class InitJob:
    id: str
    profile_name: str
    devices: dict[str, DeviceInitState]
    created_at: float

    def to_dict(self) -> dict:
        all_done = all(d.status in ("done", "failed") for d in self.devices.values())
        return {
            "id": self.id,
            "profile_name": self.profile_name,
            "finished": all_done,
            "devices": [asdict(d) for d in self.devices.values()],
        }


_jobs: dict[str, InitJob] = {}
# Hold task refs so they aren't garbage-collected mid-flight.
_tasks: dict[str, list[asyncio.Task]] = {}


async def _run_one(
    job: InitJob, serial: str, profile: AndroidProfile, reboot_override: bool | None
) -> None:
    state = job.devices[serial]
    state.status = "running"
    result = await initialize_device(serial, profile, reboot_override=reboot_override)
    state.status = "done" if result.ok else "failed"
    state.rebooted = result.rebooted
    state.steps_run = result.steps_run
    state.duration_ms = result.duration_ms
    state.error = result.error


def start_job(
    profile: AndroidProfile, serials: list[str], *, reboot_override: bool | None = None
) -> InitJob:
    import time

    job_id = f"init_{uuid.uuid4().hex[:10]}"
    job = InitJob(
        id=job_id,
        profile_name=profile.name,
        devices={s: DeviceInitState(serial=s) for s in serials},
        created_at=time.time(),
    )
    _jobs[job_id] = job
    # One task per device so they initialize in parallel.
    _tasks[job_id] = [
        asyncio.create_task(_run_one(job, serial, profile, reboot_override))
        for serial in serials
    ]
    return job


def get_job(job_id: str) -> InitJob | None:
    return _jobs.get(job_id)


def prune_old_jobs(max_keep: int = 50) -> None:
    if len(_jobs) <= max_keep:
        return
    # Drop the oldest finished jobs first.
    finished = sorted(
        (j for j in _jobs.values() if j.to_dict()["finished"]),
        key=lambda j: j.created_at,
    )
    for job in finished[: len(_jobs) - max_keep]:
        _jobs.pop(job.id, None)
        _tasks.pop(job.id, None)
