from pathlib import Path

import pytest

from autoagent.loaders.jsonl_loader import load_jsonl
from autoagent.loaders.json_loader import load_json
from autoagent.loaders.csv_loader import load_csv

FIX = Path(__file__).parent.parent / "fixtures"


def test_load_jsonl():
    samples = load_jsonl((FIX / "batch_sample.jsonl").read_text())
    assert len(samples) == 2
    assert samples[0].id == "t1"
    assert samples[1].prompts == ["hi", "再说一遍"]
    assert samples[1].new_session is False
    assert samples[1].metadata == {"tag": "multi"}


def test_load_json():
    samples = load_json((FIX / "batch_sample.json").read_text())
    assert len(samples) == 2
    assert samples[0].prompts == ["hello"]


def test_load_csv():
    samples = load_csv((FIX / "batch_sample.csv").read_text())
    assert len(samples) == 2
    assert samples[1].prompts == ["hi", "again"]
    assert samples[1].new_session is False
    assert samples[1].metadata == {"tag": "multi"}


def test_load_jsonl_empty_raises():
    with pytest.raises(ValueError):
        load_jsonl("")


def test_load_json_non_list_raises():
    with pytest.raises(ValueError):
        load_json('{"hello": "world"}')
