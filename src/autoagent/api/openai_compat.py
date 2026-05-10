from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from autoagent.api._deps import get_scheduler
from autoagent.auth.bearer import BearerAuthError, resolve_bearer_subject
from autoagent.openai_compat.chat_completions import (
    OpenAICompatError,
    build_chat_completion_response,
    build_sample_from_request,
    ensure_supported_request,
    parse_chat_completions_request,
    resolve_profile,
)
from autoagent.services.sync_tests import SyncSampleResultMissingError, execute_sync_sample
from autoagent.storage.samples import list_samples_for_batch

router = APIRouter(prefix="/v1", tags=["openai_compat"])


def _require_openai_bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise OpenAICompatError(
            status_code=401,
            message="Missing bearer token",
            error_type="invalid_request_error",
            code="invalid_api_key",
        )
    try:
        return resolve_bearer_subject(token)
    except BearerAuthError as exc:
        message = "Malformed token" if exc.reason == "malformed" else "Invalid or expired token"
        raise OpenAICompatError(
            status_code=401,
            message=message,
            error_type="invalid_request_error",
            code="invalid_api_key",
        ) from exc


@router.post("/chat/completions")
async def create_chat_completion(request: Request) -> JSONResponse:
    try:
        _require_openai_bearer(request)
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise OpenAICompatError(
                status_code=400,
                message="invalid chat.completions request: malformed JSON body",
                error_type="invalid_request_error",
                code="invalid_request",
            ) from exc
        body = parse_chat_completions_request(payload)
        ensure_supported_request(body)
        profile = resolve_profile(body.model)
        sample = build_sample_from_request(body, profile)
        result = await execute_sync_sample(
            sample,
            get_scheduler_fn=get_scheduler,
            list_samples_for_batch_fn=list_samples_for_batch,
        )
        response = build_chat_completion_response(body, result, profile)
        return JSONResponse(status_code=200, content=response.model_dump())
    except SyncSampleResultMissingError:
        error = OpenAICompatError(
            status_code=500,
            message="no result recorded",
            error_type="api_error",
        )
        return JSONResponse(status_code=500, content=error.to_response().model_dump())
    except OpenAICompatError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_response().model_dump())
    except Exception:
        error = OpenAICompatError(
            status_code=500,
            message="internal execution failure",
            error_type="api_error",
        )
        return JSONResponse(status_code=500, content=error.to_response().model_dump())
