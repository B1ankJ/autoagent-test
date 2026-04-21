import json

from autoagent.models.api import Sample


def load_json(text: str) -> list[Sample]:
    data = json.loads(text)
    # Accept either a bare list of samples or {"samples": [...]}
    if isinstance(data, dict) and "samples" in data:
        data = data["samples"]
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of samples or an object with 'samples' key")
    return [Sample.model_validate(s) for s in data]
