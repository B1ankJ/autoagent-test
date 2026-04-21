import json
from pathlib import Path

from autoagent.config.settings import get_settings
from autoagent.models.api import SampleResult
from autoagent.results.writer import ResultWriter


def _res(sid: str, status: str = "done") -> SampleResult:
    return SampleResult(
        id=sid, status=status, prompts_sent=["p"], responses=["r"],
        duration_ms=10, attempt_count=1, mode="api", target_profile="pf",
    )


def test_writes_jsonl_in_order():
    w = ResultWriter("b1")
    w.append(_res("t1"))
    w.append(_res("t2", "failed"))
    w.close()
    path = get_settings().data_root / "results" / "b1.jsonl"
    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "t1"
    assert json.loads(lines[1])["status"] == "failed"


def test_reopen_appends():
    w = ResultWriter("b2")
    w.append(_res("t1"))
    w.close()
    w2 = ResultWriter("b2")
    w2.append(_res("t2"))
    w2.close()
    path = get_settings().data_root / "results" / "b2.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 2
