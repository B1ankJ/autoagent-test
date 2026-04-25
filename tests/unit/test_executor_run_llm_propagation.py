import pytest

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample


class _StubExecutor(Executor):
    async def execute(self, sample, profile, ctx):
        ctx.llm_responses.append("L1")
        ctx.llm_errors.append(None)
        ctx.llm_responses.append("")
        ctx.llm_errors.append("auth")
        return ["R1", "R2"]


@pytest.mark.asyncio
async def test_run_copies_llm_fields_from_ctx_into_result():
    sample = Sample(id="s1", prompts=["p1", "p2"], mode="gui_android", target_profile="x")
    ctx = ExecutorContext()
    result = await _StubExecutor().run(sample, profile=None, default_timeout_sec=30, ctx=ctx)
    assert result.responses == ["R1", "R2"]
    assert result.llm_responses == ["L1", ""]
    assert result.llm_errors == [None, "auth"]


@pytest.mark.asyncio
async def test_run_default_llm_fields_are_empty_when_ctx_untouched():
    sample = Sample(id="s1", prompts=["p1"], mode="gui_android", target_profile="x")

    class _Legacy(Executor):
        async def execute(self, sample, profile, ctx):
            return ["R1"]

    result = await _Legacy().run(sample, profile=None, default_timeout_sec=30)
    assert result.llm_responses == []
    assert result.llm_errors == []
