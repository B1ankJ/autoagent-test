from autoagent.models.api import SampleResult


def test_sample_result_default_llm_fields_are_empty_lists():
    result = SampleResult(
        id="s1",
        status="done",
        prompts_sent=["hi"],
        responses=["hello"],
        duration_ms=1,
        attempt_count=1,
        mode="gui_android",
        target_profile="qwen_android",
    )
    assert result.llm_responses == []
    assert result.llm_errors == []


def test_sample_result_dumps_llm_fields_alongside_responses():
    result = SampleResult(
        id="s1",
        status="done",
        prompts_sent=["p1", "p2"],
        responses=["r1", "r2"],
        llm_responses=["lr1", ""],
        llm_errors=[None, "auth"],
        duration_ms=1,
        attempt_count=1,
        mode="gui_android",
        target_profile="qwen_android",
    )
    dumped = result.model_dump()
    assert dumped["llm_responses"] == ["lr1", ""]
    assert dumped["llm_errors"] == [None, "auth"]
