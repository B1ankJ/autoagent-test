import json

from autoagent.models.api import Sample


def load_jsonl(text: str) -> list[Sample]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty JSONL input")
    out: list[Sample] = []
    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"line {i + 1}: invalid JSON ({e})") from e
        out.append(Sample.model_validate(obj))
    return out
