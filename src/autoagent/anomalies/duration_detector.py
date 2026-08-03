from __future__ import annotations

import logging
import statistics
from typing import Any

_log = logging.getLogger(__name__)

MIN_HISTORY = 20
IQR_MULTIPLIER = 1.5


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
    elif value < fence_low:
        direction = "low"
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
