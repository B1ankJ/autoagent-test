import pytest
from pydantic import ValidationError

from autoagent.models.api import BatchCreateJSON, BatchSummary, Sample, SampleResult


def test_sample_defaults():
    s = Sample(id="t1", prompts=["hi"], mode="api", target_profile="p")
    assert s.new_session is False
    assert s.retry == 2
    assert s.dry_run is False
    assert s.metadata == {}


def test_sample_requires_prompts():
    with pytest.raises(ValidationError):
        Sample(id="t1", prompts=[], mode="api", target_profile="p")


def test_sample_mode_enum():
    with pytest.raises(ValidationError):
        Sample(id="t1", prompts=["x"], mode="bogus", target_profile="p")


def test_sample_result_roundtrip():
    r = SampleResult(
        id="t1",
        status="done",
        prompts_sent=["hi"],
        responses=["hello"],
        duration_ms=100,
        attempt_count=1,
        mode="api",
        target_profile="p",
    )
    assert r.model_dump()["status"] == "done"


def test_batch_create_requires_same_mode():
    with pytest.raises(ValidationError):
        BatchCreateJSON(
            name="b",
            mode="api",
            samples=[
                Sample(id="t1", prompts=["x"], mode="api", target_profile="p"),
                Sample(id="t2", prompts=["y"], mode="gui_pc_web", target_profile="p"),
            ],
        )


def test_batch_create_accepts_same_mode():
    b = BatchCreateJSON(
        name="b",
        mode="api",
        samples=[
            Sample(id="t1", prompts=["x"], mode="api", target_profile="p"),
            Sample(id="t2", prompts=["y"], mode="api", target_profile="p"),
        ],
    )
    assert b.mode == "api"
    assert len(b.samples) == 2


def test_batch_summary():
    b = BatchSummary(batch_id="b1", name="n", mode="api", total=10, done=9, failed=1)
    assert b.avg_duration_ms is None
