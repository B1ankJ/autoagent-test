import csv
import io
import json

from autoagent.models.api import Sample

PROMPT_SEP = "\u241f"  # Unit Separator


def _parse_bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "y", "t"}


def load_csv(text: str) -> list[Sample]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[Sample] = []
    for row in reader:
        prompts = [p for p in row["prompts"].split(PROMPT_SEP) if p != ""]
        md_raw = (row.get("metadata") or "").strip()
        md = json.loads(md_raw) if md_raw else {}
        s = Sample.model_validate(
            {
                "id": row["id"],
                "prompts": prompts,
                "mode": row["mode"],
                "target_profile": row["target_profile"],
                "new_session": _parse_bool(row.get("new_session", "true")),
                "metadata": md,
            }
        )
        out.append(s)
    return out
