import pytest
from pydantic import ValidationError

from autoagent.models.api import (
    BatchCreateJSON,
    BatchSummary,
    ProfileBuilderNewSessionConfigRequest,
    ProfileBuilderNewSessionStep,
    ProfileBuilderTapPoint,
    Sample,
    SampleResult,
)


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


def test_profile_builder_new_session_config_rejects_disabled_with_steps():
    with pytest.raises(ValidationError):
        ProfileBuilderNewSessionConfigRequest(strategy="disabled", step_count=3)


def test_profile_builder_new_session_config_rejects_guided_zero_steps():
    with pytest.raises(ValidationError):
        ProfileBuilderNewSessionConfigRequest(strategy="guided_tap_sequence", step_count=0)


def test_profile_builder_new_session_step_rejects_source_without_confirmed_tap():
    with pytest.raises(ValidationError):
        ProfileBuilderNewSessionStep(step_index=0, source="manual")


def test_profile_builder_new_session_step_rejects_confirmed_tap_without_source():
    with pytest.raises(ValidationError):
        ProfileBuilderNewSessionStep(step_index=0, confirmed_tap=ProfileBuilderTapPoint(x=12, y=34))


def test_profile_builder_new_session_step_roundtrip():
    step = ProfileBuilderNewSessionStep(
        step_index=1,
        xml_artifact="capture_1.xml",
        screenshot_artifact="capture_1.png",
        confirmed_tap=ProfileBuilderTapPoint(x=12, y=34),
        source="recommended",
    )

    restored = ProfileBuilderNewSessionStep.model_validate(step.model_dump())

    assert restored == step
