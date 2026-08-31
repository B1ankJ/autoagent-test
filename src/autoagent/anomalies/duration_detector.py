from __future__ import annotations

import logging
import statistics
from typing import Any

_log = logging.getLogger(__name__)

MIN_HISTORY = 20
IQR_MULTIPLIER = 3.0


def evaluate_duration(value: int, history: list[int]) -> dict[str, Any] | None:
    """IQR-fence outlier check for a duration against a profile's history.

    Returns None when there isn't enough history to trust a baseline
    (< MIN_HISTORY) or when the value sits inside the fences. Otherwise
    returns the verdict payload (used for the anomaly record's detail).
    """
    if len(history) < MIN_HISTORY:
        return None
    # quantiles(n=4) returns the 3 quartile cut points [Q1, Q2, Q3].
    q1, _q2, q3 = statistics.quantiles(history, n=4)
    iqr = q3 - q1
    fence_high = q3 + IQR_MULTIPLIER * iqr
    fence_low = q1 - IQR_MULTIPLIER * iqr
    if value > fence_high:
        direction = "high"
    else:
        return None
    return {
        "value": value,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "fence_low": fence_low,
        "fence_high": fence_high,
        "direction": direction,
        "sample_count": len(history),
    }


def _format_summary(verdict: dict[str, Any]) -> str:
    v = verdict["value"] / 1000
    return (
        f"耗时 {v:.1f}s，高于 P75+{IQR_MULTIPLIER:g}·IQR "
        f"阈值 {verdict['fence_high'] / 1000:.1f}s"
    )


async def check_duration_anomaly(result, batch_id: str) -> None:
    """Scheduler hook: evaluate a finished sample's duration against its
    profile's recent history and persist an anomaly record on a hit. Never
    raises — a detector failure must not crash the sample run."""
    from autoagent.anomalies import store
    from autoagent.storage.samples import recent_durations_for_profile

    try:
        if result.duration_ms is None:
            return
        history = await recent_durations_for_profile(result.target_profile)
        verdict = evaluate_duration(int(result.duration_ms), history)
        if verdict is None:
            return
        await store.record_anomaly(
            type="duration",
            batch_id=batch_id,
            sample_id=result.id,
            target_profile=result.target_profile,
            device_serial=(result.metadata or {}).get("device_serial"),
            summary=_format_summary(verdict),
            detail=verdict,
        )
    except Exception:  # noqa: BLE001
        _log.exception(
            "duration anomaly check failed for sample %s", getattr(result, "id", "?")
        )
