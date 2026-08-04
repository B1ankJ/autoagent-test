from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from autoagent.anomalies import store as anomaly_store
from autoagent.models.api import ProfileHealth
from autoagent.profiles.registry import list_profile_names, load_profile
from autoagent.storage.devices import list_devices
from autoagent.storage.samples import avg_duration_by_profile, success_stats_by_profile

SUCCESS_RED = 0.5
SUCCESS_YELLOW = 0.9
ANOMALY_RED = 5
ANOMALY_YELLOW = 1

# Ordered worst → best for "worst-of" reduction and worst-first sorting.
_SEVERITY = {"red": 0, "yellow": 1, "green": 2, "nodata": 3}


@dataclass
class HealthMetrics:
    total_runs: int
    success_rate: float | None
    unacked_anomalies: int
    devices_online: int | None  # None = signal not applicable (non-android / unbound)
    devices_total: int | None


def _success_signal(rate: float | None) -> str:
    if rate is None:
        return "green"
    if rate < SUCCESS_RED:
        return "red"
    if rate < SUCCESS_YELLOW:
        return "yellow"
    return "green"


def _anomaly_signal(count: int) -> str:
    if count >= ANOMALY_RED:
        return "red"
    if count >= ANOMALY_YELLOW:
        return "yellow"
    return "green"


def _device_signal(online: int | None, total: int | None) -> str | None:
    if not total or online is None:  # not applicable / no live count → don't judge
        return None
    if online == 0:
        return "red"
    if online < total:
        return "yellow"
    return "green"


def compute_health(m: HealthMetrics) -> str:
    """Worst-of the participating signals (success rate, unacked anomalies,
    device pool). Avg duration is display-only and deliberately not a signal.
    No terminal runs in the window → 'nodata' (no basis to judge)."""
    if m.total_runs == 0:
        return "nodata"
    signals = [_success_signal(m.success_rate), _anomaly_signal(m.unacked_anomalies)]
    dev = _device_signal(m.devices_online, m.devices_total)
    if dev is not None:
        signals.append(dev)
    return min(signals, key=lambda s: _SEVERITY[s])


WINDOW_DAYS = 7
# Profile.platform values (see profiles/schemas.py) for android-backed profiles.
# Note: this is the profile's `platform` field, not Sample.mode — a "gui_android"
# mode sample targets a profile whose platform is "android", not "gui_android".
_ANDROID_PLATFORMS = {"android", "agent_android"}


async def list_profile_health(now: datetime | None = None) -> list[ProfileHealth]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)

    success = await success_stats_by_profile(since)
    durations = await avg_duration_by_profile(since=since)
    anomalies = await anomaly_store.unacked_counts_by_profile(since)
    devices = {d.serial: d for d in await list_devices()}

    out: list[ProfileHealth] = []
    for name in list_profile_names():
        profile = load_profile(name)
        if profile is None:
            continue
        done, total = success.get(name, (0, 0))
        rate = (done / total) if total else None

        online_ct: int | None = None
        total_ct: int | None = None
        serials: list[str] = []
        if str(profile.platform) in _ANDROID_PLATFORMS:
            serial = getattr(profile, "serial", None)
            serials = list(getattr(profile, "serials", None) or [])
            if serial and serial not in serials:
                serials = [serial, *serials]
            if serials:
                total_ct = len(serials)
                online_ct = sum(1 for s in serials if devices.get(s) and devices[s].online)

        metrics = HealthMetrics(
            total_runs=total,
            success_rate=rate,
            unacked_anomalies=anomalies.get(name, 0),
            devices_online=online_ct,
            devices_total=total_ct,
        )
        out.append(
            ProfileHealth(
                name=name,
                platform=str(profile.platform),
                status=compute_health(metrics),
                success_rate=rate,
                total_runs=total,
                avg_duration_ms=durations.get(name),
                unacked_anomalies=anomalies.get(name, 0),
                devices_online=online_ct,
                devices_total=total_ct,
                serials=serials,
            )
        )

    out.sort(key=lambda h: (_SEVERITY[h.status], h.name))
    return out
