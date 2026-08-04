from __future__ import annotations

import logging
from dataclasses import dataclass

from autoagent.anomalies import store
from autoagent.anomalies.duration_detector import _format_summary, evaluate_duration
from autoagent.storage.samples import distinct_sample_profiles, timed_samples_for_profile

_log = logging.getLogger(__name__)

# Match the live detector's recency cap (see duration_detector.check_duration_anomaly,
# which baselines off recent_durations_for_profile(limit=500)).
_BASELINE_CAP = 500


@dataclass
class BackfillResult:
    scanned: int
    created: int


async def backfill_duration_anomalies() -> BackfillResult:
    """Scan every profile's historical timed samples through the same IQR
    duration detector the live hook uses, recording anomalies it finds.
    Point-in-time: each sample is judged against the samples before it.
    Idempotent: samples that already have a duration anomaly are skipped."""
    already = await store.existing_duration_sample_ids()
    scanned = 0
    created = 0
    for profile in await distinct_sample_profiles():
        samples = await timed_samples_for_profile(profile)
        durations: list[int] = []
        for ts in samples:
            scanned += 1
            baseline = durations[-_BASELINE_CAP:]
            verdict = evaluate_duration(ts.duration_ms, baseline)
            durations.append(ts.duration_ms)
            if verdict is None or ts.sample_id in already:
                continue
            await store.record_anomaly(
                type="duration",
                batch_id=ts.batch_id,
                sample_id=ts.sample_id,
                target_profile=profile,
                device_serial=ts.device_serial,
                summary=_format_summary(verdict),
                detail=verdict,
            )
            already.add(ts.sample_id)
            created += 1
    _log.info("duration backfill: scanned=%d created=%d", scanned, created)
    return BackfillResult(scanned=scanned, created=created)
