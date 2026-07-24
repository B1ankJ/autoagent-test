from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from autoagent.models.api import Sample, SampleResult
from autoagent.openai_compat.schemas import (
    AutoAgentPayload,
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionResponse,
    ChatCompletionsRequest,
    OpenAIError,
    OpenAIErrorResponse,
)
from autoagent.profiles.registry import load_profile
from autoagent.profiles.schemas import (
    AgentAndroidProfile,
    AgentPcProfile,
    AndroidProfile,
    ApiProfile,
    Profile,
    WebProfile,
)


@dataclass
class OpenAICompatError(Exception):
    status_code: int
    message: str
    error_type: str = "invalid_request_error"
    param: str | None = None
    code: str | None = None
    # Structured, machine-readable detail beyond the free-text message —
    # e.g. {"blocking_session_ids": [...]} for a 429 device-reservation
    # conflict. Mirrors the x_autoagent extension already on the success
    # response shape; None (the default) for every error that doesn't
    # need one.
    extra: dict[str, Any] | None = None

    def to_response(self) -> OpenAIErrorResponse:
        return OpenAIErrorResponse(
            error=OpenAIError(
                message=self.message,
                type=self.error_type,
                param=self.param,
                code=self.code,
            ),
            x_autoagent=self.extra,
        )


def parse_chat_completions_request(payload: dict) -> ChatCompletionsRequest:
    try:
        return ChatCompletionsRequest.model_validate(payload)
    except ValidationError as exc:
        first_error = exc.errors()[0] if exc.errors() else {}
        loc = first_error.get("loc", ())
        param = loc[0] if loc else None
        raise OpenAICompatError(
            status_code=400,
            message=(
                "invalid chat.completions request: "
                f"{first_error.get('msg', 'validation failed')}"
            ),
            param=str(param) if param is not None else None,
            code="invalid_request",
        ) from exc


def ensure_supported_request(body: ChatCompletionsRequest) -> None:
    if body.stream:
        raise OpenAICompatError(
            status_code=400,
            message="stream=true is not supported",
            param="stream",
            code="unsupported_parameter",
        )
    if body.tools is not None:
        raise OpenAICompatError(
            400,
            "tools is not supported",
            param="tools",
            code="unsupported_parameter",
        )
    if body.tool_choice is not None:
        raise OpenAICompatError(
            400,
            "tool_choice is not supported",
            param="tool_choice",
            code="unsupported_parameter",
        )
    if body.functions is not None:
        raise OpenAICompatError(
            400,
            "functions is not supported",
            param="functions",
            code="unsupported_parameter",
        )
    if body.function_call is not None:
        raise OpenAICompatError(
            400,
            "function_call is not supported",
            param="function_call",
            code="unsupported_parameter",
        )
    if body.n != 1:
        raise OpenAICompatError(
            400,
            "only n=1 is supported",
            param="n",
            code="unsupported_parameter",
        )
    if body.response_format is not None:
        raise OpenAICompatError(
            400,
            "response_format is not supported",
            param="response_format",
            code="unsupported_parameter",
        )
    if body.audio is not None:
        raise OpenAICompatError(
            400,
            "audio is not supported",
            param="audio",
            code="unsupported_parameter",
        )
    if body.modalities is not None:
        raise OpenAICompatError(
            400,
            "modalities is not supported",
            param="modalities",
            code="unsupported_parameter",
        )
    if body.parallel_tool_calls is not None:
        raise OpenAICompatError(
            400,
            "parallel_tool_calls is not supported",
            param="parallel_tool_calls",
            code="unsupported_parameter",
        )
    for index, message in enumerate(body.messages):
        if not isinstance(message.content, str):
            raise OpenAICompatError(
                400,
                f"messages[{index}].content non-text content is not supported",
                param="messages",
                code="unsupported_parameter",
            )


def resolve_profile(name: str) -> Profile:
    try:
        profile = load_profile(name)
    except ValueError as exc:
        raise OpenAICompatError(
            status_code=400,
            message=str(exc),
            param="model",
            code="invalid_value",
        ) from exc
    if profile is None:
        raise OpenAICompatError(
            status_code=404,
            message=f"target profile {name!r} not found",
            param="model",
            code="not_found",
        )
    return profile


def mode_for_profile(profile: Profile) -> str:
    if isinstance(profile, ApiProfile):
        return "api"
    if isinstance(profile, WebProfile):
        return "gui_pc_web"
    if isinstance(profile, AndroidProfile):
        return "gui_android"
    if isinstance(profile, AgentPcProfile):
        return "agent_pc"
    if isinstance(profile, AgentAndroidProfile):
        return "agent_android"
    raise OpenAICompatError(
        status_code=400,
        message="unsupported profile platform",
        param="model",
    )


def extract_last_user_text(body: ChatCompletionsRequest) -> str:
    for message in reversed(body.messages):
        if message.role not in ("user", "assistant"):
            continue
        if not isinstance(message.content, str):
            raise OpenAICompatError(
                status_code=400,
                message="non-text message content is not supported",
                param="messages",
                code="unsupported_parameter",
            )
        if message.content.strip():
            return message.content
    raise OpenAICompatError(
        status_code=400,
        message="messages must include at least one non-empty user or assistant message",
        param="messages",
        code="invalid_messages",
    )


def build_sample_from_request(body: ChatCompletionsRequest, profile: Profile) -> Sample:
    return Sample(
        id=f"chatcmpl_{uuid.uuid4().hex[:12]}",
        prompts=[extract_last_user_text(body)],
        mode=mode_for_profile(profile),
        target_profile=body.model,
        new_session=body.new_session,
        session_id=body.session_id,
        end_session=body.end_session,
        timeout_sec=body.timeout_sec,
        retry=body.retry,
        dry_run=body.dry_run,
        metadata=dict(body.metadata),
    )


def select_effective_response(
    responses: list[str],
    llm_responses: list[str],
    llm_errors: list[str | None],
) -> str:
    """The response content this system actually stands behind for the first
    prompt: the LLM-reviewed extraction when it ran and succeeded, otherwise
    the raw extraction. Anything that previews/labels "the response" for a
    sample (API replies, batch-list previews, empty-response detection)
    should go through this so they agree with each other.
    """
    if llm_responses and llm_errors:
        first_error = llm_errors[0]
        first_llm = llm_responses[0]
        if first_error is None and first_llm:
            return first_llm
    return responses[0] if responses else ""


def select_message_content(result: SampleResult, profile: Profile) -> str:
    llm_enabled = bool(getattr(profile, "llm_response_enabled", lambda: False)())
    if not llm_enabled:
        return result.responses[0] if result.responses else ""
    return select_effective_response(result.responses, result.llm_responses, result.llm_errors)


def build_chat_completion_response(
    body: ChatCompletionsRequest,
    result: SampleResult,
    profile: Profile,
) -> ChatCompletionResponse:
    content = select_message_content(result, profile)
    sample_id = result.id.removeprefix("chatcmpl_")
    return ChatCompletionResponse(
        id=f"chatcmpl_{sample_id}",
        created=int(time.time()),
        model=body.model,
        choices=[
            ChatCompletionChoice(
                message=ChatCompletionMessage(content=content),
            )
        ],
        x_autoagent=AutoAgentPayload(
            sample_id=result.id,
            status=result.status,
            attempt_count=result.attempt_count,
            duration_ms=result.duration_ms,
            responses=list(result.responses),
            llm_responses=list(result.llm_responses),
            llm_errors=list(result.llm_errors),
            logs_dir=result.logs_dir,
            metadata=dict(result.metadata),
        ),
    )
