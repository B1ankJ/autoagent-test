from __future__ import annotations

from dataclasses import dataclass

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
