from __future__ import annotations

from collections import Counter
from datetime import datetime

from autoagent.models.api import AnomalyRecord

_TOP_EXAMPLES = 3


def _ref(app_base_url: str, batch_id: str, sample_id: str) -> str:
    base = app_base_url.rstrip("/")
    if base:
        return f"[{sample_id}]({base}/batches/{batch_id}/samples/{sample_id})"
    return f"`{batch_id}/{sample_id}`"


def build_digest_markdown(
    anomalies: list[AnomalyRecord], since: datetime, app_base_url: str
) -> str:
    """DingTalk markdown summarizing anomalies created since `since`: total,
    counts by type and by profile, and a few example rows. Pure — no I/O."""
    total = len(anomalies)
    by_type = Counter(a.type for a in anomalies)
    by_profile = Counter(a.target_profile for a in anomalies)
    type_line = " / ".join(f"{t} {n}" for t, n in by_type.most_common())
    profile_line = " / ".join(f"{p}({n})" for p, n in by_profile.most_common(5))
    lines = [
        "### 📊 异常摘要",
        f"- **自** {since.strftime('%Y-%m-%d %H:%M')} **以来共 {total} 条新异常**",
        f"- **按类型**: {type_line}",
        f"- **Top Profile**: {profile_line}",
        "- **举例**:",
    ]
    for a in anomalies[:_TOP_EXAMPLES]:
        lines.append(f"  - {a.summary} {_ref(app_base_url, a.batch_id, a.sample_id)}")
    return "\n".join(lines)
