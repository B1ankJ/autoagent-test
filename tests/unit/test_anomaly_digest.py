from datetime import datetime, timezone

from autoagent.anomalies.digest import build_digest_markdown
from autoagent.models.api import AnomalyRecord


def _a(type_, profile, sid):
    return AnomalyRecord(
        id=1, type=type_, batch_id="b", sample_id=sid, target_profile=profile,
        device_serial=None, summary=f"{type_} on {profile}", detail={},
        acknowledged=False, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_build_digest_markdown_groups_and_totals():
    anomalies = [
        _a("duration", "doubao", "s1"),
        _a("duration", "doubao", "s2"),
        _a("anr", "kimi", "s3"),
    ]
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    md = build_digest_markdown(anomalies, since, app_base_url="")
    assert "共 3 条" in md
    assert "duration" in md and "anr" in md
    assert "doubao" in md
