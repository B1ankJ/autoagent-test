from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str | list[dict[str, Any]]


class ChatCompletionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False
    new_session: bool = False
    session_id: str | None = None
    end_session: bool = False
    timeout_sec: int | None = Field(default=None, gt=0)
    retry: int = Field(default=2, ge=0)
    dry_run: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    user: str | None = None
    tools: Any | None = None
    tool_choice: Any | None = None
    functions: Any | None = None
    function_call: Any | None = None
    n: int = 1
    response_format: Any | None = None
    audio: Any | None = None
    modalities: Any | None = None
    parallel_tool_calls: bool | None = None


class ChatCompletionMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage
    finish_reason: Literal["stop"] = "stop"


class AutoAgentPayload(BaseModel):
    sample_id: str
    status: str
    attempt_count: int
    duration_ms: int | None = None
    responses: list[str] = Field(default_factory=list)
    llm_responses: list[str] = Field(default_factory=list)
    llm_errors: list[str | None] = Field(default_factory=list)
    logs_dir: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    x_autoagent: AutoAgentPayload


class OpenAIError(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    error: OpenAIError
    # Structured extension alongside the standard OpenAI error envelope —
    # same idea as ChatCompletionResponse.x_autoagent on the success side.
    # None for ordinary errors; populated for ones with machine-readable
    # detail beyond the free-text message (e.g. a 429's blocking_session_ids).
    x_autoagent: dict[str, Any] | None = None
